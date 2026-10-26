# Tasks

Prerequisite: the `backend-api` endpoints from `add-backend-api` are available, or stubbed with the same DTOs, for local development. Groups 1 to 9 are P0 - MVP. Groups 10 and 11 are P1 / P2 and start only after P0 passes.

## 1. Workspace scaffold (F21)

- [x] 1.1 Create `frontend/` with Angular CLI 18 (standalone, routing, SCSS, strict). Verify `npm --prefix frontend run build` succeeds.
- [x] 1.2 Add Angular Material 18 with a custom theme, plus `proxy.conf.json` mapping `/api` to the backend port. Verify `ng serve` proxies `GET /api/stats` to the backend.
- [x] 1.3 Add typed DTOs and an `ApiClient` covering every `backend-api` endpoint the app uses. Verify with a unit test using `HttpTestingController` that each method hits the right method and path.

## 2. Live data layer

- [x] 2.1 Implement the `LiveStore` pattern: `refresh$` plus a shared 3-second poll tick that pauses while `document.hidden`. Add stores for queue, review, audit, payment queue, payments, payment batches, and stats. Verify with a fakeAsync unit test that rows refetch every 3 s and stop while hidden.
- [x] 2.2 Implement `ToastService` over `MatSnackBar`. Verify with a unit test that it shows the message text.

## 3. App shell and sidebar (F21)

- [x] 3.1 Build the shell: sidenav with the "ACME Corp IPA" name and tagline, the six lazy routes in the specified order, and active-item highlight. Verify that navigating to each route by URL highlights the right item.
- [x] 3.2 Add count badges for Invoice Queue, Invoice Elevated Review, and Payment Queue from the stats store, hidden at zero. Verify with a component test that the badges render the counts and hide at 0.
- [x] 3.3 Add the responsive behavior: side mode at 960 px and wider; over mode with icons only below, closing after navigation. Verify with a component test that drives `BreakpointObserver` at 800 px and 1200 px.
- [x] 3.4 Show the active provider and model in the footer (from `llm.provider` and `llm.model` in `/api/stats`). Verify the footer reads the values from a stubbed stats response.

## 4. Shared table, status chips, and name field

- [x] 4.1 Build `InvoiceTableComponent` with column defs, sort, client-side search, paginator, `rowClick` output, an expandable-row slot, and an optional selection column. Verify with component tests for sort, search filtering with recount, and pagination.
- [x] 4.2 Add the `STATUS_STYLE` map and a status chip component covering every status in the spec (Processing, Retrying extraction, Awaiting review, Queued, Paying, Failed, Paid, Rejected, Duplicate, Superseded, Credit confirmed). Verify with a unit test that every status has exactly one style.
- [x] 4.3 Build `ReviewerNameFieldComponent` with trim plus a 1 to 50 validator, a characters-left counter, and localStorage prefill in try/catch. Verify with unit tests for spaces-only, 51 characters, 50 characters with padding, prefill, and throwing storage.

## 5. Home page and upload (F22)

- [x] 5.1 Add the welcome header and the drop zone with hover highlight, and a Browse button with a multi-select `accept` list (.pdf, .txt, .csv, .json, .xml, .eml). Verify by dragging files in the running app.
- [x] 5.2 Implement `UploadService`: client-side refusal of wrong type, over 10 MB, and empty files; one POST per file with progress, at most 3 concurrently; per-row Queued or backend error. Verify with unit tests over a mixed batch, including a server-side 4xx.
- [x] 5.3 Show the accepted-count toast and the "View in Invoice Queue" link after the uploads finish. Verify manually by uploading 3 golden files and following the link.

## 6. Invoice Queue and Resolution Audit (F23, F24)

- [x] 6.1 Build the Invoice Queue page with all spec columns: the "Extracting..." placeholder, a 5-step stage strip component, and time-in-stage. Verify that uploading `data/invoices/invoice_1001.txt` shows the stages advancing within 3 s per change and the row leaving when resolved.
- [x] 6.2 Build the Audit page: all spec columns, up to 3 finding chips with a "+N" indicator, and status and date filters. Verify that after the golden batch, INV-1004 shows Superseded and INV-1009 shows 3 chips and +1.
- [x] 6.3 Add the expandable rationale timeline (extraction, validation with evidence, rules fired, each AI VP draft and Critic response with provider and model, reviewer note, payment or rejection record). Verify that expanding INV-1010 after review shows each stage entry.

## 7. Invoice Elevated Review and review dialog (F25)

- [x] 7.1 Build the Elevated Review page with spec columns and Approve, Reject, and View details actions. Verify that INV-1010 is listed with a Price variance reason and the AI recommendation.
- [x] 7.2 Build `ReviewDecisionDialog` (summary, findings, AI recommendation, name field, rationale of at least 15 characters) that sends `POST /api/invoices/{id}/review`. On success, close it, refresh the review and queue stores and badges, and toast. Verify that approving INV-1010 moves it to the Payment Queue.
- [x] 7.3 Handle a 409 with an "already decided" message and refresh. Verify with a component test using a stubbed 409.
- [x] 7.4 Add the credit-hold variant: an overpaid amount in the row, Credit confirmed and Reject revision actions, and a rationale hint that asks for the credit note or refund and the amount. Verify with a component test that the labels change and no payment-queue refresh claims a new row.

## 8. Payment Queue (F40)

- [x] 8.1 Build the Payment Queue page: a header (count, total, next batch time, auto-pay-on-idle state) and a table with a selection column, Type, Approved by, Queued at, Status with the Failed error, and Pay now. Verify against `/api/payment-queue` after the golden batch run without `--pay`.
- [x] 8.2 Build `PayConfirmDialog` (row count, total, name field) for Pay all, Pay selected (disabled with no selection), and Pay now, which sends `POST /api/payment-queue/execute`. Handle a 409 with a "batch already running" message. Verify with a component test of the all, selected, and one scopes and the 409.
- [x] 8.3 During a batch, show Paying and disable the controls. On finish, toast "Batch <id>: N paid, $X, F failed" and refresh. Verify that paying all after the golden run toasts 7 paid, $37,620 and the rows move to Payments.
- [x] 8.4 Show the revision-swap toast when a `replacement` row appears and its original's row disappears. Verify by uploading `invoice_1004.json` and then `invoice_1004_revised.json` within the idle delay: the INV-1004 row is replaced by R1 at $5,940.00 with a toast.

## 9. Payments page (F26)

- [x] 9.1 Build the Payments page with all spec columns: original currency, "Delta for R1" display, batch ID and trigger, Released by (System or a name), and a link to the audit entry. Verify that INV-1014 shows EUR 4,125.00 as the original.
- [x] 9.2 Add date and vendor filters and a footer total over the filtered rows. Verify with a component test that the footer sums only the filtered rows.
- [x] 9.3 P0 integration check: with `make`-less manual startup (uvicorn plus `ng serve`, offline provider, fresh seed), upload all 20 golden files, approve INV-1010, and Pay all. Verify that every page shows the outcomes from the spec's test plan.

## 10. P1 - Should

- [x] 10.1 F29: build `EventStreamService` on `/api/events` that maps each event type to the stores it invalidates, suspends polling while connected, and falls back to polling with backoff reconnect. Verify with a unit test using a fake `EventSource` for connect, event, error→poll, and reconnect.
- [x] 10.2 F29: use `batch.finished` and `payment.cancelled`/`payment.queued` events for the batch and swap toasts. Verify that the toasts fire without waiting for a poll tick.
- [x] 10.3 F30: build the detail drawer from `?invoice=<id>`, with text preview for TXT/CSV/JSON/XML/EML, a PDF viewer through `<object>` with a download fallback, extracted fields, findings, and timeline, opened by every table's `rowClick`. Verify that it opens from each page and that the back button closes it.
- [x] 10.4 F31: add Home tiles for In queue, Awaiting review, Paid today, and Rejected today from stats. Verify that the tiles match `/api/stats` after the golden run.
- [x] 10.5 F32: add component tests for the drop zone, `ReviewDecisionDialog`, and `PayConfirmDialog` if they aren't already covered above. Verify that `npm --prefix frontend test -- --watch=false` passes.
- [x] 10.6 F32: add a Playwright e2e in `frontend/e2e/` that uploads invoice_1001.txt, invoice_1006.csv, and invoice_1010.txt, approves INV-1010, clicks Pay all, and asserts all three appear in Payments. Verify that `npx playwright test` passes against offline mode with a fresh seed.
- [x] 10.7 F33: add a repo-root `Makefile` where `setup` installs backend and frontend dependencies and seeds `acme.db`, and `dev` runs uvicorn and `ng serve` together, both stopping on Ctrl+C. Document this in the README. Verify on a fresh clone that `make setup && make dev` serves the Home page.
- [x] 10.8 F33 (optional): add `docker-compose.yml` with backend and frontend services. Verify that `docker compose up` serves the Home page.

## 11. P2 - Stretch

- [x] 11.1 F35: add Export CSV buttons on the Audit and Payments pages that link to `/api/invoices.csv` and `/api/payments.csv` with the current filter params. Verify that exporting the Audit filtered to Rejected yields only Rejected rows.
