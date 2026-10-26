# Proposal

## Why

The ACME Corp IPA web app needs an HTTP service that runs the same agent pipeline as the CLI. People upload invoices, watch them move through the stages, decide held invoices, and release payments without touching a terminal. Without that service, the human-in-the-loop review (F28) and the payment batch triggers (F38) are only reachable from the CLI, and the web app (change `add-ipa-web-app`) has nothing to talk to.

## What Changes

**P0 - MVP**
- Add a FastAPI app (served by Uvicorn) in `backend/src/acme/api/` that wraps the LangGraph pipeline from `add-agent-workflow` and the payment executor from `add-payment-processing`, so the CLI and the API produce identical results (F27).
- `POST /api/invoices` accepts a multipart upload of one or many files. It validates each file's type (.pdf, .txt, .csv, .json, .xml, .eml) and size (10 MB or less, not empty), stores accepted files under `uploads/`, creates an `invoice_runs` row, and returns 202 within 1 second. A background upload worker then runs each invoice through the graph (F27).
- Read endpoints:
  - `GET /api/invoices?view=queue|audit|review`
  - `GET /api/invoices/{id}`
  - `GET /api/invoices/{id}/file`
  - `GET /api/payments`
  - `GET /api/stats`
  - `GET /api/payment-queue`
  - `GET /api/payment-batches`
- Human-in-the-loop endpoint `POST /api/invoices/{id}/review`. It validates the reviewer name (1 to 50 characters after trimming) and the rationale (at least 15 characters), returning 422 when either fails. It returns 409 when the invoice is no longer awaiting review. Otherwise it resumes the paused LangGraph run (F17, F28).
- Payment endpoint `POST /api/payment-queue/execute`. It takes optional `ids` (Pay selected and Pay now; omit for Pay all) and `released_by` (1 to 50 characters), starts a batch, and returns 202 with the batch ID. It returns 409 when a batch is already running (F16, F38, F40).
- APScheduler runs inside the FastAPI process. It schedules the end-of-day batch at `PAYMENT_BATCH_TIME` (America/Chicago) and an idle check that fires a batch after `PAYMENT_IDLE_DELAY_S` with nothing in processing. Setting `PAYMENT_AUTO_IDLE=false` disables the idle check (F38).
- CORS allows only the Angular dev server origin. There is no login, which is a non-goal.
- Restart durability: on startup, the API re-attaches held invoices from the SQLite checkpointer, re-enqueues invoices that were mid-processing, and resets payment rows left in `paying` back to `queued` without losing them (F28).
- Polling fallback contract: every list and stats endpoint is cheap enough to poll every 3 seconds and returns the full current view, so the web app works before SSE lands (F29).

**P1 - Should**
- `GET /api/events` is a Server-Sent Events stream. It carries `invoice.created`, `invoice.stage_changed`, `invoice.resolved`, `payment.queued`, `payment.cancelled`, `batch.started`, `batch.finished`, and `payment.created` (F29).
- `GET /api/stats` adds the batch summary figures used by the Home tiles: dollars queued, paid, and blocked, plus duplicates caught (F31).

**P2 - Stretch**
- `GET /api/invoices.csv` and `GET /api/payments.csv` export the current filter (F35).

## Capabilities

### New Capabilities
- `backend-api`: HTTP contract of the ACME Corp IPA backend. It covers the upload intake and background worker, the read views for each web page, review resume, payment queue execution, scheduled batch triggers, the SSE event stream, CSV export, CORS, and restart durability.

### Modified Capabilities
- None. This change consumes `data-model`, `llm-provider`, `audit-logging`, `agent-workflow`, and `payment-processing` without changing their requirements.

## Impact

- New code: `backend/src/acme/api/` (app factory, routers, schemas, upload worker, scheduler, event bus) and `backend/tests/api/`.
- New dependencies in `backend/pyproject.toml`: `fastapi`, `uvicorn[standard]`, `python-multipart`, `apscheduler`, `sse-starlette` (P1), and `httpx` (tests).
- Settings (declared in `add-project-foundation`'s settings catalog): `API_CORS_ORIGIN` (default `http://localhost:4200`), `UPLOAD_DIR` (default `uploads/`), and `UPLOAD_MAX_BYTES` (10 MB). The service also reads the existing `PAYMENT_BATCH_TIME`, `PAYMENT_IDLE_DELAY_S`, and `PAYMENT_AUTO_IDLE`.
- Reads and writes the `invoice_runs`, `review_decisions`, `payment_queue`, `payment_batches`, `payments`, and `audit_log` tables defined by `data-model`.
- Depends on changes 1 through 5. It is a prerequisite for `add-ipa-web-app`.
