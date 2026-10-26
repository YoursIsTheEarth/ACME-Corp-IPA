# Design

## Context

Changes 1 through 5 deliver the models and `acme.db` schema, the LLM factory, the agent graph with its `interrupt()` review hold, the SQLite checkpointer, and the payment queue and executor. Those layers expose plain Python functions with no HTTP. This change puts a FastAPI process in front of them for the web app. Motivation is in proposal.md; the HTTP contract is in specs/backend-api/spec.md.

Constraints:
- Everything runs locally, on one machine, with SQLite and no extra services.
- No login.
- Uploads are capped at 10 MB per file.
- The API must give the same results as the CLI.

## Goals / Non-Goals

**Goals:**
- A thin HTTP layer: routers translate requests into calls on the workflow and payment services and add no business rules.
- Uploads return fast, and processing happens off the request path.
- One process runs the API, the worker, and the scheduler, so `make dev` starts one backend.

**Non-Goals:**
- Running multiple API instances or workers.
- Authentication, rate limiting, and HTTPS.
- WebSockets. SSE plus polling covers the one-way updates the pages need.

## Decisions

1. **Package layout.** The code lives in `backend/src/acme/api/`:
   - `app.py` holds the app factory and the lifespan that starts the worker and scheduler and runs recovery.
   - `routers/` has one module each for `invoices.py`, `reviews.py`, `payments.py`, `stats.py`, and `events.py`.
   - `schemas.py` holds the request and response Pydantic models.
   - `worker.py`, `scheduler.py`, and `events.py` hold the in-process event bus.

   Run it with `uvicorn acme.api.app:create_app --factory`. Routers call service functions from `agent-workflow` and `payment-processing` only. *Alternative:* putting queries straight in the routers. Rejected, because it would let the API and the CLI drift apart.

2. **Upload worker: an asyncio queue plus a thread pool.** The upload handler validates each file, writes it to `UPLOAD_DIR/<run_id>/<file_name>`, inserts an `invoice_runs` row (status Uploaded), and puts the `run_id` on an `asyncio.Queue`. One consumer task runs each run through the graph in `run_in_executor`, because the graph and the LLM calls are blocking. Concurrency defaults to 1, so files process in arrival order. That keeps duplicate and revision detection deterministic and matches the CLI's sorted-order assumption: INV-1004 is queued before R1 arrives. *Alternative:* FastAPI `BackgroundTasks`. Rejected, because those tasks are lost on restart and have no ordering control. Celery or RQ would also work but needs Redis, which is a non-goal.

3. **Status changes come from the workflow.** The workflow writes `invoice_runs.stage` and `status` as nodes run, which `agent-workflow` owns. It also calls an optional `on_event` callback. The API passes a callback that publishes to the event bus, so the CLI pays nothing for this.

4. **Review resume.** The handler validates the body first; Pydantic `constr(strip_whitespace=True, min_length=1, max_length=50)` produces the 422s. It then calls `agent-workflow`'s `resume_review(run_id, decision, reviewer, rationale)`, which owns the claim: in a `BEGIN IMMEDIATE` transaction it runs `UPDATE invoice_runs SET status='Resuming' WHERE id=? AND status='Awaiting review'`, inserts `review_decisions`, and resumes the graph with `Command(resume=...)` (or calls `resume_payment_failure` for payment-failure holds). `ReviewConflict` maps to 409. The resume runs on the worker pool, and the handler returns 200 once the decision is recorded. The conditional update makes concurrent decisions safe without an in-memory lock that wouldn't survive a restart.

5. **Payment execution.** `POST /api/payment-queue/execute` calls `payment-processing`'s `run_batch(trigger, released_by, ids)`. That function holds the single batch lock and raises `BatchAlreadyRunning`, which the API maps to 409. The handler returns 202 with the `batch_id` as soon as the batch is recorded, and the rows are paid on the worker pool. Trigger mapping:
   - `ids` omitted → `pay_all`
   - one id → `pay_now`
   - several ids → `pay_selected`

6. **Scheduler.** APScheduler runs as an `AsyncIOScheduler` started in the lifespan, with two jobs:
   - A `CronTrigger` at `PAYMENT_BATCH_TIME` in `America/Chicago`, trigger `end_of_day`.
   - An `IntervalTrigger` every 5 seconds that loads the run and queue snapshot and calls the pure `idle_batch_due(now, runs_snapshot, queue_count, batch_running, settings)` from `payment-processing`; if true, it starts an `idle` batch.

   Both treat `BatchAlreadyRunning` as "skip this tick." `next_run_time` of the cron job feeds `/api/payment-queue`. *Alternative:* a separate cron process. Rejected, because it adds a second process to run.

7. **SSE (P1).** The in-process `EventBus` keeps one `asyncio.Queue` per connected client, and `publish` fans out to all of them. Publishing from worker threads uses `loop.call_soon_threadsafe`. `/api/events` uses `sse-starlette`'s `EventSourceResponse` with a 15-second ping. Events are not replayed, because clients re-fetch the list endpoints on reconnect. That is why the polling contract requires full-state responses.

8. **Restart recovery in the lifespan, before serving.** Recovery runs four steps:
   - `agent-workflow`'s `recover_orphaned_runs()` returns runs in Uploaded, Extracting, Validating, or Deciding, and the lifespan re-enqueues them. The graph resumes from its last checkpoint where one exists; otherwise it starts over. Extraction is idempotent and duplicate detection keys on `run_id`.
   - Runs Awaiting review need no action, because their checkpoint is on disk and the review endpoint resumes it.
   - Runs left in `Resuming` are re-submitted with their stored `review_decisions` row.
   - Payment rows in `paying` go through `payment-processing`'s `recover_interrupted_batch()`: a row whose idempotency key is in `payments` becomes paid, and the rest go back to queued.

9. **Validation and errors.** Allowed extensions and the 10 MB cap come from settings. The handler checks size by streaming to disk and aborting once the cap is passed, rather than trusting `Content-Length`. Errors use FastAPI's default `{"detail": ...}` shape. A 409 body carries the run's current status so the dialog can explain what happened.

10. **CORS.** `CORSMiddleware` is configured with `allow_origins=[settings.API_CORS_ORIGIN]` and no credentials.

11. **CSV (P2).** The CSV handlers reuse the list query functions and stream rows with `csv.writer` into a `StreamingResponse`.

## Risks / Trade-offs

- [Single worker means a slow LLM call holds up the queue] → At under 30 seconds per invoice (spec target) and demo-sized batches, ordering matters more than throughput. Concurrency is a setting (`WORKER_CONCURRENCY`) that can be raised later.
- [SQLite write contention between the worker, the scheduler, and requests] → Use WAL mode and short transactions; `BEGIN IMMEDIATE` only around the review and batch-claim updates.
- [SSE events can be missed during a reconnect] → Clients re-fetch the full state on reconnect, and polling stays as the fallback.
- [Re-running a run that was mid-processing could double-record findings] → Recovery resumes from the checkpointer, and audit entries are keyed by `run_id` and stage, so replays append a "resumed" marker rather than duplicates.
- [The idle check fires between files of a multi-file upload] → Uploads insert all their runs in one transaction before returning, so the idle condition sees them as Uploaded right away.

## Migration Plan

This is new code with no existing behavior to migrate. Rollback means not starting the API, and the CLI is unaffected.

## Open Questions

- Should `WORKER_CONCURRENCY` above 1 ever be the default? It can be decided after measuring, because it doesn't change the API contract.

## Implementation notes

- **Dependencies.** `fastapi~=0.162`, `uvicorn[standard]~=0.54`, `python-multipart~=0.0.32`, `apscheduler~=3.11`, `sse-starlette~=3.6`; `httpx~=0.28` went into the existing `dev` extra (the repo has no `test` extra), so `pip install -e "backend[dev]"` covers the tests. The settings in task 1.2 already existed in the foundation catalog with a defaults test; `tests/api/test_app.py` re-checks them.
- **Layout.** As in D1, plus `queries.py` (read-only SQL for every list/detail/stats view, shared by the CSV handlers), `deps.py` (services + per-request connection, opened inside the endpoint because sqlite connections are thread-bound), and `csv_export.py`. Response bodies are plain dicts; the field contract is documented in `backend/README.md` (Web API).
- **Upload.** `workflow.create_run` commits per call, so runs are inserted one commit each (all before the 202 and before anything is enqueued) rather than in one transaction; files are streamed to `UPLOAD_DIR/.incoming/`, then moved to `UPLOAD_DIR/<run_id>/<file_name>` and `stored_path` updated in one transaction. Multipart field `files` (repeatable); `file` is also accepted. Rejected entries have `status: "rejected"` and an `error`.
- **Views.** `view=queue` maps `status` to the page's labels (Processing, Retrying extraction, Awaiting review) and keeps the raw value as `run_status`; "time in stage" is measured from the run's latest audit row. `view=audit` lists every Resolved run, so `Revised` (delta paid / same total) appears too, not only the five statuses the spec names. Findings for list rows come from the audit ledger (`validation.findings`/`fallback`, `rejection.recorded`, `invoice.superseded`), so lists never open the checkpointer; the detail endpoint uses `run_state`. Payments rows join the ledger to `payment_queue` by idempotency key; the original currency comes from the run's `CURRENCY_CONVERTED` finding. "Today" and date filters use the local date in `PAYMENT_TZ`. `dollars_blocked` = totals of Rejected + Duplicate runs. `llm.provider/model` is the approval (AI VP) role's, with every role under `llm.roles`.
- **Review.** The endpoint calls `record_review` (claim + `review_decisions`) and then queues `continue_review` on the same FIFO worker as uploads (not `resume_review` in one call), so it returns 200 with `status: "Resuming"` as soon as the decision is recorded. Unknown ids are 404.
- **Batches.** `BatchRunner` runs `run_batch` on a 4-thread pool (more than one so a second request reaches the lock and gets 409 instead of queueing) and returns the batch ID when the batch's own `batch.started` event fires (matched by thread). `ids: []` is 422 rather than Pay all. The scheduler passes `PAYMENT_TZ` to both triggers explicitly (APScheduler's local-zone lookup fails on a non-IANA `TZ`, e.g. `CDT5`). The idle job is only added when `PAYMENT_AUTO_IDLE` is on, and `idle_tick(now)` re-checks it; tests drive `idle_tick`/`end_of_day` with explicit times through the TestClient portal.
- **Recovery** runs in the lifespan before serving, in this order: `recover_interrupted_batch()`, re-submit `Resuming` runs, re-enqueue `recover_orphaned_runs()`. The lifespan also creates and seeds an empty `acme.db` (as the CLI does) and runs `check_keys()`.
- **SSE.** A `ready` event is sent first on each connection. Workflow events carry `invoice` = the run's current list row; payment events are forwarded from `acme.payments.events` unchanged (dataclass `RowResult`s in `batch.finished` are converted to objects). The `batch.finished` *audit* payload (written by add-payment-processing) stores each `RowResult` as its repr string; noted, not changed. SSE tests run against a real uvicorn server in a thread, because the TestClient cannot consume an endless stream.
- **Tests.** `backend/tests/api/` (94 tests): a session-scoped fixture uploads all 20 golden files through the API and pays them once, shared by the parity, payments, detail, and stats tests.
