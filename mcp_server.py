from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime
import base64
import copy
import re
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    load_dotenv = None  # type: ignore

if load_dotenv:
    load_dotenv()

from connectors.emailer import Emailer
from connectors.pdf_processor import PDFProcessor
from connectors.scheduler import Scheduler
from connectors.web_searcher import WebSearcher
from connectors.pizza_orderer import PizzaOrderer
from local_model import LocalModel

try:
    from dateutil import parser as date_parser  # type: ignore
except ImportError:
    date_parser = None  # type: ignore

app = FastAPI(title="Personal MCP Assistant with Privacy Guardrails")

llm = LocalModel()
emailer = Emailer(None, llm)
pdf_processor = PDFProcessor(None, llm)
scheduler = Scheduler(None, llm)
web_searcher = WebSearcher(None, llm)
pizza_orderer = PizzaOrderer(None, llm)
WORKSPACE_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = WORKSPACE_ROOT / "frontend"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="frontend-static")

    @app.get("/", response_class=HTMLResponse)
    async def serve_frontend():
        index_path = FRONTEND_DIR / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Frontend not found.")
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))

class EmailRequest(BaseModel):
    to: str
    subject: str
    body: str

class LegacyPDFQueryRequest(BaseModel):
    paths: List[str]
    question: str

class PDFProcessRequest(BaseModel):
    pdf_data: str

class MeetingScheduleRequest(BaseModel):
    title: str
    description: Optional[str] = ""
    start_time: str
    duration_minutes: int
    attendees: List[str]

class MeetingRequest(BaseModel):
    attendees: List[str]
    start_time: str
    end_time: str
    subject: Optional[str] = None
    details: Optional[str] = None

class PizzaCustomer(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str


class PizzaAddress(BaseModel):
    street: str
    city: str
    region: str
    postal_code: str


class PizzaItem(BaseModel):
    code: str
    quantity: Optional[int] = 1


class PizzaPayment(BaseModel):
    card_number: Optional[str] = None
    card_expiration: Optional[str] = None
    card_cvv: Optional[str] = None
    billing_postal_code: Optional[str] = None


class PizzaOrderRequest(BaseModel):
    customer: PizzaCustomer
    address: PizzaAddress
    items: List[PizzaItem]
    payment: Optional[PizzaPayment] = None
    special_instructions: Optional[str] = None


class QuestionRequest(BaseModel):
    question: str
    context: Optional[str] = None

class SearchRequest(BaseModel):
    query: str
    num_results: int = 5


class PromptRequest(BaseModel):
    prompt: str


class PDFQuestionDocument(BaseModel):
    name: Optional[str] = None
    data: str


class PDFQuestionRequest(BaseModel):
    question: str
    documents: List[PDFQuestionDocument]


def _normalize_email(value: str) -> str:
    """Normalize email casing while preserving non-domain semantics."""
    email = value.strip()
    if email.lower().endswith("@gmail.com") or email.lower().endswith("@googlemail.com"):
        local, domain = email.split("@", 1)
        return f"{local.lower()}@{domain.lower()}"
    return email


def _mask_email(value: str) -> str:
    """Return a user-friendly alias for an email without exposing the address."""
    normalized = _normalize_email(value)
    local_part = normalized.split("@", 1)[0]
    name_tokens = re.findall(r"[A-Za-z]+", local_part)
    if not name_tokens:
        return "Recipient"
    first_name = name_tokens[0].capitalize()
    return llm._redact_sensitive_info(first_name)


def sanitize_data(value: Any) -> Any:
    """Redact sensitive information before returning responses to the user."""
    if isinstance(value, str):
        if EMAIL_PATTERN.match(value):
            normalized = _normalize_email(value)
            return _mask_email(normalized)
        return llm._redact_sensitive_info(value)
    if isinstance(value, list):
        return [sanitize_data(item) for item in value]
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, val in value.items():
            if key in {"customer", "address", "payment"}:
                sanitized[key] = "[REDACTED]"
            elif key == "documents":
                if isinstance(val, list):
                    sanitized[key] = [
                        sanitize_data(
                            doc.get("name")
                            if isinstance(doc, dict)
                            else doc
                        )
                        for doc in val
                    ]
                else:
                    sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_data(val)
        return sanitized
    return value


@app.get("/health")
async def health_check():
    """Basic health probe used by tests/tools."""
    return {"status": "ok"}


@app.post("/email/send")
@app.post("/email")
async def send_email(req: EmailRequest):
    """Send email with privacy protection."""
    try:
        result = emailer.send(req.to, req.subject, req.body)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pdf/query")
async def query_pdfs(req: LegacyPDFQueryRequest):
    """Query PDF documents with privacy checks."""
    try:
        documents: List[str] = []
        for path in req.paths:
            with open(path, "rb") as f:
                pdf_data = f.read()
            result = pdf_processor.process(base64.b64encode(pdf_data).decode())
            doc_text = result.get("raw_text") or result.get("text") or ""
            if doc_text:
                documents.append(doc_text)

        answer = llm.answer_from_documents(req.question, documents)
        answer = llm._redact_sensitive_info(answer)
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pdf")
async def process_pdf(req: PDFProcessRequest):
    """Process a base64-encoded PDF (compatibility route)."""
    try:
        result = pdf_processor.process(req.pdf_data)
        if result.get("status") == "failed":
            raise HTTPException(status_code=500, detail=result.get("error", "PDF processing failed"))
        result.pop("raw_text", None)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def parse_datetime(value: str, field_name: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        if date_parser:
            try:
                return date_parser.parse(value)
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid {field_name}: {exc}",
                ) from exc
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid {field_name}: {value}. Please provide an ISO 8601 datetime string "
                "such as 2024-10-20T12:45:00-05:00."
            ),
        )


@app.post("/meeting/schedule")
async def schedule_meeting(req: MeetingRequest):
    """Schedule a meeting with privacy protection."""
    try:
        start_dt = parse_datetime(req.start_time, "start_time")
        end_dt = parse_datetime(req.end_time, "end_time")

        if end_dt <= start_dt:
            raise HTTPException(status_code=400, detail="end_time must be after start_time")

        duration_minutes = int((end_dt - start_dt).total_seconds() // 60)
        if duration_minutes <= 0:
            raise HTTPException(status_code=400, detail="Meeting duration must be at least one minute")

        title = req.subject or "Untitled Meeting"
        description = req.details or ""

        result = scheduler.schedule_meeting(
            title,
            description,
            start_dt,
            duration_minutes,
            req.attendees
        )
        if isinstance(result, dict) and result.get("status") == "failed":
            raise HTTPException(status_code=500, detail=result.get("error", "Meeting scheduling failed"))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/meeting")
async def schedule_meeting_simple(req: MeetingScheduleRequest):
    """Schedule a meeting using duration (compatibility route)."""
    try:
        start_dt = parse_datetime(req.start_time, "start_time")

        if req.duration_minutes <= 0:
            raise HTTPException(status_code=400, detail="duration_minutes must be positive")

        result = scheduler.schedule_meeting(
            req.title or "Untitled Meeting",
            req.description or "",
            start_dt,
            req.duration_minutes,
            req.attendees
        )
        if isinstance(result, dict) and result.get("status") == "failed":
            raise HTTPException(status_code=500, detail=result.get("error", "Meeting scheduling failed"))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/web/search")
async def search_web(q: str):
    """Search the web (non-private data only)."""
    try:
        if llm._detect_privacy_patterns(q):
            raise HTTPException(
                status_code=400,
                detail="Query contains private information. Please remove sensitive data."
            )
        results = web_searcher.search(q)
        return results
    except HTTPException:
        raise
    except Exception as e:
        message = str(e) or "Unexpected error while processing web search."
        raise HTTPException(status_code=500, detail=message)

@app.post("/search")
async def search_web_post(req: SearchRequest):
    """POST variant used by tests."""
    try:
        if llm._detect_privacy_patterns(req.query):
            raise HTTPException(
                status_code=400,
                detail="Query contains private information. Please remove sensitive data."
            )
        results = web_searcher.search(req.query, req.num_results)
        if isinstance(results, dict) and results.get("status") == "failed":
            error = results.get("error") or "Search failed"
            raise HTTPException(status_code=500, detail=error)
        return results
    except HTTPException:
        raise
    except Exception as e:
        message = str(e) or "Unexpected error while processing web search."
        raise HTTPException(status_code=500, detail=message)


@app.post("/pizza")
@app.post("/pizza/order")
async def place_pizza(req: PizzaOrderRequest):
    try:
        payload = req.dict(exclude_none=True)
        result = pizza_orderer.place_order(payload)
        if result.get("status") == "failed":
            raise HTTPException(status_code=500, detail=result.get("error", "Pizza ordering failed"))
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/ask")
async def ask_question(req: QuestionRequest):
    """Ask questions with privacy awareness."""
    try:
        if req.context:
            answer = llm.answer_from_documents(req.question, [req.context])
        else:
            answer = llm.complete(req.question)
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/assistant/pdf_question")
async def assistant_pdf_question(req: PDFQuestionRequest):
    """Answer a question using the provided PDF documents."""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if not req.documents:
        raise HTTPException(status_code=400, detail="At least one PDF document is required.")

    texts: List[str] = []
    doc_summaries: List[Dict[str, Any]] = []

    for idx, doc in enumerate(req.documents, start=1):
        processed = pdf_processor.process(doc.data)
        if processed.get("status") != "success":
            error = processed.get("error", "Failed to process PDF document.")
            raise HTTPException(status_code=400, detail=error)
        text_source = processed.get("raw_text") or processed.get("text", "")
        texts.append(text_source)
        doc_summaries.append(
            {
                "name": doc.name or f"Document {idx}",
                "length": processed.get("length", len(text_source)),
            }
        )

    if not texts:
        raise HTTPException(status_code=400, detail="No extractable text found in the provided PDFs.")

    answer = llm.answer_from_documents(question, texts)
    answer = llm._redact_sensitive_info(answer)

    return {
        "question": question,
        "answer": answer,
        "documents": doc_summaries,
        "status": "success",
    }


@app.post("/assistant/command")
async def handle_prompt(req: PromptRequest):
    """Interpret a natural language prompt and execute the corresponding connector action."""
    instruction = req.prompt.strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    structured = llm.interpret_instruction(instruction)
    if not structured:
        raise HTTPException(status_code=400, detail="Unable to interpret the prompt")

    actions_raw = structured.get("actions")
    actions: List[Dict[str, Any]] = []
    if isinstance(actions_raw, list):
        actions = [item for item in actions_raw if isinstance(item, dict) and item.get("action")]
    elif isinstance(actions_raw, dict) and actions_raw.get("action"):
        actions = [actions_raw]
    elif structured.get("action"):
        actions = [structured]

    clarifications: List[Dict[str, Any]] = []
    structured_clarifications = structured.get("clarifications")
    if isinstance(structured_clarifications, list):
        for clarification in structured_clarifications:
            if isinstance(clarification, dict):
                clarifications.append(
                    {
                        "action": clarification.get("action"),
                        "field": clarification.get("field"),
                        "prompt": clarification.get("prompt"),
                        "payload": sanitize_data(
                            copy.deepcopy(clarification.get("payload", {}))
                            if isinstance(clarification.get("payload"), dict)
                            else clarification.get("payload")
                        ),
                    }
                )

    if not actions:
        if clarifications:
            return {"clarifications": clarifications}
        raise HTTPException(status_code=400, detail="Unable to interpret the prompt")

    results_bundle: List[Dict[str, Any]] = []

    try:
        context: Dict[str, Any] = {}
        for item in actions:
            action = item.get("action")
            if not action:
                raise HTTPException(status_code=400, detail="Action missing in instruction")
            payload = item.get("payload") or {}

            if action == "send_email":
                to = payload.get("to")
                if isinstance(to, list):
                    to = to[0] if to else None
                subject = payload.get("subject") or "No subject"
                body = payload.get("body") or ""
                if not to or "@" not in to:
                    clarifications.append(
                        {
                            "action": "send_email",
                            "field": "to",
                            "prompt": "Please provide the recipient's email address.",
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue

                if not body and context.get("last_meeting"):
                    meeting = context["last_meeting"]
                    attendees = ", ".join(meeting.get("attendees", []))
                    body = (
                        f"Hello,\n\n"
                        f"Our meeting \"{meeting.get('title', 'Meeting')}\" is scheduled.\n"
                        f"Start: {meeting.get('start')}\n"
                        f"End: {meeting.get('end')}\n"
                        f"Attendees: {attendees}\n\n"
                        f"Looking forward to it.\n"
                    )
                if not body and context.get("last_pizza_order"):
                    order = context["last_pizza_order"]
                    items = order.get("items", [])
                    total = order.get("total")
                    currency = order.get("currency", "USD")
                    lines = ["Hello,", "", "Thanks for placing your Domino's order. Here's the summary:"]
                    if items:
                        for item in items:
                            lines.append(
                                f"- {item.get('quantity', 1)} x {item.get('code', 'item')}"
                            )
                    if total:
                        lines.append("")
                        lines.append(f"Total: {total} {currency}")
                    lines.append("\nEnjoy your meal!")
                    body = "\n".join(lines)
                if not body:
                    clarifications.append(
                        {
                            "action": "send_email",
                            "field": "body",
                            "prompt": "Please supply the email body so the assistant can send your message.",
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue
                result = emailer.send(to, subject, body)
                if isinstance(result, dict) and result.get("status") != "sent":
                    raise HTTPException(status_code=500, detail=result.get("error", "Email send failed"))

            elif action == "schedule_meeting":
                attendees = payload.get("attendees") or []
                if not isinstance(attendees, list):
                    attendees = [attendees]
                if not attendees:
                    clarifications.append(
                        {
                            "action": "schedule_meeting",
                            "field": "attendees",
                            "prompt": "Whom should I invite to this meeting? Provide one or more attendee emails.",
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue

                start_time = payload.get("start_time")
                end_time = payload.get("end_time")
                duration_minutes = payload.get("duration_minutes")

                if not start_time:
                    clarifications.append(
                        {
                            "action": "schedule_meeting",
                            "field": "start_time",
                            "prompt": "When should the meeting start? (Include date and time).",
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue

                start_dt = parse_datetime(str(start_time), "start_time")

                if end_time:
                    end_dt = parse_datetime(str(end_time), "end_time")
                    duration_minutes = int((end_dt - start_dt).total_seconds() // 60)
                elif duration_minutes:
                    duration_minutes = int(duration_minutes)
                    if duration_minutes <= 0:
                        clarifications.append(
                            {
                                "action": "schedule_meeting",
                                "field": "duration_minutes",
                                "prompt": "Meeting duration must be a positive number of minutes. Please provide it again.",
                                "payload": sanitize_data(copy.deepcopy(payload)),
                            }
                        )
                        continue
                else:
                    duration_minutes = 30

                title = payload.get("title") or "Untitled Meeting"
                description = payload.get("description") or ""

                result = scheduler.schedule_meeting(
                    title,
                    description,
                    start_dt,
                    duration_minutes,
                    attendees,
                )
                if isinstance(result, dict) and result.get("status") == "failed":
                    raise HTTPException(status_code=500, detail=result.get("error", "Meeting scheduling failed"))
                context["last_meeting"] = result

            elif action == "search_web":
                query = payload.get("query")
                if not query:
                    clarifications.append(
                        {
                            "action": "search_web",
                            "field": "query",
                            "prompt": "What would you like me to search for?",
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue
                num_results = int(payload.get("num_results", 5))
                result = web_searcher.search(query, num_results)
                if isinstance(result, dict) and result.get("status") == "failed":
                    raise HTTPException(status_code=500, detail=result.get("error", "Search failed"))

            elif action == "pdf_question":
                question = (payload.get("question") or "").strip()
                documents = payload.get("documents")
                if not question:
                    clarifications.append(
                        {
                            "action": "pdf_question",
                            "field": "question",
                            "prompt": "Please provide the question you would like answered from the PDFs.",
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue
                if not documents:
                    clarifications.append(
                        {
                            "action": "pdf_question",
                            "field": "documents",
                            "prompt": "Please provide one or more PDF documents (paths or base64 data) to analyze.",
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue

                texts: List[str] = []
                doc_summaries: List[Dict[str, Any]] = []
                errors: List[str] = []

                for idx, doc in enumerate(documents, start=1):
                    doc_data: Optional[str] = None
                    doc_name: Optional[str] = None
                    doc_path: Optional[str] = None

                    if isinstance(doc, str):
                        doc_path = doc
                    elif isinstance(doc, dict):
                        doc_data = doc.get("data")
                        doc_path = doc.get("path")
                        doc_name = doc.get("name")
                    else:
                        errors.append(f"Document {idx} is in an unsupported format.")
                        continue

                    if doc_data is None:
                        if not doc_path:
                            errors.append(f"Document {idx} missing path or data.")
                            continue
                        resolved = (WORKSPACE_ROOT / doc_path).resolve()
                        try:
                            resolved.relative_to(WORKSPACE_ROOT)
                        except ValueError:
                            errors.append(f"Document {idx} path is outside the workspace.")
                            continue
                        if not resolved.exists():
                            errors.append(f"Document {idx} not found at path: {doc_path}")
                            continue
                        doc_data = base64.b64encode(resolved.read_bytes()).decode("utf-8")
                        if not doc_name:
                            doc_name = resolved.name

                    processed = pdf_processor.process(doc_data)
                    if processed.get("status") != "success":
                        errors.append(processed.get("error", f"Failed to process document {idx}."))
                        continue
                    text_content = processed.get("raw_text") or processed.get("text", "")
                    if text_content:
                        texts.append(text_content)
                        doc_summaries.append(
                            {
                                "name": doc_name or f"Document {idx}",
                                "length": processed.get("length", len(text_content)),
                            }
                        )

                if errors or not texts:
                    clarifications.append(
                        {
                            "action": "pdf_question",
                            "field": "documents",
                            "prompt": " ".join(errors) if errors else "No readable text found in the provided PDFs.",
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue

                answer = llm.answer_from_documents(question, texts)
                answer = llm._redact_sensitive_info(answer)
                result = {
                    "question": question,
                    "answer": answer,
                    "documents": doc_summaries,
                }

            elif action == "order_pizza":
                validation_error = pizza_orderer._validate(payload)  # type: ignore[attr-defined]
                if validation_error:
                    clarifications.append(
                        {
                            "action": "order_pizza",
                            "field": "order_details",
                            "prompt": validation_error.get("error", "Please fill in the missing pizza order details."),
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue

                result = pizza_orderer.place_order(payload)
                status = result.get("status")
                if status == "failed":
                    raise HTTPException(status_code=500, detail=result.get("error", "Pizza ordering failed"))
                context["last_pizza_order"] = result

            elif action == "answer_question":
                question = payload.get("question")
                context_docs = payload.get("context")
                if not question:
                    clarifications.append(
                        {
                            "action": "answer_question",
                            "field": "question",
                            "prompt": "Please provide the question you want answered.",
                            "payload": sanitize_data(copy.deepcopy(payload)),
                        }
                    )
                    continue
                if context_docs:
                    docs_list = [context_docs] if isinstance(context_docs, str) else context_docs
                    result_content = llm.answer_from_documents(question, docs_list)
                else:
                    result_content = llm.complete(question)
                result = {"answer": result_content}

            else:
                raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")

            safe_payload = sanitize_data(copy.deepcopy(payload))
            safe_result = sanitize_data(copy.deepcopy(result))

            results_bundle.append(
                {
                    "action": action,
                    "payload": safe_payload,
                    "result": safe_result,
                }
            )

        if clarifications:
            response_payload: Dict[str, Any] = {}
            if results_bundle:
                response_payload["actions"] = results_bundle
            response_payload["clarifications"] = clarifications
            return response_payload

        if len(results_bundle) == 1:
            return results_bundle[0]

        return {"actions": results_bundle}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/status/local_model")
async def local_model_status():
    """Report whether the local LLaMA runner is available."""
    available = llm.local_runner.is_available()
    response: Dict[str, Any] = {
        "available": available,
        "provider": llm.local_runner.provider_name,
        "model": llm.local_runner.model_descriptor,
        "last_call": llm.get_last_call_info(),
    }
    if not available:
        response["message"] = llm.local_runner.availability_message()
    return response


@app.post("/admin/local_model/initialize")
async def initialize_local_model():
    """Explicitly trigger initialization of the local LLaMA runner."""
    available = llm.local_runner.is_available()
    response: Dict[str, Any] = {
        "initialized": available,
        "provider": llm.local_runner.provider_name,
        "model": llm.local_runner.model_descriptor,
        "message": "Local model initialized successfully." if available else llm.local_runner.availability_message(),
    }
    return response
