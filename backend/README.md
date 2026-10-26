# Acme Invoice Agents: backend

Python package `acme` (in `src/acme/`). Commands below run from the repo root.

## Setup

```bash
uv venv backend/.venv                      # or: python -m venv backend/.venv
uv pip install --python backend/.venv/bin/python -e "backend[dev]"
source backend/.venv/bin/activate
cp .env.example .env                       # then edit; every setting is listed with its default
python -m acme.db seed                     # creates acme.db with inventory, aliases, vendors
```

Run the tests (no API key or network needed; a test-only fake model stands in for the LLM):

```bash
pytest backend/tests
```

## LLM providers

Agents get their model from `acme.llm.get_chat_model(role)`; switching providers is a
config change only.

| Setting | Default | Notes |
| --- | --- | --- |
| `LLM_PROVIDER` | `grok` | `grok` or `claude`; any other value stops startup. `python main.py --provider ...` overrides it for one run |
| `GROK_MODEL` | `grok-4` | Needs `XAI_API_KEY`. Confirm the current name in the xAI console |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | Needs `ANTHROPIC_API_KEY`. `claude-opus-5-5` for the hardest reasoning |
| `LLM_PROVIDER_EXTRACTION`, `_VALIDATION`, `_APPROVAL`, `_CRITIC` | unset | Per-role override, e.g. `LLM_PROVIDER_CRITIC=claude` for cross-model critique |
| `LLM_TEMPERATURE` | `0` | |
| `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES` | `30` / `3` | Exponential backoff on 429 and 5xx |

**Key status.** `acme.llm.key_status()` reports whether every provider in use (per-role overrides
included) has its key, and names the first missing variable. `python -m acme.llm` prints it.
Without a key, `--invoice_path` and `--batch` exit 2 before creating a run with "No LLM token
provided: set XAI_API_KEY for Grok (in .env or the environment). The app cannot process invoices
without it." (`--json` prints `{"error", "missing_key"}`); `--explain`, `review`, and `payments run`
make no LLM call and still work. The API starts anyway (see "Web API").

**Tests.** No test calls a provider. `backend/tests/conftest.py` sets a dummy `XAI_API_KEY` and
replaces `acme.llm.factory._build_model` with `tests/fake_llm.py`'s `FakeChatModel` (scripted
extraction, approval, critic, tool plan, and address verdicts). `tests/fake_server.py` (the e2e
backend) and `tests/fake_cli.py` (subprocess tests) install the same fake. No setting or CLI flag
can select it.

Every call is recorded in the `llm_calls` table (provider, model, prompt version, tokens,
latency, retries, failure), including the Validation stage's address plausibility call
(prompt `address_v1`).

## Web API

A FastAPI service (`acme.api`) runs the same pipeline as the CLI for the Angular web app. One
process holds the API, the upload worker, and the payment scheduler.

```bash
uvicorn acme.api.app:create_app --factory --port 8000   # from the repo root, venv active
```

OpenAPI docs: <http://localhost:8000/docs>. At startup the service creates and seeds an empty
`acme.db`, settles a payment batch left `paying`, re-submits claimed reviews (`Resuming`), and
re-processes runs left mid-pipeline. Held invoices stay decidable across restarts.

The service also starts without an LLM key, so the web app can explain the problem: `/api/stats`
reports `llm.configured: false` and `llm.missing_key`, uploads are refused with 503, and runs
waiting to be processed stay Uploaded until a restart with a key. Reviews and payments keep
working. An invalid `LLM_PROVIDER` still stops startup.

| Setting | Default | Notes |
| --- | --- | --- |
| `API_CORS_ORIGIN` | `http://localhost:4200` | The only origin allowed by CORS (the Angular dev server) |
| `UPLOAD_DIR` | `uploads` | Files are stored as `UPLOAD_DIR/<run_id>/<file_name>` |
| `UPLOAD_MAX_BYTES` | `10485760` | Per file (10 MB); empty files are refused too |
| `ALLOWED_UPLOAD_EXTENSIONS` | `.pdf,.txt,.csv,.json,.xml,.eml` | |
| `WORKER_CONCURRENCY` | `1` | Invoices process one at a time, in upload order |
| `PAYMENT_BATCH_TIME` / `PAYMENT_TZ` | `17:00` / `America/Chicago` | Daily `end_of_day` batch |
| `PAYMENT_IDLE_DELAY_S` / `PAYMENT_AUTO_IDLE` | `60` / `true` | `idle` batch once nothing has been processing for the delay (checked every 5 s) |

Money is a 2-decimal string (`"7750.00"`); timestamps are ISO 8601 UTC. Errors use FastAPI's
`{"detail": ...}`; a 409 carries `{"detail": {"message", "status"}}`, and a 503 with no LLM key carries
`{"detail": {"code": "llm_not_configured", "message", "missing_key"}}`. Every list response has
`server_time`, and every view returns the full current state, so polling every 3 s works.

| Method and path | Purpose |
| --- | --- |
| `POST /api/invoices` | Multipart, field `files` (repeat per file; `file` also accepted). 202 → `{files: [{id, file_name, status: "Uploaded" \| "rejected", size, error}], accepted, rejected, server_time}`. 422 with no files; 503 `llm_not_configured` (nothing stored, no run created) while no LLM key is set |
| `GET /api/invoices?view=queue` | `{view, rows, count, server_time}`. Unresolved runs; row: `id, file_name, format, invoice_number, vendor, amount_usd, stage, status` (Processing, Retrying extraction, Awaiting review), `run_status, uploaded_at, stage_entered_at, time_in_stage_s, final_status, decided_by, completed_at, processing_s` |
| `GET /api/invoices?view=audit` | Resolved runs, newest first. Filters `status` (comma list), `date_from`, `date_to` (YYYY-MM-DD, completed date in PAYMENT_TZ), `search` (file, number, vendor). Adds `key_findings` (≤ 3 `{code, severity, message}`), `findings_count` |
| `GET /api/invoices?view=review` | Held runs. Adds `hold_kind` (warning, credit, payment_failure), `reason` ("Payment failed" for payment failures), `detail, last_error, attempts, findings, ai_recommendation, ai_rationale, overpaid_usd, paid_amount_usd, waiting_since, waiting_s` |
| `GET /api/invoices/{id}` | Row fields plus `invoice, extracted, findings, decision, drafts, critiques` (each with `provider`, `model`), `reviews, hold, payment_queue, payments, rejection, timeline` (audit ledger). 404 if unknown |
| `GET /api/invoices/{id}/file` | Original bytes, content type from the extension (`application/pdf`, `text/plain`, ...). 404 if unknown |
| `POST /api/invoices/{id}/review` | `{decision: "approve" \| "reject", reviewer (1-50 trimmed), rationale (≥ 15)}`. 200 → `{id, decision, reviewer, status: "Resuming"}`; the run resumes on the worker. 422 bad input, 409 not awaiting review, 404 unknown. Credit holds: approve = Credit confirmed, reject = Reject revision |
| `GET /api/payment-queue` | `{rows, count, total_usd, next_batch_at, next_batch_label ("Today 5:00 PM CT"), timezone, auto_idle, idle_delay_s, batch_running, server_time}`; row: `id, run_id, file_name, invoice_number, revision, vendor, amount_usd, kind (full, replacement, delta), approved_by, queued_at, status (queued, paying, failed), attempts, last_error, batch_id` |
| `POST /api/payment-queue/execute` | `{ids?: [row id], released_by (1-50 trimmed)}`: no ids = Pay all, one = Pay now, several = Pay selected (an empty list is 422). 202 → `{batch_id, trigger, released_by}`; 409 while a batch runs |
| `GET /api/payments` | Filters `date_from`, `date_to`, `vendor` (substring). `{rows, count, total_usd, server_time}`; row: `payment_id, run_id, file_name, invoice_number, revision, vendor, amount_usd, original_amount, original_currency, kind, delta_label ("Delta for R1"), invoice_total_usd, approved_by, paid_at, idempotency_key, batch_id, batch_trigger, batch_trigger_label, released_by` |
| `GET /api/payment-batches` | `{rows, count, server_time}`, newest first; row: `batch_id, trigger, trigger_label, released_by, started_at, finished_at, running, count, total_usd, failed_count` |
| `GET /api/stats` | `in_queue, processing, awaiting_review, payment_queue, paid_today, rejected_today, dollars_queued, dollars_paid, dollars_blocked, duplicates_caught, llm: {provider, model, roles, configured, missing_key}, server_time`. `configured` is false while a needed key is missing; `missing_key` names it (`XAI_API_KEY`, `ANTHROPIC_API_KEY`) or is null |
| `GET /api/events` | SSE: `ready`, `invoice.created`, `invoice.stage_changed`, `invoice.resolved` (data: `run_id, stage, status, final_status, invoice` = the list row), `payment.queued`, `payment.cancelled`, `batch.started`, `payment.created`, `batch.finished` (`count, total_usd, failed_count, results`). Ping every 15 s; no replay |
| `GET /api/invoices.csv`, `GET /api/payments.csv` | CSV of the audit view and payments, same filters as the JSON endpoints |

API tests live in `backend/tests/api/` (`pytest backend/tests/api`).
