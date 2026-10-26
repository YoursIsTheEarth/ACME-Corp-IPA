# Proposal

## Why

Offline mode lets the whole pipeline run on a rule-based stand-in, so the system can look agentic without any model doing the reading or reasoning. The clearest example is the address check: `SUSPICIOUS_ADDRESS` fires only because "1600 Pennsylvania Ave" is in a hardcoded `SUSPICIOUS_ADDRESSES` list, so any other implausible address passes. The user has decided that the app must run on a real LLM, and that the LLM, not a list, judges whether a vendor address is plausible for a supplier.

## What Changes

- **BREAKING** Remove offline mode. `LLM_PROVIDER` accepts only `grok` (default) or `claude`, and `--provider offline` is rejected as an invalid value. The rule-based model leaves the application code.
- **BREAKING** A missing API key no longer has a fallback:
  - **CLI:** invoice processing (`--invoice_path`, `--batch`) exits non-zero before any run starts. The message says no LLM token is provided, names the variable to set (`XAI_API_KEY` or `ANTHROPIC_API_KEY`), and says invoices cannot be processed without it. Commands that make no LLM call (`--explain`, `review`, `payments run`) still work.
  - **API:** the server still starts so the UI loads. `/api/stats` reports that no key is configured, and invoice uploads are refused with 503 and a descriptive body. Runs already waiting to be processed stay Uploaded and are not processed until a key is set.
  - **Web app:** it still loads and shows a persistent error banner: "No LLM token provided — the app cannot process invoices without it", naming the variable. The Home drop zone and Browse button are disabled with that explanation. The sidebar footer shows Grok or Claude only.
- **BREAKING** Remove the `SUSPICIOUS_ADDRESSES` setting and the list match. The Validation stage asks the LLM, through a dedicated structured-output call that runs for every invoice with a vendor address, whether the address is plausible for a business supplier. An implausible verdict raises WARNING `SUSPICIOUS_ADDRESS` with `source` = `llm` and the model's reasoning as evidence. That finding still counts as the `suspicious_address` fraud signal. INV-1005 (1600 Pennsylvania Ave, Washington, DC 20500) must be flagged.
- Tests never call a paid API. The rule-based model becomes a test-only fake chat model, injected by fixtures and not selectable through settings or the CLI. It scripts the address verdicts the golden suite needs. The golden table is unchanged; INV-1005 still shows `STOCK_EXCEEDED` and `SUSPICIOUS_ADDRESS`.
- The run scripts and docs drop the offline fallback: `run.sh`, `Makefile`, `docker-compose.yml`, `.env.example`, `README.md`, `backend/README.md`, `frontend/README.md`, and the e2e backend script. `run.sh` still starts both servers without a key, so the banner can be seen, but prints a clear warning.
- The source design doc ("Acme Invoice Agents — Design & Feature Spec.md") is updated to match.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `llm-provider`:
  - provider values are `grok` and `claude` only
  - the key check becomes a reported key status that processing entry points enforce
  - the offline rule-based model is removed
  - adds a test-only fake model
- `invoice-validation`: the suspicious address signal becomes an LLM plausibility assessment, and the fraud score uses that verdict.
- `invoice-ingestion`: extraction parity covers `grok` and `claude` only.
- `invoice-approval`: rationales always come from the configured LLM (no offline template).
- `audit-logging`: the LLM call ledger loses the offline scenario.
- `agent-workflow`: the golden suite runs with the test fake model instead of offline mode.
- `cli`:
  - `--provider` accepts `grok` or `claude` only
  - processing commands refuse without a key, with a descriptive message
  - examples drop `--provider offline`
- `backend-api`:
  - the server starts without a key
  - `/api/stats` reports key status
  - uploads are refused with 503 while no key is set
  - API parity is stated without offline mode
- `web-app`:
  - adds the missing-key banner and disabled upload
  - the footer lists Grok or Claude only
  - setup and e2e test wording drop offline mode

## Impact

- **Backend code:**
  - `acme/llm/` (factory, `offline.py` removed, `__init__` exports)
  - `acme/settings.py` (`suspicious_addresses` removed, provider validation)
  - `acme/validation/` (checks, agent, a new address assessment and prompt `prompts/address_v1.md`)
  - offline handler modules: `acme/ingestion/offline.py`, `acme/approval/offline.py`, `acme/normalization/llm_fallback.py` registrations, `acme/validation/agent.py` tool plan
  - `acme/cli.py`, and `acme/api/` (app lifespan, uploads router, stats, worker start)
- **Tests:** `backend/tests/conftest.py` and every suite's conftest. `fakes.py` gains the fake model. Most suites currently set `LLM_PROVIDER=offline`.
- **Frontend:** the shell (banner, footer labels), the Home drop zone, API models, tests, and `e2e/start-backend.sh`, which must start a backend with the test fake.
- **Operations:**
  - A reviewer needs an `XAI_API_KEY` or `ANTHROPIC_API_KEY` and network access to `api.x.ai` or `api.anthropic.com` to see invoices processed.
  - This departs from the case README's "assume no internet … simulate everything locally" (see design.md).
- **Settings:** an existing `.env` with `LLM_PROVIDER=offline` now fails at startup with an error naming the valid values.
