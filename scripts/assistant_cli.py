#!/usr/bin/env python3
"""
CLI helper for the MCP assistant endpoint.

Send a natural language prompt to the running MCP server's /assistant/command
route and print the structured response in the console.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List
from pathlib import Path
import base64

import requests


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send a prompt to the MCP server's assistant endpoint.",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Prompt to send. If omitted, you will be prompted to enter one interactively.",
    )
    parser.add_argument(
        "--search",
        nargs="+",
        help="Run a web search for the given query instead of sending a general prompt.",
    )
    parser.add_argument(
        "--num-results",
        type=int,
        default=int(os.environ.get("MCP_SEARCH_RESULTS", 5)),
        help="Number of search results to request (default: %(default)s or MCP_SEARCH_RESULTS env var).",
    )
    parser.add_argument(
        "--pdf-question",
        help="Ask a question across one or more PDF documents.",
    )
    parser.add_argument(
        "--pdf",
        dest="pdf_paths",
        action="append",
        default=[],
        help="Path to a PDF file (repeat this flag for multiple documents).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MCP_SERVER_URL", "http://localhost:8000"),
        help="MCP server base URL (default: %(default)s or MCP_SERVER_URL env var).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the full JSON response in addition to the summary.",
    )
    return parser


def ensure_prompt(parts: List[str]) -> str:
    if parts:
        return " ".join(parts).strip()
    try:
        return input("Enter your prompt: ").strip()
    except EOFError:
        return ""


def post_prompt(base_url: str, prompt: str) -> Dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/assistant/command"
    response = requests.post(endpoint, json={"prompt": prompt}, timeout=30)
    response.raise_for_status()
    return response.json()


def post_search(base_url: str, query: str, num_results: int) -> Dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/search"
    payload = {"query": query, "num_results": num_results}
    response = requests.post(endpoint, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def post_pdf_question(base_url: str, question: str, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/assistant/pdf_question"
    payload = {
        "question": question,
        "documents": documents,
    }
    response = requests.post(endpoint, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.pdf_question:
        if not args.pdf_paths:
            parser.error("--pdf-question requires at least one --pdf path.")
        question = args.pdf_question.strip()
        if not question:
            parser.error("PDF question cannot be empty.")
        try:
            documents = []
            for pdf_path in args.pdf_paths:
                path_obj = Path(pdf_path).expanduser()
                if not path_obj.exists():
                    parser.error(f"PDF not found: {pdf_path}")
                pdf_bytes = path_obj.read_bytes()
                documents.append(
                    {
                        "name": path_obj.name,
                        "data": base64.b64encode(pdf_bytes).decode("utf-8"),
                    }
                )
            payload = post_pdf_question(args.base_url, question, documents)
        except requests.exceptions.HTTPError as exc:
            text = exc.response.text if exc.response is not None else str(exc)
            sys.stderr.write(f"Server returned an error ({exc.response.status_code if exc.response else 'unknown'}):\n{text}\n")
            raise SystemExit(1)
        except requests.exceptions.RequestException as exc:
            sys.stderr.write(f"Failed to contact MCP server at {args.base_url}: {exc}\n")
            raise SystemExit(1)
        print("=== PDF Question Answer ===")
        print(f"Question : {payload.get('question', question)}")
        print(f"Answer   : {payload.get('answer')}")
        docs = payload.get("documents") or []
        if docs:
            print("\nDocuments analyzed:")
            for doc in docs:
                print(f"  - {doc.get('name')} (length: {doc.get('length')})")
        if args.pretty:
            print("\nFull response:")
            print(json.dumps(payload, indent=2, default=str))
        return

    if args.search:
        query = " ".join(args.search).strip()
        if not query:
            parser.error("Empty search query.")
        try:
            payload = post_search(args.base_url, query, args.num_results)
        except requests.exceptions.HTTPError as exc:
            text = exc.response.text if exc.response is not None else str(exc)
            sys.stderr.write(f"Server returned an error ({exc.response.status_code if exc.response else 'unknown'}):\n{text}\n")
            raise SystemExit(1)
        except requests.exceptions.RequestException as exc:
            sys.stderr.write(f"Failed to contact MCP server at {args.base_url}: {exc}\n")
            raise SystemExit(1)

        print("=== MCP Web Search Results ===")
        if payload.get("status") != "success":
            print(f"Status : {payload.get('status', 'failed')}")
            if payload.get("error"):
                print(f"Error  : {payload['error']}")
            raise SystemExit(1)

        results = payload.get("results") or []
        print(f"Query  : {payload.get('query', query)}")
        print(f"Count  : {len(results)}")
        for idx, item in enumerate(results, start=1):
            title = item.get("title") or "(no title)"
            snippet = item.get("snippet") or ""
            link = item.get("link") or ""
            print(f"\n[{idx}] {title}")
            if snippet:
                print(f"    {snippet}")
            if link:
                print(f"    {link}")
    else:
        prompt = ensure_prompt(args.prompt)
        if not prompt:
            parser.error("No prompt provided.")

        payload = send_prompt(args, prompt)
        print("=== MCP Assistant Response ===")
        render_response(payload, args.pretty)

    if args.pretty and args.search:
        print("\nFull response:")
        print(json.dumps(payload, indent=2, default=str))


def send_prompt(args: argparse.Namespace, prompt: str) -> Dict[str, Any]:
    try:
        return post_prompt(args.base_url, prompt)
    except requests.exceptions.HTTPError as exc:
        text = exc.response.text if exc.response is not None else str(exc)
        sys.stderr.write(f"Server returned an error ({exc.response.status_code if exc.response else 'unknown'}):\n{text}\n")
        raise SystemExit(1)
    except requests.exceptions.RequestException as exc:
        sys.stderr.write(f"Failed to contact MCP server at {args.base_url}: {exc}\n")
        raise SystemExit(1)


def render_response(payload: Dict[str, Any], pretty: bool) -> None:
    clarifications = payload.get("clarifications")
    if clarifications:
        print("Clarifications needed:")
        for idx, item in enumerate(clarifications, start=1):
            prompt_text = item.get("prompt") or "Additional information required."
            action_name = item.get("action", "<unknown>")
            field = item.get("field") or ""
            print(f"\nClarification {idx} (action: {action_name}, field: {field}):")
            print(f"  {prompt_text}")

    actions_payload = payload.get("actions")
    if isinstance(actions_payload, list) and actions_payload:
        for idx, entry in enumerate(actions_payload, start=1):
            action_name = entry.get("action", "<unknown>")
            result = entry.get("result")
            print(f"\nAction {idx}: {action_name}")
            _print_action_result(result)
    elif actions_payload is None:
        pass
    else:
        action = payload.get("action", "<unknown>")
        result = payload.get("result")
        print(f"Action : {action}")
        _print_action_result(result)

    if pretty:
        print("\nFull response:")
        print(json.dumps(payload, indent=2, default=str))


def _print_action_result(result: Any) -> None:
    if isinstance(result, dict):
        status = result.get("status")
        if status:
            print(f"  Status : {status}")
        if result.get("error"):
            print(f"  Error  : {result['error']}")
        else:
            for key, value in result.items():
                if key in {"status", "error"}:
                    continue
                print(f"  {key.title():<7}: {value}")
    else:
        print(f"  Result : {result}")


if __name__ == "__main__":
    main()
