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

### Data flow details

#### `/assistant/command`

1. Incoming prompt is handed to `LocalModel.interpret_instruction`.
2. The text is scanned for sensitive markers (password, token, email, card number, etc.).
3. If the text is private (or becomes private after placeholder substitution), the prompt is sent to the local LLaMA runner. Otherwise, the OpenAI Chat Completions API is used.
4. The interpreter returns structured actions. Example actions include `send_email`, `schedule_meeting`, `search_web`, `order_pizza`, `pdf_question`, and `answer_question`.
5. `mcp_server` executes each action sequentially. Results and intermediate payloads pass through `sanitize_data` so that email addresses, payment details, and document contents are redacted before being returned.
6. If required fields are missing, the server collects clarification prompts instead of executing the action.

#### Direct task endpoints

- `/ask` forwards a question (with optional context) to `LocalModel.complete` or `answer_from_documents`.
- `/email` and `/email/send` accept explicit email payloads and use `Emailer.send`.
- `/meeting` and `/meeting/schedule` schedule Google Calendar events through `Scheduler.schedule_meeting`.
- `/pdf` decodes base64 PDF data and returns sanitized text.
- `/pdf/query` reads PDFs from disk, passes raw text to the LLM, and redacts the answer.
- `/assistant/pdf_question` processes uploaded PDFs, asks the LLM, and redacts the answer.
- `/web/search` and `/search` use `WebSearcher`.
- `/pizza` and `/pizza/order` call `PizzaOrderer.place_order`.
- `/health` is a simple health probe.

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

