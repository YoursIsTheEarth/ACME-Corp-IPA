# Design

## Context

See proposal.md for why. Today:

- **Timing comes from `.env`.** `acme.settings.Settings` holds `payment_batch_time`, `payment_tz`, and `payment_auto_idle`. They are read in three places:
  - `acme/payments/triggers.py`, for the next batch time, the end-of-day decision, and `idle_batch_due`
  - `acme/api/scheduler.py`, where `PaymentScheduler` builds a `CronTrigger` from them and a 5-second idle check
  - `acme/api/queries.py`, for the payment-queue header and the "today" date bucketing in stats
- **Payments are only queued.** Disposition (`acme/graph/nodes.py`) calls `payments.queue_payment(...)`, which only queues. Paying happens through `payments.run_batch(trigger, released_by, ids)` under a single DB-backed lock that raises `BatchAlreadyRunning`.
- **Triggers are restricted.** `payment_batches.trigger` has a SQL `CHECK` limited to `end_of_day`, `idle`, `pay_all`, `pay_selected`, and `pay_now` (`acme/db/schema.sql`).
- **Frontend.** The sidebar lives in `frontend/src/app/shell/shell.component.ts`, routes in `app.routes.ts`, and the Payment Queue page in `pages/payment-queue.page.ts`. The shared 1–50 character name field is `shared/reviewer-name-field.component.ts`.
- **Sequencing.** `reorder-sidebar-menu` and `require-llm-provider` modify the sidebar requirement, the golden outcomes, CLI payment commands, and the batch summary. This change's MODIFIED blocks are written on top of their text. **Apply and archive this change after both.**

## Goals / Non-Goals

**Goals:**
- One source of truth for payment timing that operators edit at runtime, from the web app or the CLI.
- Immediate payment reuses the existing executor, lock, re-checks, idempotency, retries, and revision rules. There is no second payment path.

**Non-Goals:**
- Authentication or roles for the Admin page. There is no login, a prototype non-goal; the typed name is attribution only.
- Other admin settings, such as FX rates, thresholds, or the LLM provider. The page and table are shaped to grow, but only payment timing is in scope.
- Per-vendor or per-amount payment schedules.

## Decisions

**D1. `admin_settings` key/value table, with defaults in code.**
- **What.** The table has columns `key` PK, `value` (JSON text), `updated_by`, and `updated_at`. A new `acme.admin` module exposes:
  - `PaymentTiming` (Pydantic: `delay_payments=False`, `pay_at_end_of_day=True`, `end_of_day_time=17:00`, `end_of_day_timezone="America/Chicago"`, `pay_when_queue_empty=True`)
  - `load_payment_timing(conn=None)`, which merges stored keys over the defaults
  - `save_payment_timing(timing, updated_by, conn=None)`, which validates, writes all keys in one transaction, writes an `audit_log` row (`agent="admin"`, `event="settings.updated"`, payload `{by, changes: {key: [old, new]}}`), and emits `settings.updated` on `acme.payments.events`
- **Why key/value.** It lets later admin settings be added without a migration. A single JSON row was considered; key/value gives per-key `updated_at` for free and keeps `CREATE TABLE IF NOT EXISTS` idempotent on old databases.
- **Validation.** The timezone uses `zoneinfo.ZoneInfo` (an unknown name gives a 422 or CLI error), and the time is a strict `HH:MM` 24-hour string.

**D2. Remove `PAYMENT_BATCH_TIME`, `PAYMENT_TZ`, and `PAYMENT_AUTO_IDLE` from `Settings`.**
- The trigger functions take a `PaymentTiming` argument, so they stay pure and testable: `next_batch_time(now, timing)`, `end_of_day_due(...)`, `idle_batch_due(now, runs_snapshot, queue_count, batch_running, settings, timing)`.
- `PAYMENT_IDLE_DELAY_S`, `PAYMENT_MAX_ATTEMPTS`, and `PAYMENT_LOCK_TIMEOUT_S` stay in `.env`, as tuning rather than operator choices.
- Stats' "today" uses the admin timezone, since that is the business day finance cares about.
- Alternative considered: keep the env values as seed defaults. Rejected, because two sources of truth would confuse anyone reading `.env`.

**D3. Immediate mode is a batch, not a direct call.**
- **Disposition.** After `queue_payment(...)` returns `queued` (including `delta` and `replacement` rows), disposition calls a new `payments.pay_now_if_immediate(conn)`. When `delay_payments` is false, that runs `run_batch("immediate", "System")` synchronously, before disposition reports the run finished.
- **Scope.** The `immediate` scope (spec: Batch scope by trigger) is all `queued` rows plus `failed` rows whose last attempt is at least `PAYMENT_IDLE_DELAY_S` old.
- **Collisions.** If `BatchAlreadyRunning` is raised, the row stays `queued`.
- **Draining after any batch.** When any batch finishes and delay is off, `run_batch` calls the drain hook again. That catches rows that arrived during the batch and is the "paid right after" guarantee.
- **The API.** The API scheduler's existing 5-second tick runs the same check when delay is off. It catches failed-row retries after the wait, and anything missed if a process died between queueing and paying.
- **The CLI.** The CLI has no scheduler. Retries happen on the next approval in the same process, or through `payments run`.
- **Why.** Calling `mock_payment` from disposition would bypass the lock, re-checks, ledger, and retry accounting. Reusing `run_batch` keeps one money path.
- **The new trigger value.** `immediate` is added to the `payment_batches.trigger` CHECK. SQLite cannot alter a CHECK in place, so `init_schema` rebuilds `payment_batches` with the new CHECK when the old one is detected (`CREATE` new, `INSERT SELECT`, `DROP`, `RENAME`, in one transaction). This is tested on a database created by the old schema.

**D4. Mode switches.**
- Saving with `delay_payments` changing true → false triggers one `immediate` batch right after the save commits: synchronously in the CLI, on the batch runner in the API.
- Changing false → true does nothing to existing rows.
- When the timezone or time changes, `PaymentScheduler.reschedule(timing)` replaces the cron job (by job id) or removes it when end of day is off. The idle check reads timing on every tick, so it needs no reschedule.

**D5. API shape.**
- **Router.** A new `acme/api/routers/admin.py` serves:
  - `GET /api/admin/settings`
  - `PUT /api/admin/settings`, with body `{delay_payments, pay_at_end_of_day, end_of_day_time, end_of_day_timezone, pay_when_queue_empty, updated_by}`
- **Validation.** `updated_by` is trimmed and checked by the same validator as reviews; a failure gives 422 with FastAPI's field-path detail.
- **Payment-queue fields.** `GET /api/payment-queue` adds `delay_payments`, `pay_at_end_of_day`, `pay_when_queue_empty`, and `timezone`. `next_batch_at` and `next_batch_label` are null when no end-of-day batch is scheduled, and the old `auto_idle` key becomes `pay_when_queue_empty`.
- **SSE.** `settings.updated` carries the full timing.
- **No key needed.** The admin endpoints make no LLM call and stay available without an LLM key, consistent with `require-llm-provider`.

**D6. Frontend.**
- **Route.** `admin` loads a standalone `AdminPage` with a reactive form.
- **Sidebar.** `shell.component` renders Admin in a separate `mat-nav-list` after a spacer and divider, above the provider footer, with icon `admin_panel_settings`.
- **Timezone picker.** It uses `Intl.supportedValuesOf('timeZone')` with a filterable autocomplete, with America/Chicago, America/New_York, America/Denver, America/Los_Angeles, and UTC listed first.
- **Defaults on first enable.** When `delay_payments` is first switched on, the form shows the spec defaults if they were never saved. The backend already returns defaults for unsaved keys.
- **Save.** Save opens a confirm dialog listing changed fields, with the shared name field.
- **Payment Queue header.** It renders the mode text and a `routerLink` to `/admin`.

**D7. Golden suite runs in two configurations.**
- **Fixture.** `golden_run(timing)` in `tests/conftest.py`, applied with `save_payment_timing` before processing.
- **Existing table.** It runs with `delay_payments=True, pay_at_end_of_day=False, pay_when_queue_empty=True`. There is no scheduler in tests, so idle never fires, and the explicit batch reproduces today's results.
- **New variant.** It runs with the defaults and asserts 7 Paid, 1 Revised, 0 Superseded, 1 held, 11 rejected (3 duplicates), and 8 `immediate` batches. The amounts are INV-1004 $1,890.00 and the R1 delta $4,050.00 ($5,940.00 − $1,890.00), with the total still $37,620.00.
- **Other payment tests.** Existing payment, revision, idle and end-of-day tests set `delay_payments=True` explicitly so their meaning is unchanged.

**D8. CLI.** `admin show` and `admin set` are thin wrappers over `load_payment_timing` and `save_payment_timing`. They're cheap because validation lives in `acme.admin`. Single-file output gains the payment ID when it was paid at approval.

## Risks / Trade-offs

- [The default flips to paying at approval, so a revision can no longer replace an unpaid original in the common case] → Paid-original rules (delta, credit hold, Revised) are already implemented and tested. The Payment Queue header and the Admin page explain the mode, and the delayed golden table keeps the replacement path tested.
- [Synchronous immediate batches add `mock_payment` latency to every approval] → `mock_payment` is local and fast. In the API the pipeline already runs on the worker thread, not the request.
- [Rebuilding the `payment_batches` table on old databases] → It runs in one transaction, only when the old CHECK is detected, and is covered by a migration test using a database created with the old schema.
- [No authentication on Admin] → It is attributed by typed name and audited, consistent with reviews. Real access control is a stated non-goal.
- [A failed row hammering retries in immediate mode] → Retries wait `PAYMENT_IDLE_DELAY_S` since the last attempt, and the existing `PAYMENT_MAX_ATTEMPTS` escalation still applies.

## Migration Plan

1. Deploy: `init_schema` adds `admin_settings` and rebuilds `payment_batches` if needed.
2. The default is delay off. Anyone who set `PAYMENT_BATCH_TIME`, `PAYMENT_TZ`, or `PAYMENT_AUTO_IDLE` in `.env` must re-enter them on the Admin page or with `admin set`. Those keys are now ignored and removed from `.env.example`.
3. Rollback: revert the code. The extra table is harmless to the old code, and `immediate` batch rows would violate the old CHECK only if the table were rebuilt again, which the old code never does.
