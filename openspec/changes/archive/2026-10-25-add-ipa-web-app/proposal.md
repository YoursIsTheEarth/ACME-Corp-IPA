# Proposal

## Why

The case grades UI/UX: reviewers must understand and enjoy using the system. Today, decisions on held invoices and payment releases would only be possible through the CLI. ACME Corp IPA gives AP staff and VPs one browser app to upload invoices, watch them move through the pipeline, decide held ones, release payments, and see why every invoice ended the way it did.

## What Changes

- New Angular 18 single-page app in `frontend/` (standalone components, Angular Material, RxJS), titled **ACME Corp IPA**, talking only to the FastAPI backend (`backend-api`).
- **P0 - MVP**
  - F21 App shell: persistent left sidebar (Home, Invoice Queue, Invoice Resolution Audit, Invoice Elevated Review, Payment Queue, Payments), active-page highlight, live count badges on Invoice Queue, Elevated Review, and Payment Queue, collapse to icons with overlay below 960 px, footer showing the active LLM provider and model.
  - F22 Home page: welcome header, multi-file drop zone and Browse picker (.pdf, .txt, .csv, .json, .xml, .eml), client-side refusal of wrong type, over 10 MB, and empty files, per-file progress then Queued or an error, toast with accepted count, "View in Invoice Queue" link.
  - F23 Invoice Queue page with the 5-step stage strip and status.
  - F24 Invoice Resolution Audit page with expandable rationale timeline per stage.
  - F25 Invoice Elevated Review page and decision dialog (typed reviewer name of 1 to 50 characters after trimming, remembered in the browser; rationale of at least 15 characters; credit-or-refund variant with Credit confirmed / Reject revision; 409 stale-decision handling).
  - F40 Payment Queue page: header totals, next batch time, auto-pay-on-idle state, Pay all / Pay selected / Pay now through a confirm dialog with the same typed name field; Paying state and batch-summary toasts.
  - F26 Payments page with batch, trigger, released by, idempotency key, and a filtered total footer.
  - One shared Angular Material table component (sort, search, pagination, status chip, row click) used by all tables.
  - Live data by polling every 3 seconds.
- **P1 - Should**
  - F29 (frontend half) Server-Sent Events subscription replacing polling, with polling kept as the fallback.
  - F30 Invoice detail drawer: original file preview beside extracted fields, findings, and full stage timeline.
  - F31 (frontend half) Home summary tiles: in queue, awaiting review, paid today, rejected today.
  - F32 Frontend tests: component tests for the drop zone, review dialog, and pay dialog, plus one Playwright end-to-end run.
  - F33 One-command setup: `make setup && make dev` installs both apps, seeds the DB, and starts FastAPI and the Angular dev server; optional `docker compose up`.
- **P2 - Stretch**
  - F35 (frontend half) Export-to-CSV buttons on the Audit and Payments pages for the current filter.

## Capabilities

### New Capabilities

- `web-app`: The ACME Corp IPA browser application: shell and navigation, the six pages, the review and pay dialogs, the shared table, the detail drawer, live-update behavior, frontend tests, and local dev setup.

### Modified Capabilities

None. The app consumes `backend-api` (from `add-backend-api`) and does not change its requirements.

## Impact

- New `frontend/` Angular workspace (package.json, angular.json, Material theme, Playwright config).
- New repo-root `Makefile` (and optional `docker-compose.yml`) for F33, which also invokes the seed command from `data-model`.
- Depends on every endpoint in `backend-api`: `/api/invoices` (upload and the `queue`, `audit`, `review` views), `/api/invoices/{id}`, `/api/invoices/{id}/file`, `/api/invoices/{id}/review`, `/api/payment-queue`, `/api/payment-queue/execute`, `/api/payment-batches`, `/api/payments`, `/api/stats`, `/api/events`, and the CSV exports. It also needs an endpoint or a `/api/stats` field that reports the active provider and model (see the open question in design.md).
- New dev dependencies: Node 20 LTS, Angular CLI 18, Angular Material 18, Playwright.
- No authentication, matching the spec's non-goals: reviewer and releaser names are typed by hand.
