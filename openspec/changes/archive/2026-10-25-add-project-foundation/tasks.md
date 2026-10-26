# Tasks

## 1. Repository skeleton

- [x] 1.1 Create `backend/pyproject.toml` (package `acme` under `backend/src/`, deps: pydantic, pydantic-settings, langchain-core, langchain-xai, langchain-anthropic; dev: pytest) and verify `pip install -e backend[dev]` succeeds
- [x] 1.2 Create `backend/src/acme/__init__.py`, `backend/prompts/`, `backend/tests/`, `frontend/.gitkeep`, and a stub `acme/cli.py`; verify `python -c "import acme"` works
- [x] 1.3 Add repo-root `main.py` shim that puts `backend/src` on the path and calls `acme.cli.main()`; verify `python main.py --help` exits 0
- [x] 1.4 Add `.env.example` listing every setting with its default, and add `.env`, `acme.db`, and `uploads/` to `.gitignore`; verify `git status` doesn't show a local `.env`

## 2. Settings and domain models (data-model)

- [x] 2.1 Implement `acme/settings.py` (`Settings` with every setting in the design's settings catalog, including the EUR rate of 1.08; cached `get_settings()`) and verify with a unit test that `.env` values and all catalog defaults load
- [x] 2.2 Implement enums `FindingCode` (full catalog from the spec, with each code's canonical severity), `Severity`, `Outcome`, `FindingSource` in `acme/models.py`; verify a test that codes serialize verbatim and `CURRENCY_UNSUPPORTED` maps to WARNING
- [x] 2.3 Implement `LineItem`, `Invoice` (Decimal money, optional vendor/due date, `due_date_raw`, `original_currency`, `original_total`), `Finding`, `Decision`, `Critique`; verify tests for valid invoice, bad total, missing optional fields, and bad severity
- [x] 2.4 Implement `InvoiceState` and verify a JSON round-trip test passes

## 3. Database (data-model)

- [x] 3.1 Write `acme/db/schema.sql` with all eleven tables and their columns verbatim from the design spec, the unique index on `processed_invoices(vendor, invoice_number, revision)`, and UNIQUE `payments.idempotency_key`; verify a test that `init_schema()` on a temp file creates all tables
- [x] 3.2 Implement `connect()` (WAL, foreign keys, row factory) and idempotent `init_schema()`; verify running it twice keeps existing rows
- [x] 3.3 Implement `acme/db/seed.py` and `python -m acme.db seed` (inventory with reference prices, aliases "Widget A"/"Gadget X"/etc., the approved vendor list and FastShip aliases from the spec); verify tests for exact stock values, repeatable seed, the FastShip alias, absence of NoProd Industries/Fraudster LLC, and absence of SuperGizmo/MegaSprocket/WidgetC
- [x] 3.4 Verify the duplicate `idempotency_key` insert is rejected by a test

## 4. Audit logging (audit-logging)

- [x] 4.1 Implement `configure_logging()` with a JSON-lines formatter and context variables for `run_id` and agent; verify tests for run-scoped and run-less log lines and for injection-like text staying one valid JSON line
- [x] 4.2 Implement `audit(run_id, agent, event, payload)` writing `audit_log` with Decimal/date-safe JSON and a `read_trace(run_id)` helper; verify tests for recording, ordered replay, and Decimal/date payloads
- [x] 4.3 Implement the `llm_calls` recorder (LangChain callback handler capturing provider, model, prompt version, tokens, latency, retries, failure); verify a test using the offline model writes a row with provider `offline`

## 5. LLM provider (llm-provider)

- [x] 5.1 Implement `RuleBasedLLM` (deterministic `with_structured_output` dispatching to registered per-schema handlers; `bind_tools` returning a fixed plan then a final message); verify determinism and tool-plan tests
- [x] 5.2 Implement `get_chat_model(role)` with provider resolution (run override → `LLM_PROVIDER`), `ChatXAI`/`ChatAnthropic` construction with temperature, timeout, retries, and the call-recorder callback; verify tests for default, claude, override, and invalid provider (real SDK classes checked by type only, no network)
- [x] 5.3 Implement `check_keys()` and call it at CLI startup; verify tests for missing `XAI_API_KEY` and for offline with no keys
- [x] 5.4 Implement `active_models()` reporting provider and model per role; verify a test with `CLAUDE_MODEL=claude-opus-5-5`
- [x] 5.5 Verify the retry behavior with a test double that returns 429 twice and then succeeds, and one that always fails with 5xx
- [x] 5.6 Document the provider settings and offline mode in a short `backend/README.md` section and verify the documented `python -m acme.db seed` and `LLM_PROVIDER=offline python main.py --help` commands run as written

## 6. P1: Cross-model critique settings (F37)

- [x] 6.1 Add `LLM_PROVIDER_EXTRACTION`, `_VALIDATION`, `_APPROVAL`, `_CRITIC` to settings and the role resolution order; verify a test that `LLM_PROVIDER_CRITIC=claude` gives Claude only to the critic role
- [x] 6.2 Extend `check_keys()` to every provider in use; verify a test that a critic override without `ANTHROPIC_API_KEY` stops startup

## 7. Integration check

- [x] 7.1 Run `pytest backend/tests` offline with no API keys set and verify all tests pass
