## MODIFIED Requirements

### Requirement: Same pipeline as the CLI (F27)
Every accepted upload SHALL be processed in the background through the same agent workflow the CLI uses. The same file under the same provider SHALL reach the same outcome, findings, and amounts as `python main.py --invoice_path=<file>`. The upload request SHALL NOT wait for processing to finish.

#### Scenario: Parity with the CLI
- **WHEN** `invoice_1002.txt` is uploaded through the API and processed with the same model as a CLI run of that file
- **THEN** its run ends Rejected with finding `STOCK_EXCEEDED`, the same as the CLI result for that file

#### Scenario: Stage progression is visible
- **WHEN** an uploaded invoice is being processed
- **THEN** successive reads of the queue view show its stage advancing through Uploaded, Extracting, Validating, and Deciding

### Requirement: Stats for tiles and badges (F21, F31)
`GET /api/stats` SHALL return:
- counts for invoices in the queue, awaiting review, and in the payment queue, plus paid today and rejected today
- an `llm` object with the active provider and model per agent role (from `llm-provider`'s active-model report), for the sidebar footer
- the LLM key status, as `llm.configured` (true or false) and `llm.missing_key` (the environment variable name, or null)

P1: it SHALL also return dollars queued, dollars paid, dollars blocked, and duplicates caught.

#### Scenario: Badge counts
- **WHEN** 3 invoices are processing, 1 is awaiting review, and 2 payments are queued
- **THEN** `/api/stats` returns an in-queue count of 4, an awaiting-review count of 1, and a payment-queue count of 2

#### Scenario: Active model reported
- **WHEN** the server runs with `LLM_PROVIDER=claude`, `CLAUDE_MODEL=claude-sonnet-5-5`, and `ANTHROPIC_API_KEY` set
- **THEN** `/api/stats` returns `llm.provider` `claude`, `llm.model` `claude-sonnet-5-5`, `llm.configured` true, and `llm.missing_key` null

#### Scenario: Missing key reported
- **WHEN** the server runs with `LLM_PROVIDER=grok` and no `XAI_API_KEY`
- **THEN** `/api/stats` returns `llm.configured` false and `llm.missing_key` `XAI_API_KEY`

## ADDED Requirements

### Requirement: Server starts without an LLM key
The API server SHALL start when the selected provider's key is missing, so the web app can load and explain the problem. While the key is missing, read views, reviews of held invoices, and payment execution SHALL keep working, because they make no LLM call. An invalid `LLM_PROVIDER` value SHALL still stop startup.

#### Scenario: Startup without a key
- **WHEN** the server starts with `LLM_PROVIDER=grok` and no `XAI_API_KEY`
- **THEN** it starts and serves `/api/stats` and the list views

#### Scenario: Payments still work
- **WHEN** no key is configured and a person posts to `/api/payment-queue/execute` with rows queued
- **THEN** the response is 202 and the batch pays the queued rows

### Requirement: Processing refused without an LLM key
While a needed key is missing, `POST /api/invoices` SHALL return 503 without storing any file or creating a run. The body SHALL be `{"detail": {"code": "llm_not_configured", "message": ..., "missing_key": ...}}`, with a message stating that no LLM token is provided, naming the variable, and saying invoices cannot be processed without it. The background worker SHALL NOT process runs; runs that are Uploaded or orphaned mid-processing SHALL wait until the server restarts with a key.

#### Scenario: Upload refused
- **WHEN** a client posts `invoice_1001.txt` to `/api/invoices` while no key is configured
- **THEN** the response is 503 with `code` `llm_not_configured`, a message naming `XAI_API_KEY`, and `missing_key` `XAI_API_KEY`
- **AND** no file is stored and no invoice run is created

#### Scenario: Pending runs wait for a key
- **WHEN** the server restarts without a key while a run is in status Uploaded
- **THEN** the run stays Uploaded and is not processed
- **AND** after a restart with a key configured, it is processed
