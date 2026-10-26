# Acme Invoice Agents: backend

Python package `acme` (in `src/acme/`). Commands below run from the repo root.

## Setup

```bash
uv venv backend/.venv                      # or: python -m venv backend/.venv
uv pip install --python backend/.venv/bin/python -e "backend[dev]"
source backend/.venv/bin/activate
cp .env.example .env                       # then edit; every setting is listed with its default
python -m acme.db seed                     # creates acme.db with inventory, aliases, vendors, payees
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

## Fraud checks: payee threshold and prompt injection

| Setting | Default | Notes |
| --- | --- | --- |
| `PAYEE_WINDOW_DAYS` | `30` | Rolling window for the cumulative payee total |
| `PAYEE_CUMULATIVE_THRESHOLD_USD` | `10000.00` | A payee total over this (at least two invoices) raises `PAYEE_CUMULATIVE_THRESHOLD` |
| `FRAUD_SIGNAL_WEIGHTS` | includes `payee_cumulative: 0.25`, `prompt_injection: 0.60` | `prompt_injection` alone reaches `FRAUD_THRESHOLD` (0.60) |

**Payee registry.** `acme.payees` keeps one identity per payee (`payees`, `payee_names`, `payee_addresses`)
and a ledger of every invoice received for it (`payee_invoices`, rejected and duplicate copies included,
outcome kept in step with the run). An invoice resolves by normalized vendor name or alias (case,
punctuation, and suffixes such as LLC or Co. ignored) **or** by normalized remit-to address (Road = Rd,
Suite = Unit, ...), so differently named vendors at one address count together. Seed creates one payee per
approved vendor plus the Widgets Inc. and Precision Parts Ltd. addresses; other identities and addresses are
learned at disposition and survive a re-seed.

**Cumulative payee threshold.** Validation's `check_payee_threshold` takes the largest `PAYEE_WINDOW_DAYS`
span that includes the invoice's date and sums the payee's invoices in it, each invoice number once at its
latest revision. Over the threshold it raises WARNING `PAYEE_CUMULATIVE_THRESHOLD` (evidence: payees,
window, total, and each contributor's number, date, total, and outcome), so the invoice is held. At
disposition every other contributor is flagged, under the payment batch lock:

- a `queued` or `failed` payment is cancelled (`payment.cancelled`) and the invoice held in Elevated
  Review with a `payee_threshold` hold ("Pulled from Payment Queue"); approve requeues the same payment
  (paid at once when delay is off), reject resolves it Rejected;
- an invoice already awaiting review gets the finding and the latest total added to its hold;
- a paid, rejected, or otherwise resolved invoice gets a `finding.retroactive` audit entry; its status and
  any money paid are left alone.

**Prompt injection.** Invoice text reaches the models only between untrusted-data delimiters. Validation's
`detect_prompt_injection` scans the document text, notes, terms, and line descriptions for text aimed at the
agents (named patterns: `ignore_instructions`, `role_marker`, `agent_address`, `approval_command`,
`fake_verdict`, `skip_checks`, `delimiter_spoof`). A match raises CRITICAL `PROMPT_INJECTION_SUSPECTED`
with the patterns and quoted excerpts as evidence (excerpts are left out of what the models see), so the
invoice is rejected with the fraud flag whatever a model says. Urgency wording ("URGENT - pay immediately")
stays a fraud signal only. The validation model may also report injection with `report_finding`; like every
LLM finding it is capped at WARNING and can only hold the invoice for review.

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
| `PAYMENT_IDLE_DELAY_S` | `60` | `idle` batch once nothing has been processing for the delay (checked every 5 s); also the wait before an `immediate` batch retries a failed payment |

Payment timing is not in `.env`: it lives in the `admin_settings` table and is changed on the Admin page,
with `PUT /api/admin/settings`, or with `python main.py admin set`, and applies without a restart.
`PAYMENT_BATCH_TIME`, `PAYMENT_TZ`, and `PAYMENT_AUTO_IDLE` were removed and are ignored if still set.
The defaults are delay on, pay at end of day off (17:00 America/Chicago once turned on), and pay when the
Invoice Queue is empty on. With delay off, each approved invoice is paid at approval by an `immediate`
batch (released by System); a row approved while another batch runs is paid right after it, and the
5-second check retries failed rows after `PAYMENT_IDLE_DELAY_S`.

Money is a 2-decimal string (`"7750.00"`); timestamps are ISO 8601 UTC. Errors use FastAPI's
`{"detail": ...}`; a 409 carries `{"detail": {"message", "status"}}`, and a 503 with no LLM key carries
`{"detail": {"code": "llm_not_configured", "message", "missing_key"}}`. Every list response has
`server_time`, and every view returns the full current state, so polling every 3 s works.

| Method and path | Purpose |
| --- | --- |
| `POST /api/invoices` | Multipart, field `files` (repeat per file; `file` also accepted). 202 → `{files: [{id, file_name, status: "Uploaded" \| "rejected", size, error}], accepted, rejected, server_time}`. 422 with no files; 503 `llm_not_configured` (nothing stored, no run created) while no LLM key is set |
| `GET /api/invoices?view=queue` | `{view, rows, count, server_time}`. Unresolved runs; row: `id, file_name, format, invoice_number, vendor, amount_usd, stage, status` (Processing, Retrying extraction, Awaiting review), `run_status, uploaded_at, stage_entered_at, time_in_stage_s, final_status, decided_by, completed_at, processing_s` |
| `GET /api/invoices?view=audit` | Resolved runs, newest first (final status Paid, Revised, Rejected, Duplicate, Superseded, Credit confirmed). Filters `status` (comma list), `date_from`, `date_to` (YYYY-MM-DD, completed date in the admin end-of-day timezone), `search` (file, number, vendor). Adds `key_findings` (≤ 3 `{code, severity, message}`), `findings_count` |
| `GET /api/invoices?view=review` | Held runs. Adds `hold_kind` (warning, credit, payment_failure, payee_threshold), `reason` ("Payment failed" for payment failures, "Payee cumulative threshold" for payee holds), `detail, last_error, attempts, findings, ai_recommendation, ai_rationale, overpaid_usd, paid_amount_usd, payee_threshold` (null, or `{total_usd, threshold_usd, window_days, window_start, window_end, payees, message, triggered_by, invoices: [{run_id, invoice_number, invoice_date, vendor, amount_usd, status}]}`), `pulled` (an approved payment pulled from the Payment Queue), `waiting_since, waiting_s` |
| `GET /api/invoices/{id}` | Row fields plus `invoice, extracted, findings, decision, drafts, critiques` (each with `provider`, `model`), `reviews, hold, payment_queue, payments, rejection, timeline` (audit ledger, including `finding.retroactive` flags with `triggered_by` and the payee `total`). 404 if unknown |
| `GET /api/invoices/{id}/file` | Original bytes, content type from the extension (`application/pdf`, `text/plain`, ...). 404 if unknown |
| `POST /api/invoices/{id}/review` | `{decision: "approve" \| "reject", reviewer (1-50 trimmed), rationale (≥ 15)}`. 200 → `{id, decision, reviewer, status: "Resuming"}`; the run resumes on the worker. 422 bad input, 409 not awaiting review, 404 unknown. Credit holds: approve = Credit confirmed, reject = Reject revision. Payee threshold holds: approve requeues the pulled payment, reject = Rejected |
| `GET /api/payment-queue` | `{rows, count, total_usd, delay_payments, pay_at_end_of_day, next_batch_at, next_batch_label ("Today 5:00 PM CT"; both null when no end-of-day batch is scheduled), timezone, pay_when_queue_empty, idle_delay_s, batch_running, server_time}`; row: `id, run_id, file_name, invoice_number, revision, vendor, amount_usd, kind (full, replacement, delta), approved_by, queued_at, status (queued, paying, failed), attempts, last_error, batch_id` |
| `POST /api/payment-queue/execute` | `{ids?: [row id], released_by (1-50 trimmed)}`: no ids = Pay all, one = Pay now, several = Pay selected (an empty list is 422). 202 → `{batch_id, trigger, released_by}`; 409 while a batch runs |
| `GET /api/payments` | Filters `date_from`, `date_to`, `vendor` (substring). `{rows, count, total_usd, server_time}`; row: `payment_id, run_id, file_name, invoice_number, revision, vendor, amount_usd, original_amount, original_currency, kind, delta_label ("Delta for R1"), invoice_total_usd, approved_by, paid_at, idempotency_key, batch_id, batch_trigger, batch_trigger_label, released_by` |
| `GET /api/payment-batches` | `{rows, count, server_time}`, newest first; row: `batch_id, trigger` (`end_of_day`, `idle`, `immediate`, `pay_all`, `pay_selected`, `pay_now`), `trigger_label, released_by, started_at, finished_at, running, count, total_usd, failed_count` |
| `GET /api/admin/settings` | `{delay_payments, pay_at_end_of_day, end_of_day_time ("17:00"), end_of_day_timezone ("America/Chicago"), pay_when_queue_empty, updated_by, updated_at}`; defaults for anything never saved, `updated_by`/`updated_at` null until the first save. No LLM key needed |
| `PUT /api/admin/settings` | All five settings plus `updated_by` (1-50 trimmed). 200 → the saved settings; applied at once (the `end_of_day` job is rescheduled or removed) and audited with old and new values. 422 naming the field for a bad `end_of_day_time` (24-hour HH:MM), an unknown IANA `end_of_day_timezone`, or a bad name; nothing is saved. Turning delay off pays everything queued in one `immediate` batch. No LLM key needed |
| `GET /api/stats` | `in_queue, processing, awaiting_review, payment_queue, paid_today, rejected_today, dollars_queued, dollars_paid, dollars_blocked, duplicates_caught, llm: {provider, model, roles, configured, missing_key}, server_time`. `configured` is false while a needed key is missing; `missing_key` names it (`XAI_API_KEY`, `ANTHROPIC_API_KEY`) or is null |
| `GET /api/events` | SSE: `ready`, `invoice.created`, `invoice.stage_changed`, `invoice.resolved` (data: `run_id, stage, status, final_status, invoice` = the list row), `payment.queued`, `payment.cancelled`, `batch.started`, `payment.created`, `batch.finished` (`count, total_usd, failed_count, results`), `settings.updated` (the full admin settings). Ping every 15 s; no replay |
| `GET /api/invoices.csv`, `GET /api/payments.csv` | CSV of the audit view and payments, same filters as the JSON endpoints |

Payment timing from the shell (the server on port 8000):

```bash
curl -s localhost:8000/api/admin/settings
curl -s -X PUT localhost:8000/api/admin/settings -H 'Content-Type: application/json' \
  -d '{"delay_payments": true, "pay_at_end_of_day": true, "end_of_day_time": "17:00",
       "end_of_day_timezone": "America/Chicago", "pay_when_queue_empty": true, "updated_by": "Dana"}'
curl -s localhost:8000/api/payment-queue    # delay_payments, next_batch_label "Today 5:00 PM CT", ...
```

API tests live in `backend/tests/api/` (`pytest backend/tests/api`).
