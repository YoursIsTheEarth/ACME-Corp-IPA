## MODIFIED Requirements

### Requirement: Active LLM provider in footer (F21)
The sidebar footer SHALL show the active LLM provider (Grok or Claude) and model name from the `llm` field of `/api/stats`.

#### Scenario: Provider shown
- **WHEN** the backend runs with `LLM_PROVIDER=claude` and `CLAUDE_MODEL=claude-sonnet-5-5`
- **THEN** the sidebar footer reads Claude and claude-sonnet-5-5

### Requirement: One-command local setup (P1, F33)
From a fresh clone, `make setup` SHALL install backend and frontend dependencies and seed `acme.db`, and `make dev` SHALL start the FastAPI backend and the Angular dev server together so the app is usable in a browser. Without an LLM key both servers SHALL still start, and the startup output SHALL warn that invoices cannot be processed until a key is set.

#### Scenario: Fresh clone
- **WHEN** a developer with Python and Node installed and an LLM key in `.env` runs `make setup && make dev`
- **THEN** both servers start, and opening the Angular dev server URL shows the Home page with the sidebar footer showing the active provider

#### Scenario: Fresh clone without a key
- **WHEN** a developer runs `make dev` (or `run.sh`) with no LLM key set
- **THEN** both servers start, the terminal prints a warning naming the variable to set, and the Home page shows the missing-key banner

#### Scenario: Stopping dev
- **WHEN** the developer stops `make dev` with Ctrl+C
- **THEN** both the backend and the frontend dev servers stop

### Requirement: Frontend tests (P1, F32)
The frontend SHALL have:
- component tests for the drop zone, the review dialog, the pay dialog, and the missing-key banner
- one end-to-end run that uploads 3 files, reviews one held invoice, clicks Pay all, and finds the paid invoices in Payments

#### Scenario: End-to-end happy path
- **WHEN** the end-to-end test runs against a backend started by the test harness with the test-only fake model
- **THEN** it uploads 3 files including invoice_1010.txt, approves INV-1010 in Elevated Review, pays all from the Payment Queue, and sees them in Payments

## ADDED Requirements

### Requirement: Missing LLM key banner
While `/api/stats` reports `llm.configured` false, every page SHALL show a persistent, prominent error banner reading "No LLM token provided — the app cannot process invoices without it". The banner names the variable from `llm.missing_key` and says to set it in `.env` and restart the backend. The Home drop zone and Browse button SHALL be disabled with the same explanation. Pages that need no LLM (the lists, review decisions, payment actions) SHALL stay usable.

#### Scenario: App loads without a key
- **WHEN** the backend runs with no `XAI_API_KEY` and `LLM_PROVIDER=grok`
- **THEN** the app loads, the banner reads "No LLM token provided — the app cannot process invoices without it" and names `XAI_API_KEY`
- **AND** the drop zone and Browse button are disabled

#### Scenario: Refused upload explained
- **WHEN** an upload reaches the API while no key is configured and the API answers 503
- **THEN** the upload row shows the API's message naming the missing variable

#### Scenario: Other pages stay usable
- **WHEN** no key is configured and a reviewer approves a held invoice, then clicks Pay all
- **THEN** both actions succeed while the banner stays visible

#### Scenario: Key added
- **WHEN** the backend restarts with a key and the next stats poll reports `llm.configured` true
- **THEN** the banner disappears and the drop zone is enabled without a page reload
