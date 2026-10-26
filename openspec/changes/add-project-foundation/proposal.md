# Proposal

## Why

Every later stage of Acme Invoice Agents (ingestion, validation, approval, payment, CLI, API, web app) needs the same shared models, the same `acme.db` file, one way to get an LLM, and one audit trail. Building those first, and making them work offline, lets each later change be tested in isolation and keeps "the LLM reads and reasons; deterministic code decides about money" enforceable from day one.

## What Changes

- Create the repository skeleton: Python package at `backend/src/acme/` (with `backend/pyproject.toml`), `backend/prompts/`, `backend/tests/`, an empty `frontend/` placeholder, and a repo-root `main.py` shim that delegates to `acme.cli`, so `python main.py --invoice_path=...` works as the case README requires.
- Add the shared Pydantic models: `LineItem`, `Invoice`, `Finding`, `Decision`, `Critique`, `InvoiceState`, plus the enums for finding codes, severities, outcomes, and statuses used across the spec.
- Add the `acme.db` SQLite schema for every table in the design spec (`inventory`, `item_aliases`, `vendors`, `processed_invoices`, `payments`, `audit_log`, `llm_calls`, `invoice_runs`, `review_decisions`, `payment_queue`, `payment_batches`) and `python -m acme.db seed`, which seeds the README's inventory (with reference prices), aliases, and vendors.
- Add settings loaded from `.env` with `pydantic-settings` (LLM, payment batch, upload, and FX settings).
- Add the switchable LLM provider (F36): one factory, `get_chat_model(role)`, that returns Grok (`ChatXAI`), Claude (`ChatAnthropic`), or an offline `RuleBasedLLM`, with shared timeout, retry, and logging, and a startup check for the selected provider's key.
- Add structured JSON logging keyed by `run_id` and agent, and writers for the `audit_log` and `llm_calls` tables.
- **P1:** per-agent provider overrides (`LLM_PROVIDER_EXTRACTION`, `_VALIDATION`, `_APPROVAL`, `_CRITIC`) to enable cross-model critique (F37).

## Capabilities

### New Capabilities
- `data-model`: Shared invoice domain models, enums, the `acme.db` schema for all tables, and the seed command with the reference inventory, aliases, and vendors.
- `llm-provider`: Provider selection (Grok, Claude, offline), per-role model resolution, startup key check, and common timeout/retry/temperature behavior (F36, F37).
- `audit-logging`: Structured JSON logs and the `audit_log` and `llm_calls` ledgers that let a run be replayed and every LLM call attributed to a provider and model.

### Modified Capabilities
- None (no existing specs).

## Impact

- New code: `backend/src/acme/{models.py, settings.py, db/, llm/, logging/}`, `main.py`, `backend/pyproject.toml`, `.env.example`.
- New dependencies: `pydantic`, `pydantic-settings`, `langchain-core`, `langchain-xai`, `langchain-anthropic`, `pytest`.
- Downstream changes build on this: `add-invoice-ingestion`, `add-validation-and-approval`, `add-payment-processing`, `add-agent-workflow`, `add-backend-api`, `add-ipa-web-app`.
- No external systems; everything runs locally, and offline mode needs no API key or network.
