# Tasks

## 1. Setup (P0)

- [x] 1.1 Add `fastapi`, `uvicorn[standard]`, `python-multipart`, and `apscheduler` to `backend/pyproject.toml` (with `httpx` as a test extra); verify `pip install -e backend[test]` succeeds
- [x] 1.2 Read `API_CORS_ORIGIN`, `UPLOAD_DIR`, `UPLOAD_MAX_BYTES`, `ALLOWED_UPLOAD_EXTENSIONS`, and `WORKER_CONCURRENCY` from the foundation settings catalog; verify a settings unit test loads the defaults
- [x] 1.3 Create `backend/src/acme/api/` with an app factory, lifespan, CORS middleware, and `routers/` package, then add an `httpx` test client fixture in `backend/tests/api/conftest.py` with a temp `acme.db` in offline mode; verify the CORS test passes for `http://localhost:4200` and fails for another origin

## 2. Upload intake and worker (P0, F27)

- [x] 2.1 Implement `POST /api/invoices` with per-file type, empty, and 10 MB checks, streamed storage under `UPLOAD_DIR/<run_id>/`, and `invoice_runs` inserts in one transaction; verify tests cover a multi-file 202, mixed valid and invalid files, no files (422), and a response time under 1 second
- [x] 2.2 Implement the asyncio queue worker that runs each run through the agent workflow on a thread pool in arrival order and publishes `on_event` callbacks; verify an API test that uploads `invoice_1002.txt` and waits ends Rejected with `STOCK_EXCEEDED`, the same as the CLI
- [x] 2.3 Add a parity test that uploads all 20 golden files in sorted order through the API in offline mode; verify the final statuses match `backend/tests/test_golden.py`'s expectations

## 3. Read views (P0, F23–F26, F40)

- [x] 3.1 Implement `GET /api/invoices?view=queue|audit|review` with the audit filters (status, date, search) and `server_time`; verify tests for each view, the dual listing of Awaiting review, and 422 on an unknown view
- [x] 3.2 Implement `GET /api/invoices/{id}` (full record and timeline) and `GET /api/invoices/{id}/file` (original bytes and content type); verify tests for `invoice_1009.json` findings, PDF bytes round-trip, and 404 on an unknown id
- [x] 3.3 Implement `GET /api/payments` (date and vendor filters, filter total, original currency, delta label, batch and released by) and `GET /api/payment-batches`; verify tests after a golden batch, including the EUR row for `invoice_1014.xml`
- [x] 3.4 Implement `GET /api/payment-queue` (rows, count, total, next batch time in America/Chicago, auto-idle flag) and `GET /api/stats` (P0 counts); verify tests for the $7,750.00 two-row queue, the 1004 replacement row, and badge counts

## 4. Review resume (P0, F17, F25, F28)

- [x] 4.1 Implement `POST /api/invoices/{id}/review` with trimmed-name validation (1 to 50), a rationale of at least 15 characters, and the decision enum; verify the 422 tests for spaces-only, 51-character, and short-rationale inputs, and that a padded name is stored trimmed
- [x] 4.2 Call `acme.workflow.resume_review` (which owns the `Awaiting review → Resuming` claim, the `review_decisions` insert, and the graph resume) and map `ReviewConflict` to 409; verify tests that approve queues a payment, reject resolves Rejected, two concurrent decisions give exactly one 200 and one 409, and a processing invoice gives 409
- [x] 4.3 Handle credit or refund holds (approve maps to Credit confirmed, reject to Reject revision, never queues a payment, review view shows the overpaid amount); verify a test built from a lower-total INV-1004 revision after payment
- [x] 4.4 Show payment-failure holds in `view=review` with reason "Payment failed" and the last error, and include `llm` provider/model in `/api/stats`; verify approve requeues the payment and the stats test reads the configured model

## 5. Payment execution and scheduler (P0, F16, F38, F40)

- [x] 5.1 Implement `POST /api/payment-queue/execute` (`ids` maps to `pay_all`, `pay_now`, or `pay_selected`; `released_by` 1 to 50; 202 with `batch_id`; 409 on `BatchAlreadyRunning`); verify tests for each trigger, 422 on an empty name, and concurrent Pay all giving one 409 with each row paid once
- [x] 5.2 Start an APScheduler `AsyncIOScheduler` in the lifespan with the `end_of_day` cron job (`PAYMENT_BATCH_TIME`, America/Chicago) and the 5-second idle check honoring `PAYMENT_IDLE_DELAY_S` and `PAYMENT_AUTO_IDLE`; verify tests with a frozen clock for the 3-file idle wait, a held invoice not blocking, idle disabled, and a skipped tick while a batch runs
- [x] 5.3 Document the run command, settings, and endpoint list in `backend/README.md`; verify `uvicorn acme.api.app:create_app --factory` starts and `/docs` lists every endpoint

## 6. Restart durability (P0, F28)

- [x] 6.1 Implement lifespan recovery: re-enqueue the runs returned by `recover_orphaned_runs()`, re-submit `Resuming` runs, and call `recover_interrupted_batch()` for `paying` rows; verify a test that holds `invoice_1010.txt`, restarts the app, approves, and sees the payment queued
- [x] 6.2 Add a crash-mid-batch test (3 rows paying, 1 already in `payments`); verify that after restart 1 row is paid, 2 are queued, and the next batch pays exactly 2

## 7. Live updates and stats (P1, F29, F31)

- [x] 7.1 Add `sse-starlette`, the `EventBus` with thread-safe publish, and `GET /api/events` with a 15-second ping; verify a test receives `invoice.created`, `invoice.stage_changed`, and `invoice.resolved` in order for `invoice_1002.txt`
- [x] 7.2 Publish `payment.queued`, `payment.cancelled`, `batch.started`, `payment.created`, and `batch.finished` from the queue and executor callbacks; verify tests for the 1004 revision swap events and a 7-row batch
- [x] 7.3 Extend `GET /api/stats` with dollars queued, paid, and blocked, and duplicates caught; verify that after the golden run, duplicates caught equals 3

## 8. CSV export (P2, F35)

- [x] 8.1 Implement `GET /api/invoices.csv` and `GET /api/payments.csv` as streamed `text/csv` honoring the JSON filters; verify a test that the CSV rows equal the JSON rows for the same vendor filter

## 9. Integration check

- [x] 9.1 Run the full `pytest backend/tests/api` suite plus the golden suite in offline mode; verify all pass and a manual upload of 3 files followed by Pay all shows the payments in `GET /api/payments`
