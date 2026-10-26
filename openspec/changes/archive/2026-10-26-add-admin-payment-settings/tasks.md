# Tasks

Apply after `reorder-sidebar-menu` and `require-llm-provider` (see design.md, Context).

## 1. Settings storage and schema

- [x] 1.1 Add `admin_settings` (`key` PK, `value`, `updated_by`, `updated_at`) to `backend/src/acme/db/schema.sql`, and add `immediate` to the `payment_batches.trigger` CHECK. Rebuild `payment_batches` in `init_schema` when the old CHECK is detected. Verify in `tests/test_db.py` that a fresh DB has twelve tables, that `init_schema` is repeatable, and that a DB created with the old schema keeps its batch rows and accepts an `immediate` row.
- [x] 1.2 Create `backend/src/acme/admin.py` with `PaymentTiming` (spec defaults), `load_payment_timing`, and `save_payment_timing`:
  - validate `HH:MM`, the IANA timezone via `zoneinfo`, and `updated_by` 1–50 characters after trimming
  - write all keys and an `audit_log` `settings.updated` entry with old and new values in one transaction
  - emit `settings.updated` on the payments event bus

  Verify with new `tests/test_admin.py`: defaults on an empty DB, round trip, each validation error saving nothing, the audit payload, and the event.
- [x] 1.3 Remove `payment_batch_time`, `payment_tz`, and `payment_auto_idle` from `backend/src/acme/settings.py` and `.env.example`. Verify that `tests/test_settings.py` and `tests/api/test_app.py` are updated and pass, and that `grep -rn "payment_tz\|payment_batch_time\|payment_auto_idle" backend/src` is empty.

## 2. Payment timing in the payments module

- [x] 2.1 Change `acme/payments/triggers.py` so that `next_batch_time`, `end_of_day_due`, and `idle_batch_due` take a `PaymentTiming`: no end-of-day batch unless delay and end of day are on, and no idle batch unless delay and pay-when-queue-empty are on. Verify that `tests/payments/test_triggers.py` covers the defaults (no end-of-day batch scheduled, idle on), end of day turned on at the default 17:00 America/Chicago, a custom time and timezone (08:30 America/New_York), delay off, and each toggle off.
- [x] 2.2 Add the `immediate` trigger to `run_batch`, with released_by `System` and the scope of every `queued` row plus `failed` rows whose last attempt is at least `PAYMENT_IDLE_DELAY_S` old. Verify that `tests/payments/test_executor.py` covers the batch record, the scope (a just-failed row skipped and retried after the wait), and the third failure escalating to Elevated Review.
- [x] 2.3 Add `payments.pay_now_if_immediate(conn=None)`, which runs an `immediate` batch when delay is off and returns `None` on `BatchAlreadyRunning`. Also add a post-batch drain hook in `run_batch` that starts another `immediate` batch when delay is off and rows are payable. Verify with a test where a row is queued while a Pay all batch runs and is paid by an `immediate` batch right after it, with no concurrent batch.
- [x] 2.4 Call `pay_now_if_immediate` from disposition (`backend/src/acme/graph/nodes.py`) after `queue_payment` returns `queued`, and from `save_payment_timing` when delay changes true → false. Verify with workflow tests: delay off pays INV-1001 at approval (final status Paid, trigger `immediate`); delay on leaves it `queued`; switching to off with 3 rows queued pays all 3 in one batch; switching to on pays nothing.
- [x] 2.5 Confirm the shared payment and revision test fixtures (`tests/payments/conftest.py`, `tests/workflow` helpers) run with the defaults (delay on), so existing tests keep their meaning; set `pay_at_end_of_day=True` explicitly in end-of-day tests and `delay_payments=False` explicitly in immediate-mode tests. Add the immediate-mode revision test: INV-1004 is paid $1,890.00, then R1 pays a $4,050.00 delta and is Revised. Verify that `pytest backend/tests/payments backend/tests/workflow` passes.

## 3. Golden suite in two configurations

- [x] 3.1 Add a `golden_run(timing)` fixture and run the existing table with the default timing (`delay_payments=True, pay_at_end_of_day=False, pay_when_queue_empty=True`). Verify that `pytest backend/tests/test_golden.py` passes unchanged.
- [x] 3.2 Add the immediate golden variant with `delay_payments=False` set explicitly. Assert:
  - INV-1004 is PAID $1,890.00 with no `SUPERSEDED_BY_REVISION`
  - R1 is Revised with `REVISION` and a $4,050.00 delta
  - counts are 7 paid, 1 revised, 0 superseded, 1 held, 11 rejected (3 duplicates)
  - there are 8 `immediate` batches totalling $37,620.00
  - a following batch pays nothing

  Verify that it passes.

## 4. Backend API

- [x] 4.1 Add `backend/src/acme/api/routers/admin.py` with `GET` and `PUT /api/admin/settings` (422 on a bad time, timezone, or name; no LLM key needed) and register it in `app.py`. Verify with new `tests/api/test_admin.py`: the defaults, a successful PUT then GET, each 422, the audit entry, and the endpoints working with no LLM key.
- [x] 4.2 Update `api/queries.py`:
  - the payment-queue view adds `delay_payments`, `pay_at_end_of_day`, `pay_when_queue_empty`, and `timezone`, renames `auto_idle` to `pay_when_queue_empty`, and returns `next_batch_at` and `next_batch_label` as null when no end-of-day batch is scheduled
  - stats' "today" uses the admin timezone

  Verify that `tests/api/test_views.py` covers delay on with the defaults and delay off.
- [x] 4.3 Make `PaymentScheduler` in `api/scheduler.py` read timing on each tick, start an `immediate` batch when delay is off and rows are payable, and expose `reschedule(timing)` (replace or remove the cron job). Call it when settings are saved. Verify with scheduler tests: a time change from 17:00 to 15:00 moves the job, turning end of day off removes it, and delay off pays a stranded `queued` row within one tick.
- [x] 4.4 Forward `settings.updated` on `/api/events`. Verify that an SSE test receives it with the full settings after a PUT.
- [x] 4.5 Document the admin endpoints and removed env vars in `backend/README.md` ("Web API" section) and verify that the documented curl examples run against a local server.

## 5. CLI

- [x] 5.1 Make single-file and `--batch` output show "Paid" and the payment ID when an invoice was paid at approval, and "Queued for payment" otherwise. Make `--pay` and `payments run` print "nothing queued" when nothing is payable. Verify that `tests/test_cli.py` covers both modes.
- [x] 5.2 Add `python main.py admin show` and `admin set` (`--delay-payments on|off`, `--pay-at-end-of-day on|off`, `--end-of-day-time HH:MM`, `--end-of-day-timezone`, `--pay-when-queue-empty on|off`, `--by NAME` required), using `acme.admin` validation, with no LLM key needed. Verify with CLI tests: `admin show` prints the defaults (delay on, end of day off, queue-empty on), turn delay off and show it, and an invalid timezone exits non-zero with nothing saved.
- [x] 5.3 Make the batch summary report Revised separately from Paid. Verify that the delay-off (immediate) golden summary shows 7 paid, 1 revised, 0 superseded and $37,620.00 paid, and the default (delay-on) summary is unchanged. Update the README's CLI usage section with `admin show` / `admin set` and verify that the commands run as written.

## 6. Web app

- [x] 6.1 Add the Admin item to `frontend/src/app/shell/shell.component.ts`: a separate nav list pinned near the bottom above the provider footer, with icon `admin_panel_settings`, no badge, and kept last when collapsed. Add the `admin` route in `app.routes.ts`. Verify that `shell.component.spec.ts` asserts the six-item order plus Admin at the bottom, and Admin highlighted on `/admin`.
- [x] 6.2 Add `AdminSettings` to `core/api.models.ts`, `getAdminSettings` / `saveAdminSettings` to `core/api-client.ts`, and `settings.updated` handling in the live store. Verify with `api-client.spec.ts` and `live-store.spec.ts`.
- [x] 6.3 Create `pages/admin.page.ts`:
  - **Form.** A reactive form with the delay toggle revealing the end-of-day toggle, time, timezone autocomplete (common US zones and UTC first), and the queue-empty toggle. Time and timezone are enabled only while end of day is on.
  - **Defaults and copy.** On a new database the form shows delay on, end of day off, and queue-empty on; time 5:00 PM and timezone America/Chicago fill in when end of day is turned on. It shows a mode sentence, last saved by and when, and a warning when turning delay off will pay the queue.
  - **Saving.** Save is enabled only when the form is changed and valid. It opens a confirm dialog with a change summary and the shared name field. A success toast confirms the save; a 422 is shown on its field; a `settings.updated` event from elsewhere refreshes an unchanged form or warns on unsaved edits.

  Verify with `admin.page.spec.ts`, covering each scenario in the web-app delta.
- [x] 6.4 Update `pages/payment-queue.page.ts` so the header shows the mode:
  - delay off: "paid at approval"
  - delay on: next batch label when scheduled, and pay when queue empty on or off
  - in both modes, a link to Admin; Pay all / Pay selected / Pay now stay available

  Update its model fields (`auto_idle` becomes `pay_when_queue_empty`). Verify with component tests for both modes.
- [x] 6.5 Confirm `frontend/e2e/happy-path.spec.ts` runs unchanged under the defaults (delay on, end of day off), so the existing upload → review → Pay all flow is unchanged. Add an e2e step that turns delay off on Admin, uploads `invoice_1006.csv`, and sees it in Payments with batch trigger `immediate` without clicking Pay. Verify that `make e2e` passes.
- [x] 6.6 List the `Revised` final status on the Invoice Resolution Audit page: offer it in the status filter and give it its own chip style, and confirm `GET /api/invoices?view=audit&status=Revised` returns revised runs. Verify with a component test for the filter option and an API test for the status filter.
- [x] 6.7 Verify that `npm --prefix frontend run build` and `npm --prefix frontend run test:ci` pass with no warnings.

## 7. Docs and integration

- [x] 7.1 Update the root README's web app section with the Admin page, payment modes, and the removed `.env` keys, and verify that the steps match the running app.
- [x] 7.2 Integration check:
  - from a clean checkout with an LLM key set, run `make setup`, then `./run.sh`
  - upload `invoice_1001.txt` and confirm it waits in the Payment Queue with no end-of-day batch scheduled (defaults)
  - on Admin, as "Dana", turn Pay at end of day on and confirm the next batch shows 5:00 PM CT
  - turn delay off and confirm the queued invoice is paid by an `immediate` batch; upload `invoice_1006.csv` and confirm it is paid at approval
  - verify `pytest backend/tests` passes

## Workflow follow-up

- Archive this change only after `reorder-sidebar-menu` and `require-llm-provider` are archived.

## Implementation notes

- 7.2 was run against the test-only fake server (`backend/tests/fake_server.py`, dummy `XAI_API_KEY=test-key`, fresh seeded DB in a scratch directory) with `ng serve` on :4200, instead of `./run.sh` with a live LLM key; no live LLM call was made. The four UI steps were driven with Playwright and all passed (next batch "Today 5:00 PM CT"; INV-1001 and INV-1006 each paid by an `immediate` batch released by System). `pytest backend/tests`: 788 passed.
- `golden_run(timing)` is the session fixture `run_golden(timing)` in `tests/conftest.py` (a context manager); the module fixtures `golden_run` (defaults) and `golden_immediate` (delay off) in `test_golden.py` build on it, so the existing golden tests keep their fixture name.
- The API admin tests live in `tests/api/test_admin_endpoints.py`: pytest's rootdir import mode cannot collect two modules named `test_admin.py` (`tests/test_admin.py` holds the 1.2 tests).
- A failed row's "last attempt" is its batch's finish time (`payment_batches.finished_at` via `payment_queue.batch_id`); no column was added.
- `pay_now_if_immediate` also returns None when nothing is payable, so no empty `immediate` batch records are written (the golden variant has exactly 8).
- e2e: `start-backend.sh` keeps delay on and end of day off but turns pay-when-queue-empty off (`admin set`), replacing the old `PAYMENT_AUTO_IDLE=false`, so no idle batch races the happy path's Pay all. The new immediate-mode step uploads `invoice_1015.csv` instead of `invoice_1006.csv`, because the happy path in the same run already paid INV-1006 (a re-upload is a Duplicate).
- The batch summary row "Revised (no payment due)" is now "Revised" (it also counts paid deltas); the default-mode counts are unchanged. The `immediate` batch trigger label is "Immediate (at approval)".
- After archiving, `openspec validate --all --strict` flagged four synced requirements over 500 characters (backend-api Scheduled payment batches and Live event stream, data-model Database schema, web-app Payment Queue page). Their wording in `openspec/specs` was condensed with the same meaning; the `admin_settings` columns moved into the schema scenario, and the Payment Queue mode details rely on its Delayed and Immediate mode header scenarios.
