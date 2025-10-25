from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore


class LocalLlamaRunner:
    """Drive a locally hosted LLaMA2 model using common runtimes."""

    def __init__(self):
        self.requested_provider = (os.environ.get("LLAMA2_PROVIDER") or "").lower().strip()
        self.model_name = os.environ.get("LLAMA2_MODEL") or "llama2"
        self.model_path = (
            os.environ.get("LLAMA2_MODEL_PATH")
            or os.environ.get("LLAMA_CPP_MODEL_PATH")
            or os.environ.get("TRANSFORMERS_MODEL_PATH")
        )
        self._provider: Optional[str] = None
        self._engine: Any = None
        self._loaded = False
        self._load_error: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Public helpers
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        """Return True when any local backend is ready."""
        self._ensure_engine()
        return self._engine is not None

    def availability_message(self) -> str:
        """Describe why the local runner is unavailable."""
        self._ensure_engine()
        return self._load_error or (
            "Unable to initialize a local LLaMA2 runtime. "
            "Install and configure ollama, llama.cpp, or transformers with offline weights."
        )

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> Optional[str]:
        """Invoke the chosen runtime and return the assistant reply."""
        self._ensure_engine()
        if not self._engine or not self._provider:
            return None

        if self._provider == "ollama":
            return self._run_ollama(system_prompt, user_prompt, max_tokens, temperature)
        if self._provider == "llama_cpp":
            return self._run_llama_cpp(system_prompt, user_prompt, max_tokens, temperature)
        if self._provider == "transformers":
            return self._run_transformers(system_prompt, user_prompt, max_tokens, temperature)
        return None

    @property
    def provider_name(self) -> Optional[str]:
        self._ensure_engine()
        return self._provider

    @property
    def model_descriptor(self) -> str:
        if self._provider == "ollama":
            return self.model_name
        if self._provider == "llama_cpp":
            return self.model_path or "<unknown GGUF>"
        if self._provider == "transformers":
            return self.model_path or "<unknown checkpoint>"
        return "<uninitialised>"

    # ------------------------------------------------------------------ #
    # Internal loading
    # ------------------------------------------------------------------ #
    def _candidate_providers(self) -> Sequence[str]:
        if self.requested_provider:
            return [self.requested_provider]
        return ("ollama", "llama_cpp", "transformers")

    def _append_error(self, message: str) -> None:
        if self._load_error:
            self._load_error = f"{self._load_error} | {message}"
        else:
            self._load_error = message

    def _ensure_engine(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        for candidate in self._candidate_providers():
            loader = getattr(self, f"_init_{candidate}", None)
            if not loader:
                continue
            engine = loader()
            if engine is None:
                continue
            self._provider = candidate
            self._engine = engine
            self._load_error = None
            return

        if not self._load_error:
            self._load_error = (
                "No local LLaMA2 runtime could be initialized. "
                "Try setting LLAMA2_PROVIDER to one of: ollama, llama_cpp, transformers."
            )

    # ------------------------------------------------------------------ #
    # Provider initializers
    # ------------------------------------------------------------------ #
    def _init_ollama(self) -> Optional[Tuple[Any, str]]:
        host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        try:
            import ollama  # type: ignore
        except ImportError:
            try:
                import requests  # type: ignore
            except ImportError as exc:
                self._append_error(
                    "Ollama Python client not found and requests is unavailable for fallback: "
                    f"{exc}"
                )
                return None

            class OllamaRESTClient:
                def __init__(self, base_url: str) -> None:
                    self.base_url = base_url

                def chat(self, *, model: str, messages: List[Dict[str, str]], options: Dict[str, Any]) -> Any:
                    payload = {
                        "model": model,
                        "messages": messages,
                        "options": {
                            "temperature": options.get("temperature", 0.2),
                            "num_predict": options.get("num_predict"),
                        },
                    }
                    response = requests.post(
                        f"{self.base_url}/api/chat",
                        json=payload,
                        timeout=options.get("timeout", 120),
                    )
                    response.raise_for_status()
                    return response.json()

            return (OllamaRESTClient(host), self.model_name or "llama2")

        model = self.model_name or "llama2"
        client_factory = getattr(ollama, "Client", None)
        if callable(client_factory):
            return (client_factory(host=host), model)
        os.environ.setdefault("OLLAMA_HOST", host)
        return (ollama, model)

    def _init_llama_cpp(self) -> Optional[Any]:
        try:
            from llama_cpp import Llama  # type: ignore
        except ImportError as exc:
            self._append_error(f"llama-cpp-python not installed: {exc}")
            return None

        model_path = self.model_path
        if not model_path:
            self._append_error(
                "Set LLAMA2_MODEL_PATH to the GGUF weights to use the llama.cpp runtime."
            )
            return None
        if not os.path.exists(model_path):
            self._append_error(f"LLaMA weights not found at {model_path}")
            return None

        try:
            ctx_size = int(os.environ.get("LLAMA_CPP_CTX", "4096"))
        except ValueError:
            ctx_size = 4096

        try:
            return Llama(model_path=model_path, n_ctx=ctx_size)
        except Exception as exc:  # pragma: no cover - runtime dependent
            self._append_error(f"llama.cpp failed to load model: {exc}")
            return None

    def _init_transformers(self) -> Optional[Any]:
        try:
            from transformers import (  # type: ignore
                AutoModelForCausalLM,
                AutoTokenizer,
                pipeline,
            )
        except ImportError as exc:
            self._append_error(f"transformers not installed: {exc}")
            return None

        model_location = self.model_path
        if not model_location:
            self._append_error(
                "Set LLAMA2_MODEL_PATH or TRANSFORMERS_MODEL_PATH to a local directory "
                "containing LLaMA2 weights for transformers."
            )
            return None

        try:
            tokenizer = AutoTokenizer.from_pretrained(model_location, local_files_only=True)
            model = AutoModelForCausalLM.from_pretrained(model_location, local_files_only=True)
            text_pipe = pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
            )
            return text_pipe
        except Exception as exc:  # pragma: no cover - heavy dependency
            self._append_error(f"transformers failed to load model: {exc}")
            return None

    # ------------------------------------------------------------------ #
    # Provider execution helpers
    # ------------------------------------------------------------------ #
    def _run_ollama(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Optional[str]:
        client, model = self._engine
        try:
            chat_callable = getattr(client, "chat", None)
            if callable(chat_callable):
                response = chat_callable(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    options={
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                )
            else:
                response = client.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    options={
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                )
        except Exception as exc:
            self._append_error(f"Ollama execution error: {exc}")
            return None

        if isinstance(response, dict):
            message = response.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content.strip()
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    content = first.get("message", {}).get("content") or first.get("text")
                    if isinstance(content, str):
                        return content.strip()
        return None

    def _run_llama_cpp(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Optional[str]:
        engine = self._engine
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            output = engine.create_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except AttributeError:
            prompt = (
                f"{system_prompt.strip()}\n\n"
                f"User: {user_prompt.strip()}\n"
                "Assistant:"
            )
            try:
                output = engine(
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=["User:", "Assistant:"],
                )
            except Exception as exc:  # pragma: no cover - runtime dependent
                self._append_error(f"llama.cpp inference error: {exc}")
                return None
        except Exception as exc:  # pragma: no cover - runtime dependent
            self._append_error(f"llama.cpp inference error: {exc}")
            return None

        if isinstance(output, dict):
            choices = output.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict):
                        content = message.get("content")
                        if isinstance(content, str):
                            return content.strip()
                    text = first.get("text")
                    if isinstance(text, str):
                        return text.strip()
        return None

    def _run_transformers(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Optional[str]:
        pipe = self._engine
        prompt = (
            f"{system_prompt.strip()}\n\n"
            f"User: {user_prompt.strip()}\n"
            "Assistant:"
        )
        try:
            outputs = pipe(
                prompt,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
            )
        except Exception as exc:  # pragma: no cover - runtime dependent
            self._append_error(f"transformers inference error: {exc}")
            return None

        if outputs:
            first = outputs[0]
            generated = first.get("generated_text") if isinstance(first, dict) else str(first)
            if isinstance(generated, str):
                reply = generated.split("Assistant:", 1)[-1] if "Assistant:" in generated else generated
                return reply.strip()
        return None


class LocalModel:
    """LLM wrapper with privacy-aware routing."""

    PRIVATE_SYSTEM_PROMPT = (
        "You are the user's trusted local assistant running entirely on a private machine. "
        "Handle sensitive information responsibly. "
        "If you do not have enough information, explicitly ask the user what you need instead "
        "of guessing. Keep answers concise and actionable."
    )

    INTERPRET_PRIVATE_PROMPT = (
        "You are a command planner for a privacy-preserving assistant. "
        "Convert the user's instruction into JSON. "
        "Return either an object with an `action` and `payload`, or an object with an `actions` "
        "array containing such entries. "
        "Allowed actions: send_email, schedule_meeting, search_web, order_pizza, pdf_question, "
        "answer_question. "
        "When required information is missing, include a `clarifications` array where each item "
        "has `action`, `field`, and `prompt` explaining what you need from the user. "
        "Do not include any natural-language commentary outside of JSON."
    )

    def __init__(self):
        self.openai_key = os.environ.get("OPENAI_API_KEY")
        self.openai_project = os.environ.get("OPENAI_PROJECT")
        self.openai_organization = (
            os.environ.get("OPENAI_ORG") or os.environ.get("OPENAI_ORGANIZATION")
        )

        self.client = None
        if self.openai_key:
            if not OpenAI:
                raise ImportError("openai package is required when OPENAI_API_KEY is set")
            client_kwargs: Dict[str, Any] = {"api_key": self.openai_key}
            if self.openai_project:
                client_kwargs["project"] = self.openai_project
            if self.openai_organization:
                client_kwargs["organization"] = self.openai_organization
            self.client = OpenAI(**client_kwargs)

        self.local_runner = LocalLlamaRunner()
        self._last_call: Dict[str, Optional[str]] = {
            "provider": None,
            "engine": None,
            "reason": None,
        }

        self.privacy_patterns = [
            re.compile(r"\bpassword\b", re.IGNORECASE),
            re.compile(r"\bsecret\b", re.IGNORECASE),
            re.compile(r"\btoken\b", re.IGNORECASE),
            re.compile(r"\bauth\b", re.IGNORECASE),
            re.compile(r"\bssn\b", re.IGNORECASE),
            re.compile(r"social security", re.IGNORECASE),
            re.compile(r"\bcredit card\b", re.IGNORECASE),
            re.compile(r"\baccount\b", re.IGNORECASE),
            re.compile(r"\brouting\b", re.IGNORECASE),
            re.compile(r"\bbank\b", re.IGNORECASE),
            re.compile(r"\bprivate\b", re.IGNORECASE),
            re.compile(r"\bconfidential\b", re.IGNORECASE),
            re.compile(r"\bpersonal\b", re.IGNORECASE),
            re.compile(r"\bphone\b", re.IGNORECASE),
            re.compile(r"\bdob\b", re.IGNORECASE),
            re.compile(r"\bbirth(date)?\b", re.IGNORECASE),
            re.compile(r"(?:\d[ -]?){13,16}"),
            re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
            re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        ]

    # ------------------------------------------------------------------ #
    # Metadata helpers
    # ------------------------------------------------------------------ #
    def _record_call(self, provider: str, *, engine: Optional[str], reason: str) -> None:
        self._last_call = {
            "provider": provider,
            "engine": engine,
            "reason": reason,
        }

    def get_last_call_info(self) -> Dict[str, Optional[str]]:
        return dict(self._last_call)

    # ------------------------------------------------------------------ #
    # Privacy utilities
    # ------------------------------------------------------------------ #
    def _contains_private_info(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in self.privacy_patterns)

    def _detect_privacy_patterns(self, text: str) -> bool:
        return self._contains_private_info(text)

    def _classify_privacy(self, text: str) -> str:
        if not text.strip():
            return "unknown"
        if self._contains_private_info(text):
            return "private"
        return "public"

    def _process_private_data_locally(
        self,
        text: str,
        *,
        max_tokens: int = 256,
        system_prompt: Optional[str] = None,
        reason: str = "private_prompt",
    ) -> str:
        prompt = system_prompt or self.PRIVATE_SYSTEM_PROMPT
        engine = self.local_runner.provider_name or "unavailable"
        self._record_call("local", engine=self.local_runner.model_descriptor, reason=reason)
        response = self.local_runner.generate(
            system_prompt=prompt,
            user_prompt=text,
            max_tokens=max_tokens,
            temperature=0.2,
        )
        if response:
            return response
        self._record_call("local_unavailable", engine=engine, reason=reason)
        return self.local_runner.availability_message()

    def _redact_sensitive_info(self, text: str) -> str:
        lines = text.splitlines()
        redacted: List[str] = []
        for line in lines:
            if self._contains_private_info(line):
                redacted.append("[REDACTED SENSITIVE INFORMATION]")
            else:
                redacted.append(line)
        return "\n".join(redacted)

    # ------------------------------------------------------------------ #
    # Public LLM API
    # ------------------------------------------------------------------ #
    def complete(self, prompt: str, max_tokens: int = 256) -> str:
        if self._classify_privacy(prompt) != "public":
            return self._process_private_data_locally(prompt, max_tokens=max_tokens, reason="private_prompt")

        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                )
                self._record_call(
                    "openai",
                    engine=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
                    reason="public_prompt",
                )
                return response.choices[0].message.content
            except Exception as exc:  # pragma: no cover - network failure
                self._record_call("openai_error", engine=None, reason=str(exc))
                return f"Error processing request: {exc}"

        self._record_call("openai_unconfigured", engine=None, reason="public_prompt")
        return "OpenAI API key not configured"

    def _fallback_interpret_instruction(self, instruction: str) -> Optional[Dict[str, Any]]:
        text = instruction.strip()
        if not text:
            return None

        text_stripped = text.strip()
        if text_stripped.startswith("{") and text_stripped.endswith("}"):
            try:
                parsed = json.loads(text_stripped)
                if isinstance(parsed, dict) and "action" in parsed:
                    return parsed
                if (
                    isinstance(parsed, dict)
                    and "actions" in parsed
                    and isinstance(parsed["actions"], list)
                ):
                    return {
                        "actions": [
                            item
                            for item in parsed["actions"]
                            if isinstance(item, dict) and "action" in item
                        ]
                    }
            except json.JSONDecodeError:
                pass

        lowered = text.lower()
        email_match = re.search(
            r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.IGNORECASE
        )

        if "pizza" in lowered:
            return {"action": "order_pizza", "payload": {}}

        if "pdf" in lowered and ("question" in lowered or "ask" in lowered):
            return {
                "action": "pdf_question",
                "payload": {"question": text, "documents": []},
            }

        if "search" in lowered or "look up" in lowered:
            query = text
            query_match = re.search(
                r"(?:search|look up|find)(?: for)?\s+(.*)", text, re.IGNORECASE
            )
            if query_match:
                query = query_match.group(1).strip()
            return {"action": "search_web", "payload": {"query": query}}

        if "meeting" in lowered or "schedule" in lowered:
            return {"action": "schedule_meeting", "payload": {}}

        if "email" in lowered or "mail" in lowered or email_match:
            subject = ""
            body = ""
            to_value = email_match.group(0) if email_match else ""

            subject_match = re.search(
                r"(?:subject|about)\s*[:\-]\s*(.+)", text, re.IGNORECASE
            )
            if subject_match:
                subject = subject_match.group(1).strip()

            body_match = re.search(
                r"(?:body|message|saying|content)\s*[:\-]\s*(.+)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if body_match:
                body = body_match.group(1).strip()

            if not body:
                body = text

            return {
                "action": "send_email",
                "payload": {"to": to_value, "subject": subject, "body": body},
            }

        return {"action": "answer_question", "payload": {"question": text}}

    def _interpret_with_local(self, instruction: str) -> Optional[Dict[str, Any]]:
        response = self.local_runner.generate(
            system_prompt=self.INTERPRET_PRIVATE_PROMPT,
            user_prompt=instruction,
            max_tokens=500,
            temperature=0.0,
        )
        if not response:
            self._record_call("local_unavailable", engine=self.local_runner.provider_name, reason="interpret_instruction")
            return self._fallback_interpret_instruction(instruction)

        self._record_call("local", engine=self.local_runner.model_descriptor, reason="interpret_instruction")
        raw = response.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if "\n" in raw:
                _, raw = raw.split("\n", 1)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return self._fallback_interpret_instruction(instruction)

        return self._normalize_interpretation(parsed)

    def _normalize_interpretation(self, parsed: Any) -> Optional[Dict[str, Any]]:
        if isinstance(parsed, dict) and "actions" in parsed:
            actions_raw = parsed.get("actions")
            if isinstance(actions_raw, list):
                actions = [
                    item for item in actions_raw if isinstance(item, dict) and "action" in item
                ]
                result: Dict[str, Any] = {"actions": actions}
                if isinstance(parsed.get("clarifications"), list):
                    result["clarifications"] = parsed["clarifications"]
                return result if actions or result.get("clarifications") else None
            return None

        if isinstance(parsed, list):
            actions = [item for item in parsed if isinstance(item, dict) and "action" in item]
            return {"actions": actions} if actions else None

        if isinstance(parsed, dict) and "action" in parsed:
            result_dict: Dict[str, Any] = {"actions": [parsed]}
            if isinstance(parsed.get("clarifications"), list):
                result_dict["clarifications"] = parsed["clarifications"]
            return result_dict

        return None

    def interpret_instruction(self, instruction: str) -> Optional[Dict[str, Any]]:
        if self._contains_private_info(instruction):
            return self._interpret_with_local(instruction)

        if not self.client:
            self._record_call("openai_unconfigured", engine=None, reason="interpret_instruction")
            return self._fallback_interpret_instruction(instruction)

        placeholders: Dict[str, str] = {}

        def _placeholder_entities(regex: re.Pattern, label: str, text: str) -> str:
            matches = list(regex.finditer(text))
            for idx, match in enumerate(matches):
                value = match.group(0)
                placeholder = f"[{label}_{idx}]"
                placeholders[placeholder] = value
                text = text.replace(value, placeholder)
            return text

        sanitized = instruction
        sanitized = _placeholder_entities(
            re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
            "EMAIL",
            sanitized,
        )
        sanitized = _placeholder_entities(
            re.compile(r"\+?\d[\d\-\s]{7,}\d"),
            "PHONE",
            sanitized,
        )
        sanitized = _placeholder_entities(
            re.compile(r"(?:\d[ -]?){13,16}"),
            "CARD",
            sanitized,
        )

        if self._contains_private_info(sanitized):
            return self._interpret_with_local(instruction)

        messages = [
            {
                "role": "system",
                "content": (
                    "You translate instructions into plain JSON. "
                    "Return either a single object with keys \"action\" and \"payload\", "
                    "or an object with \"actions\" that holds a list of such items.\n"
                    "Allowed actions: send_email, schedule_meeting, search_web, order_pizza, "
                    "answer_question, pdf_question.\n"
                    "The payload is a simple dictionary of inputs for that action:\n"
                    "- send_email: to, subject, body (make short professional text when missing)\n"
                    "- schedule_meeting: attendees (list), start_time, end_time or duration_minutes, "
                    "title, description (assume America/Chicago if no timezone is given)\n"
                    "- search_web: query, num_results\n"
                    "- order_pizza: customer (...), address (...), items (list with code and quantity), "
                    "optional special_instructions, optional payment (...)\n"
                    "- answer_question: question, optional context\n"
                    "- pdf_question: question plus documents (list). Each document should have either "
                    "\"path\" that the server can read or \"data\" with base64 text, and an optional \"name\".\n"
                    "Keep the JSON clean, in order, and ask for what is missing by adding another action "
                    "when needed. If you see placeholders like [EMAIL_0], keep them exactly as they are. "
                    "Do not add commentary outside the JSON."
                ),
            },
            {"role": "user", "content": sanitized},
        ]

        try:
            response = self.client.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
                messages=messages,
                max_tokens=400,
                temperature=0,
            )
            self._record_call(
                "openai",
                engine=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
                reason="interpret_instruction",
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                if "\n" in raw:
                    _, raw = raw.split("\n", 1)
            parsed = json.loads(raw)
        except Exception as exc:
            self._record_call("openai_error", engine=None, reason=str(exc))
            return self._interpret_with_local(instruction)

        def _restore_placeholders(value: Any) -> Any:
            if isinstance(value, str):
                return placeholders.get(value, value)
            if isinstance(value, list):
                return [_restore_placeholders(item) for item in value]
            if isinstance(value, dict):
                return {k: _restore_placeholders(v) for k, v in value.items()}
            return value

        parsed = _restore_placeholders(parsed)
        return self._normalize_interpretation(parsed)

    def answer_from_documents(self, question: str, docs: List[str]) -> str:
        docs_private = any(self._contains_private_info(doc) for doc in docs)
        question_is_private = self._contains_private_info(question)

        if docs_private or question_is_private:
            context = "\n---\n".join(docs[:5])
            prompt = (
                "Use the provided context to answer the user's question. "
                "If the context does not contain enough information, explain what is missing "
                "and ask the user to provide it. Only reference the given context."
            )
            return self._process_private_data_locally(
                f"Context:\n{context}\n\nQuestion: {question}",
                max_tokens=512,
                system_prompt=prompt,
                reason="private_documents",
            )

        if self.client:
            try:
                context = "\n---\n".join(docs[:3])
                response = self.client.chat.completions.create(
                    model=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
                    messages=[
                        {
                            "role": "system",
                            "content": "Answer the question based on the provided context.",
                        },
                        {
                            "role": "user",
                            "content": f"Context:\n{context}\n\nQuestion: {question}",
                        },
                    ],
                    max_tokens=512,
                )
                self._record_call(
                    "openai",
                    engine=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
                    reason="public_documents",
                )
                return response.choices[0].message.content
            except Exception as exc:  # pragma: no cover - network failure
                self._record_call("openai_error", engine=None, reason=str(exc))
                return f"Error processing request: {exc}"

        self._record_call("openai_unconfigured", engine=None, reason="public_documents")
        return "OpenAI API key not configured"
