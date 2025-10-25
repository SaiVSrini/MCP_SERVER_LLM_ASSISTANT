## Personal MCP Assistant

This repository hosts a single FastAPI service that exposes a collection of personal assistant skills (email, calendar, document reading, web search, pizza ordering, and free-form question answering). The server routes every request through a privacy-aware language model router that decides when to keep data on the machine and when it is safe to involve OpenAI APIs.

### High-level flow

1. Environment variables are loaded from `.env` (either through `python-dotenv` or your shell).
2. `mcp_server.py` starts FastAPI, builds one `LocalModel` instance, and passes it to every connector.
3. Each HTTP endpoint calls into a connector or into the `LocalModel`.
4. `LocalModel` uses regex checks to decide if the text is private. Private text stays local and goes to a LLaMA runner. Public text can be sent to OpenAI if an API key is configured.
5. Results are sanitized before they are returned to the caller.

### Components

- `local_model.py` — wraps all LLM calls. It drives the local LLaMA runtime (`ollama`, `llama.cpp`, or `transformers`) and the OpenAI Chat Completions API. It also does privacy detection, redaction, and command interpretation.
- `mcp_server.py` — FastAPI application defining REST endpoints and wiring connectors together.
- `connectors/` — concrete skills:
  - `emailer.py` sends Gmail messages.
  - `scheduler.py` schedules Google Calendar events.
  - `pdf_processor.py` loads PDFs with PyPDF2, redacts sensitive text, and exposes it to the LLM.
  - `web_searcher.py` queries Google Custom Search, Serper.dev, a basic Google scrape, or DuckDuckGo, in that priority order.
  - `pizza_orderer.py` places Domino’s orders through `pizzapi`.
- `frontend/` — static page served by FastAPI for manual testing.
- `scripts/assistant_cli.py` — CLI helper that sends prompts to `/assistant/command`.
- `test_endpoints.py` and `test_dependencies.py` — smoke tests for the API and required packages.

### Detailed data flow

#### Overall life cycle (applies to the CLI, frontend, or any HTTP client)

1. A user types a request (for example, “Book a meeting with Alex tomorrow at 4 pm”).
2. The client sends that text to the FastAPI server. The CLI posts to `/assistant/command`; the frontend does the same through JavaScript; direct API calls can hit any endpoint.
3. FastAPI receives the JSON payload inside `mcp_server.py`. The app already has single instances of `LocalModel` and every connector ready to use.
4. Before any LLM call happens, the server looks at the request and decides which handler to call. For `/assistant/command`, it goes through the orchestrated workflow described below. For direct routes such as `/email` or `/search`, it jumps straight to the connector after a quick privacy check.
5. Each handler returns a Python dictionary. Before sending that dictionary back to the user, `sanitize_data` removes or masks any private fields so secrets do not leak to the response.
6. FastAPI serializes the sanitized dictionary into JSON and sends it back to the client.

#### `/assistant/command` step-by-step

1. The raw prompt goes to `LocalModel.interpret_instruction`.
2. The text is checked with several regular expressions to find passwords, tokens, emails, card numbers, dates of birth, and similar private strings.
3. If sensitive content is detected, the prompt is sent to the local LLaMA runner immediately. If not, the model first replaces obvious identifiers with placeholders (for example, turns an email into `[EMAIL_0]`) and checks again.
4. When the sanitized prompt is safe, the OpenAI Chat Completions API is used (through the `openai` client). When it is not safe, the local model is used instead. Either model must return valid JSON that lists the requested actions.
5. The JSON is normalized into a list of `{action, payload}` entries and optional clarification questions.
6. The server iterates over the actions. Depending on the action name it calls:
   - `Emailer.send` for `send_email`
   - `Scheduler.schedule_meeting` for `schedule_meeting`
   - `WebSearcher.search` for `search_web`
   - `PDFProcessor.process` combined with `LocalModel.answer_from_documents` for `pdf_question`
   - `PizzaOrderer.place_order` for `order_pizza`
   - `LocalModel.complete` or `answer_from_documents` for `answer_question`
7. Every connector can call back into `LocalModel` when it needs a follow-up answer under privacy rules (for example, document QA).
8. If a connector reports missing data (no recipient email, no meeting time, etc.), the server does not fail the whole request. Instead it collects the clarification prompt and adds it to the response so the user knows what to provide next.
9. The combined results and clarifications pass through `sanitize_data`, which redacts email addresses, payment blocks, PDF contents, and other sensitive fields.
10. The final JSON is returned to the client.

#### Direct task endpoints

- `/ask` uses `LocalModel.complete` for plain questions and switches to `answer_from_documents` when context is supplied.
- `/email` and `/email/send` call `Emailer.send` after redacting the message body.
- `/meeting` and `/meeting/schedule` convert times into `datetime` objects, validate the range, and forward the request to `Scheduler.schedule_meeting`.
- `/pdf` accepts a base64 string, decodes it, extracts text with `PDFProcessor`, redacts the text, and returns the safe version.
- `/pdf/query` reads files from disk, extracts text, asks `LocalModel.answer_from_documents`, and redacts the response.
- `/assistant/pdf_question` uploads document bytes directly, processes them, and then calls the same QA helper as above.
- `/web/search` and `/search` run a privacy check on the query, then call `WebSearcher` which tries Google Custom Search, Serper.dev, scrape, and DuckDuckGo in order.
- `/pizza` and `/pizza/order` validate the Domino’s order payload locally, scrub special instructions, and place the order when live mode is enabled.
- `/health` returns `{"status": "ok"}` without touching the LLM.

### Local vs OpenAI compute

`LocalModel` looks for the following environment variables to initialize a local model:

- `LLAMA2_PROVIDER` — `ollama`, `llama_cpp`, or `transformers`.
- `LLAMA2_MODEL` — model name for Ollama.
- `LLAMA2_MODEL_PATH`, `LLAMA_CPP_MODEL_PATH`, or `TRANSFORMERS_MODEL_PATH` — path to local model weights.
- `LLAMA_CPP_CTX` — optional context window size for `llama.cpp`.

If the prompt or documents are marked private (regex matches password, token, SSN, credit card, etc.), `LocalModel` always uses the local backend. For public text, it calls OpenAI when `OPENAI_API_KEY` is set. Optional OpenAI settings:

- `OPENAI_API_KEY`
- `OPENAI_PROJECT`
- `OPENAI_ORG` or `OPENAI_ORGANIZATION`
- `OPENAI_MODEL` (defaults to `gpt-3.5-turbo`)

### Connector credentials

Store secrets in `.env` (never commit production values):

- Gmail and Google Calendar: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, optionally `GOOGLE_CALENDAR_SCOPES`.
- Google Custom Search: `SEARCH_API_KEY`, `SEARCH_CX`.
- Serper.dev: `SERPER_API_KEY`.
- Pizza ordering: `PIZZA_LIVE_MODE`, `PIZZA_CARD_NUMBER`, `PIZZA_CARD_EXPIRATION`, `PIZZA_CARD_CVV`, `PIZZA_BILLING_POSTAL_CODE`.

`get_google_refresh_token.py` starts a local OAuth flow to refresh Google tokens. All scripts expect `python-dotenv` so that the `.env` file is read automatically.

### Running the server

```bash
pip install -r requirements.txt
uvicorn mcp_server:app --reload
```

When the server starts it will load `.env`, instantiate the connectors, and expose the REST API on `http://localhost:8000`. The static front-end is available at `/` when the `frontend/` directory is present.

**Using Ollama locally**

1. Install the Ollama daemon and download the desired model (for example `ollama run llama2`).
2. Install the Python client inside your virtualenv: `pip install ollama`.
3. Set `LLAMA2_PROVIDER=ollama` (already defaulted in `.env.example`) and optionally `LLAMA2_MODEL=llama2`.
4. Start the Ollama daemon (`ollama serve`) before launching FastAPI.
5. When the daemon is offline you will see “Unable to initialize a local LLaMA2 runtime…” in responses and in the frontend banner.
6. You can force the backend to preload the runner by calling `POST /admin/local_model/initialize`; the response confirms whether the local model is ready.

### Using the CLI

```
python scripts/assistant_cli.py "schedule a meeting with alice@example.com tomorrow at 3pm"
```

Flags:

- `--search` to call the `/search` endpoint.
- `--pdf-question` with one or more `--pdf` files to hit `/assistant/pdf_question`.
- `--pretty` to pretty-print JSON responses.

### Testing and diagnostics

- `python test_dependencies.py` imports every required package and prints the detected version.
- `python test_endpoints.py` assumes the FastAPI server is running locally and exercises the major endpoints. The pizza test is skipped unless `PIZZA_LIVE_MODE` is true.
- `python -m compileall .` is a quick way to confirm that all modules compile.

### Implementation notes

- PDF extraction now guards against pages that return `None` from `extract_text()`.
- Sensitive strings are consistently redacted before returning from endpoints and connectors.
- The repository avoids inline comments in favor of clear function and variable names, so the code remains readable without extra commentary.
- If the frontend shows “Local model status: offline — Ollama Python client not found…” install the `ollama` Python package and restart the server.
