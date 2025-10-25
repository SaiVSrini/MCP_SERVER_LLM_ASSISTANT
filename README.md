## Personal MCP Assistant

This project is one FastAPI server with many helper tools (email, calendar, PDF reading, web search, pizza ordering, and free-form Q&A). Every request first goes through a privacy filter that decides if it should stay on your machine or can go out to OpenAI (OpenAI is used only when an API key is set and the text looks safe).

### High-level flow

1. Environment settings are read from `.env` (loaded by `python-dotenv` or by your shell).
2. `mcp_server.py` starts FastAPI, builds one shared `LocalModel`, and gives it to every connector.
3. Each HTTP endpoint either calls the right connector or asks `LocalModel` to help.
4. `LocalModel` checks the text with simple patterns. Private text stays local and goes to LLaMA. Public text can go to OpenAI if an API key is present.
5. Before sending anything back, the result is cleaned so sensitive data is hidden.

### Components

- `local_model.py` — handles every LLM call. It can talk to Ollama, llama.cpp, transformers, or OpenAI. It also spots private data, hides it, and turns natural text into actions.
- `mcp_server.py` — FastAPI app that declares each endpoint and plugs in the connectors.
- `connectors/` — the actual skills:
  - `emailer.py` sends Gmail messages.
  - `scheduler.py` creates Google Calendar events.
  - `pdf_processor.py` reads PDFs with PyPDF2 and hides private text.
  - `web_searcher.py` tries Google Custom Search, Serper.dev, a Google scrape, then DuckDuckGo.
  - `pizza_orderer.py` talks to Domino’s through `pizzapi`.
- `frontend/` — simple web UI served by FastAPI for quick tests.
- `scripts/assistant_cli.py` — command-line helper that posts to `/assistant/command`.
- `test_endpoints.py` and `test_dependencies.py` — basic scripts that exercise the API and check imports.

### Detailed data flow

#### Overall life cycle (applies to the CLI, frontend, or any HTTP client)

1. The user types a request (for example, “Book a meeting with Alex tomorrow at 4 pm”).
2. The client sends the request to the FastAPI server. The CLI and frontend use `/assistant/command`; curl can call any endpoint.
3. `mcp_server.py` receives the JSON. One shared `LocalModel` and all connectors are already loaded.
4. The server picks the right handler. `/assistant/command` uses the longer flow below. Simple routes like `/email` or `/search` call their connector after a quick privacy check.
5. Each handler returns a Python dictionary. `sanitize_data` hides or removes any private details before the response leaves the server.
6. FastAPI sends the cleaned JSON back to the caller.

#### `/assistant/command` step-by-step

1. The prompt is sent to `LocalModel.interpret_instruction`.
2. Regular expressions look for private markers such as passwords, tokens, emails, cards, and birth dates.
3. If private markers appear, the prompt goes straight to the local LLaMA runner. If not, obvious identifiers are replaced with placeholders (for example `[EMAIL_0]`) and checked again.
4. Safe prompts go to OpenAI (when `OPENAI_API_KEY` is set). Private prompts stay on the local model. Both models must return valid JSON describing the requested work.
5. The JSON is flattened into a list of `{action, payload}` entries plus any clarification questions.
6. Each action is executed in turn:
   - `Emailer.send` for `send_email`
   - `Scheduler.schedule_meeting` for `schedule_meeting`
   - `WebSearcher.search` for `search_web`
   - `PDFProcessor.process` combined with `LocalModel.answer_from_documents` for `pdf_question`
   - `PizzaOrderer.place_order` for `order_pizza`
   - `LocalModel.complete` or `answer_from_documents` for `answer_question`
7. Connectors can call `LocalModel` again if they need another answer while keeping data local (for example, PDF Q&A).
8. Missing details (no recipient, no start time, etc.) produce clarification questions instead of errors.
9. Results and clarifications run through `sanitize_data`, which hides emails, payment info, PDF text, and similar fields.
10. The final cleaned JSON is returned to the caller.

#### Direct task endpoints

- `/ask` uses `LocalModel.complete` for plain questions and switches to `answer_from_documents` when context is supplied.
- `/email` and `/email/send` call `Emailer.send` after redacting the message body.
- `/meeting` and `/meeting/schedule` convert times into `datetime` objects, validate the range, and forward the request to `Scheduler.schedule_meeting`.
- `/pdf` accepts a base64 string, decodes it, extracts text with `PDFProcessor`, redacts the text, and returns the safe version.
- `/pdf/query` reads files from disk, extracts text, asks `LocalModel.answer_from_documents`, and redacts the response.
- `/assistant/pdf_question` uploads PDF files, extracts text, and runs the same QA helper.
- `/web/search` and `/search` run a privacy check on the query, then call `WebSearcher` which tries Google Custom Search, Serper.dev, scrape, and DuckDuckGo in order.
- `/pizza` and `/pizza/order` validate the Domino’s order payload locally, scrub special instructions, and place the order when live mode is enabled.
- `/health` returns `{"status": "ok"}` without touching the LLM.

### Local vs OpenAI compute

`LocalModel` looks for the following environment variables to initialize a local model:

- `LLAMA2_PROVIDER` — `ollama`, `llama_cpp`, or `transformers`.
- `LLAMA2_MODEL` — model name for Ollama.
- `LLAMA2_MODEL_PATH`, `LLAMA_CPP_MODEL_PATH`, or `TRANSFORMERS_MODEL_PATH` — path to local model weights.
- `LLAMA_CPP_CTX` — optional context window size for `llama.cpp`.

If a prompt or document looks private (password, token, SSN, card number, etc.), `LocalModel` always uses the local backend and never sends it to OpenAI. Public text can go to OpenAI when `OPENAI_API_KEY` is set. Optional OpenAI settings:

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

When the server starts it reads `.env`, builds every connector, and exposes the API at `http://localhost:8000`. The static frontend is served at `/` if the `frontend/` folder exists.

**Using Ollama locally**

1. Install Ollama and download the model you want (for example `ollama run llama2`).
2. (Optional but helpful) install the Python client in your virtualenv: `pip install ollama`.
3. Put `LLAMA2_PROVIDER=ollama`, `LLAMA2_MODEL=llama2`, and `OLLAMA_HOST` into your `.env`.
4. Start the Ollama daemon (`ollama serve`) before you run FastAPI. If FastAPI runs in Docker or WSL, bind Ollama to an address the container can reach and point `OLLAMA_HOST` to that address.
5. If the daemon is down you will see “Unable to initialize a local LLaMA2 runtime…” in API replies and in the frontend banner.
6. Call `POST /admin/local_model/initialize` to warm up the model and confirm it is ready.

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
- If the frontend shows “Local model status: offline — Ollama Python client not found…” install the `ollama` Python package (or make sure `OLLAMA_HOST` is reachable) and restart the server.
