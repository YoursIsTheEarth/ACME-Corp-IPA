# Design

## Context

The repo is greenfield: only the case README, `data/invoices/` (20 files), `data/generate_pdfs.py`, and the design spec ("Acme Invoice Agents — Design & Feature Spec.md"). See proposal.md for motivation. The case README requires `python main.py --invoice_path=...` at the repo root and assumes no internet, so the foundation has to run fully offline. Requirements are in `specs/data-model`, `specs/llm-provider`, and `specs/audit-logging`.

## Goals / Non-Goals

**Goals:**
- One importable package (`acme`) that every later change extends, with a single place for models, settings, DB access, LLM access, and logging.
- Offline mode that is a true drop-in for real providers, so the golden suite runs without keys.

**Non-Goals:**
- Any agent logic, parsers, rules, payment execution, CLI subcommands, API, or UI (owned by later changes).
- Database migrations tooling; the prototype recreates or extends the schema idempotently.

## Decisions

**Layout: `backend/src/acme/` with a root `main.py` shim.** Matches the spec's `backend/` + `frontend/` split while keeping the README command working. `main.py` adds `backend/src` to `sys.path` and calls `acme.cli.main()`; until `add-agent-workflow` lands, `acme.cli.main` is a stub that prints usage. Alternative: putting the package at the repo root, which would conflict with `frontend/` and the spec's build order.

Modules:
- `acme/models.py`: Pydantic v2 models and enums (`FindingCode`, `Severity`, `Outcome`, `FindingSource`).
- `acme/settings.py`: `Settings(BaseSettings)` loaded from `.env`, cached via `get_settings()`.
- `acme/db/__init__.py` (`connect()`, `init_schema()`), `acme/db/schema.sql`, `acme/db/seed.py`, `acme/db/__main__.py` (`python -m acme.db seed`).
- `acme/llm/factory.py` (`get_chat_model(role)`, `active_models()`, `check_keys()`), `acme/llm/offline.py` (`RuleBasedLLM`), `acme/llm/callbacks.py` (call recorder).
- `acme/logging/` (`configure_logging()`, `audit(run_id, agent, event, payload)`).

**Money as `Decimal`.** Avoids float rounding in the $0.01 math checks and the 1-cent adversarial test. Serialized as strings in JSON; stored as TEXT in SQLite. Alternative: integer cents, which is safer but makes the extracted models awkward for the LLM to fill.

**All tables in one `schema.sql` now.** The spec lists every table up front; creating them all here (with `CREATE TABLE IF NOT EXISTS`) means later changes only add queries, and two changes never race to alter the same table. Columns follow the design spec verbatim. `processed_invoices` gets a unique index on (`vendor`, `invoice_number`, `revision`); `payments.idempotency_key` is UNIQUE. Connections enable WAL and `foreign_keys`, since the API worker and scheduler will share the file.

**Seed is upsert-based.** `INSERT ... ON CONFLICT DO UPDATE` for inventory, aliases, and vendors, so re-running seed restores reference data without touching run tables. Reference prices (250/500/750) are an assumption inferred from the clean invoices, as the design spec states. Vendor seed rows are every vendor named on the sample invoices except NoProd Industries (INV-1008) and Fraudster LLC (INV-1003), so that `UNKNOWN_VENDOR` fires only on the golden file that expects it and INV-1005's only fraud signal is its address. QuickShip Distributers carries the aliases "QuickShip Distributers (formerly FastShip Ltd.)" and "FastShip Ltd." for INV-1012.

**LLM factory over LangChain chat models.** `get_chat_model(role)` resolves provider as: run override → `LLM_PROVIDER_<ROLE>` (P1) → `LLM_PROVIDER`. It returns `ChatXAI`, `ChatAnthropic`, or `RuleBasedLLM`, configured with temperature, timeout, `max_retries`, and a callback handler that writes `llm_calls`. Agents depend only on `bind_tools` and `with_structured_output`. The run override is passed through a context variable set by the CLI and the worker, so agents never thread it through. Alternative: a home-grown provider interface. Rejected because LangGraph's `ToolNode` and structured output already speak LangChain's interface.

**`RuleBasedLLM` is a `BaseChatModel` subclass.** It implements `with_structured_output(schema)` by dispatching to registered handlers per schema (`Invoice`, `Decision`, `Critique`), and `bind_tools` by returning a model that emits a fixed tool-call plan and then stops. Handlers are registered by later changes (ingestion registers regex extraction, approval registers template rationales). That keeps this change free of invoice-specific logic. It is deterministic: no randomness, no clock reads.

**Logging via stdlib `logging` with a JSON formatter.** `run_id` and agent come from context variables, so nested calls inherit them. Alternative: `structlog`, which is nicer but one more dependency for little gain.

**One settings catalog for every change.** `Settings` declares every setting any change reads, so later changes only consume them:

| Group | Setting | Default | Read by |
| --- | --- | --- | --- |
| LLM | `LLM_PROVIDER`, `GROK_MODEL`, `CLAUDE_MODEL`, `LLM_TEMPERATURE`, `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES`, `XAI_API_KEY`, `ANTHROPIC_API_KEY` | `grok`, Grok 4 name, `claude-sonnet-5-5`, 0, 30, 3, unset, unset | llm-provider |
| LLM (P1) | `LLM_PROVIDER_EXTRACTION`, `_VALIDATION`, `_APPROVAL`, `_CRITIC` | unset | llm-provider |
| FX | `FX_RATES` | `{"EUR": "1.08"}` (USD per unit) | invoice-normalization |
| Validation | `PRICE_VARIANCE_PCT`, `NEAR_THRESHOLD_FLOOR_USD`, `SUSPICIOUS_ADDRESSES`, `FRAUD_SIGNAL_WEIGHTS`, `FRAUD_THRESHOLD` | 10, 9500.00, ["1600 Pennsylvania Ave"], weights from add-validation-and-approval design D5, 0.60 | invoice-validation |
| Approval | `VP_REVIEW_THRESHOLD_USD`, `CRITIC_MAX_ROUNDS`, `EXTRACTION_MAX_RETRIES`, `VALIDATION_MAX_TOOL_ROUNDS` | 10000.00, 2, 2, 8 | invoice-approval, invoice-ingestion, invoice-validation |
| Payments | `PAYMENT_BATCH_TIME`, `PAYMENT_TZ`, `PAYMENT_IDLE_DELAY_S`, `PAYMENT_AUTO_IDLE`, `PAYMENT_MAX_ATTEMPTS`, `PAYMENT_LOCK_TIMEOUT_S` | `17:00`, `America/Chicago`, 60, true, 3, 30 | payment-processing, backend-api |
| API | `API_CORS_ORIGIN`, `UPLOAD_DIR`, `UPLOAD_MAX_BYTES`, `ALLOWED_UPLOAD_EXTENSIONS`, `WORKER_CONCURRENCY` | `http://localhost:4200`, `uploads/`, 10485760, `.pdf,.txt,.csv,.json,.xml,.eml`, 1 | backend-api |

The `FX_RATES` EUR default must stay between 1.00 and 1.158: INV-1014 bills WidgetA at EUR 225 and WidgetB at EUR 475, and outside that band one of them converts to more than 10% off its USD reference price and raises `PRICE_VARIANCE`, turning a golden PAID into a hold. At 1.08 the golden payment batch totals $37,620.00 (INV-1014 converts to $4,455.00).

**Model names are settings, not code.** `GROK_MODEL` defaults to a current Grok 4 model name and `CLAUDE_MODEL` to `claude-sonnet-5-5`. Both must be confirmed against the providers' model pages before submission.

## Risks / Trade-offs

- [`langchain-xai` or `langchain-anthropic` API drift] → Pin versions in `pyproject.toml`; the offline path doesn't import either SDK until a real provider is selected.
- [Offline model diverges from real-model behavior] → It is held to the same structured-output schemas; recorded fixtures (F34, P2, owned by `add-agent-workflow`) cover the real paths.
- [SQLite contention between API worker and scheduler] → WAL mode and short transactions; the payment executor's own lock is owned by `add-payment-processing`.
- [Creating all tables before their features exist] → Accepts a few unused tables early in exchange for one schema file and no cross-change migrations.

## Open Questions

- The exact Grok 4 model identifier for `GROK_MODEL`'s default; confirm in the xAI console before submission (does not affect the design).

## Implementation notes

- **Python 3.14 / pins.** Installed and pinned: pydantic ~=2.14, pydantic-settings ~=2.16, langchain-core ~=1.7, langchain-xai ~=1.3, langchain-anthropic ~=1.7, pytest ~=9.1. All support 3.14.
- **`DB_PATH` setting added** (default `acme.db`, relative to the working directory) so tests and tools can point at a temp database. Not in the catalog above.
- **`GROK_MODEL` default is `grok-4`** (still to be confirmed in the xAI console).
- **`Invoice.revision` is an int** (0 = original); the validator accepts source labels like `"R1"` → 1. `processed_invoices.revision` and `payment_queue.revision` are INTEGER to match.
- **Extra columns beyond the design spec's lists.** Surrogate `id` primary keys where the spec names none; `llm_calls` adds `provider`, `retries`, `failed`, `error`, `ts` (required by the audit-logging spec); `payments` adds `batch_id`, `payment_id` (required by the payment-processing spec). `vendors.aliases` is a JSON array. No foreign keys except `item_aliases.sku → inventory.item`, so later changes can write rows in any order.
- **Retries are ours, not the SDKs'.** Real models are built with SDK `max_retries=0` and wrapped by `RetryingChatMixin` (`acme/llm/retry.py`), which retries 429/5xx with backoff 0.5s·2ⁿ (cap 8s) and exposes the count to the `llm_calls` recorder (`response_metadata["retries"]`, or `exc.acme_retries` on failure). `disable_streaming=True` keeps every call on that path. Only the sync path (`invoke`) retries; async calls are not wrapped.
- **Offline registries.** `register_handler(schema, fn)` (fn gets the message list and returns the schema instance or a dict) and `register_tool_plan(fn)` (fn gets messages and bound tool names, returns `[{"name", "args"}]`; the default calls each tool once with `{}`). Structured output is round-tripped through JSON so it is validated like a real provider's.
- **Prompt version** is passed as invocation metadata: `config={"metadata": {"prompt_version": "extraction.v1"}}`. The `llm_calls.agent` is the current `agent_context`/`run_context` agent, else the role.
