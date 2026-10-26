# Proposal

## Why

Payment timing is fixed today: every approved invoice waits in the Payment Queue for an end-of-day or idle batch, and the only way to change the batch time, timezone, or idle trigger is to edit `.env` and restart. Acme wants an operator to choose and tune payment timing from the app: batching stays the default (paid when the Invoice Queue empties), and paying each invoice at approval or at a configured end-of-day time are options an operator can switch on.

## What Changes

- **Admin page (F41, P0).** A new "Admin" item near the bottom of the left sidebar, visually separated from the main menu, opens an Admin configuration page for payment timing:
  - **Delay payments**, default **on**. When off, an approved invoice is paid as soon as it is completely processed and approved (auto-approved, AI VP approved, approved by a reviewer, or a revision delta).
  - When on, two options appear: **Pay at end of day** (default **off**) with a configurable **time** (default 5:00 PM) and **timezone** (default America/Chicago, Central Time) used when it is turned on, and **Pay when the Invoice Queue is empty** (default **on**; today's idle trigger).
  - Saving requires a typed name (1 to 50 characters, the same rule as reviews), applies immediately with no restart, and is recorded in the audit log with old and new values.
- **Immediate payment mode.** With delay off, approval still adds a `payment_queue` row, and an `immediate` batch pays it right away (released by System). A row that arrives while another batch runs is paid right after it. Immediate mode is opt-in; the default keeps approved invoices in the queue.
- **Settings move from `.env` to the database.** A new `admin_settings` table holds the payment timing; spec defaults apply when it is empty. **BREAKING**: `PAYMENT_BATCH_TIME`, `PAYMENT_TZ`, and `PAYMENT_AUTO_IDLE` are removed. `PAYMENT_IDLE_DELAY_S`, `PAYMENT_MAX_ATTEMPTS`, and `PAYMENT_LOCK_TIMEOUT_S` stay in `.env`.
- **API.** `GET`/`PUT /api/admin/settings` (422 on a bad time, unknown timezone, or invalid name), a `settings.updated` SSE event, the scheduler rescheduling on save, and a payment-queue view that reports the current mode.
- **Payment Queue page** stays for failed rows and manual Pay all / Pay selected / Pay now in both modes. Its header shows the current mode and links to Admin.
- **CLI** honors the same settings: with delay off, each approved invoice is paid as it finishes. `--pay` and `payments run` still pay whatever is queued, and new `admin show` / `admin set` commands read and change the settings.
- **Defaults change behavior.** With the defaults (delay on, end of day off, pay when queue empty on) there is no daily 5:00 PM batch any more: approved invoices are paid when the Invoice Queue empties, or manually. **BREAKING** for anyone relying on the end-of-day batch: turn on Pay at end of day on the Admin page.
- **Golden tests.** The default configuration equals today's golden configuration, so the existing 20-row golden table runs with the defaults. A new golden variant runs with delay explicitly off (immediate mode): INV-1004 is paid $1,890.00, and its revision pays only the $4,050.00 delta.

Sequencing: this change modifies requirements that `reorder-sidebar-menu` and `require-llm-provider` also modify (sidebar navigation, golden outcomes, CLI payment commands, batch summary). Its MODIFIED blocks are written on top of those changes' text, so it must be applied and archived **after both of them**.

## Capabilities

### New Capabilities
- None. Admin settings belong to the existing payment, API, and web-app capabilities.

### Modified Capabilities
- `payment-processing`: payment timing settings and their defaults, immediate payment at approval, the `immediate` batch trigger and its scope and retries, end-of-day and idle decisions driven by the admin settings, and switching modes.
- `data-model`: the `admin_settings` table (twelve tables).
- `backend-api`: admin settings endpoints with validation and audit, the scheduler driven by and rescheduled from admin settings, payment-queue view mode fields, and the `settings.updated` event.
- `web-app`: Admin item in the sidebar, the Admin page and its form behavior, and the Payment Queue header showing the mode.
- `agent-workflow`: the golden table's payment-timing configuration and a golden variant with immediate payments.
- `cli`: immediate payment during processing, `--pay` / `payments run` / summary under each mode, and `admin show` / `admin set`.

## Impact

- **Backend:** `acme/payments` (new settings source, `immediate` trigger, immediate scope and retry, mode switch), `acme/graph/nodes.py` (disposition pays after queueing when delay is off), `acme/settings.py` (three settings removed), `acme/db` schema (new table), `acme/api` (admin router, scheduler reschedule, queries' "today" timezone, SSE event), `acme/cli.py` (admin subcommands).
- **Frontend:** sidebar (Admin item pinned at the bottom), a new `/admin` route and page, API client models, and the Payment Queue header.
- **Config and docs:** `.env.example`, README, `backend/README.md`, and the design spec (Payment batches, Admin page, Backend API, tables, F41, test plan).
- **Tests:** settings, payments, API, golden (two configurations), CLI, and frontend component and e2e tests.
