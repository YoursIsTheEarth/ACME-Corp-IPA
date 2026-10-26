# Proposal

## Why

Acme's manual process lets about 30% of invoices through with errors: stock overruns, unknown or zero-stock items, bad arithmetic, duplicates, and fraud-style requests. Approvals sit in VP email chains for days. The pipeline needs deterministic checks that catch every planted issue in `data/invoices/`, and an approval step that is repeatable. The design principle is that the LLM reads and reasons while plain Python decides about money. This change delivers both halves of that rule for the Validation, Approval (VP), and Critic agents.

## What Changes

- Add deterministic validation checks, written as plain Python tool functions that return `Finding` objects with the spec's finding codes and severities:
  - Inventory checks, aggregated per SKU across lines: `UNKNOWN_ITEM`, `ZERO_STOCK`, `STOCK_EXCEEDED` (F8).
  - Data integrity checks: `MISSING_VENDOR`, `MISSING_DUE_DATE`, `INVALID_DUE_DATE`, `INVALID_QUANTITY`, `MATH_MISMATCH`, and due date before invoice date (F9).
  - Detection of duplicates and revisions against `processed_invoices`: `DUPLICATE` (CRITICAL) and `REVISION` (INFO, linked to the original) (F10, detection only).
  - Vendor check against the seeded `vendors` table: `UNKNOWN_VENDOR`.
- Add an LLM validation agent (F13). It binds the validation tools, chooses which to call in a tool-call loop, and summarizes the findings. Afterward a deterministic sweep runs every check the LLM skipped.
- Add a pure-function rules engine, `apply_policy` (F14). It implements the approval policy table and returns the floor outcome (APPROVE, REJECT, or NEEDS_REVIEW), the rules that fired, a fraud flag, and whether VP scrutiny is required.
- Add the AI VP Approval agent and the Critic loop (F15):
  - The LLM drafts a `Decision`, and the Critic returns a `Critique`.
  - Approval revises for at most 2 rounds.
  - The final outcome can only tighten the rules-engine floor, never loosen it.
  - Every round is appended to `state.trace`.
- Add versioned prompts for validation, approval, and the critic under `backend/prompts/`. Invoice text is delimited and labeled as untrusted data.
- Add offline (`RuleBasedLLM`) behavior for all three agents: a fixed tool plan, template rationales, and a rule-checking critic.
- **P1 – Should:**
  - Fraud signal scoring with a `FRAUD_SUSPECTED` flag (F11). It uses the signals urgency language, wire-transfer requests, "Immediate" terms, past-due or relative due dates, `UNKNOWN_VENDOR`, `SUSPICIOUS_ADDRESS`, and `NEAR_THRESHOLD`.
  - Price variance over 10% against the reference unit price: `PRICE_VARIANCE` (F12).
  - Note: the golden outcomes for INV-1010 (`PRICE_VARIANCE` leads to NEEDS REVIEW) and INV-1003 (`FRAUD_SUSPECTED`), and the key finding codes `SUSPICIOUS_ADDRESS` (INV-1005) and `NEAR_THRESHOLD` (INV-1012), depend on these. Without F12, INV-1010 would be auto-paid. Thresholds, weights, and the address list are read from `add-project-foundation`'s settings catalog. Implement them right after the P0 tasks and before the golden suite in `add-agent-workflow` is considered green.

## Capabilities

### New Capabilities
- `invoice-validation`: Deterministic and LLM-driven checks that turn a canonical `Invoice` into `findings[]`. Covers inventory, data integrity, duplicate and revision detection, vendor, fraud signals, price variance, and the tool-calling validation agent (F8–F13).
- `invoice-approval`: The approval policy rules engine, plus the AI VP draft and Critic loop that produce the final `Decision` (F14, F15).

### Modified Capabilities
None. There are no existing specs.

## Impact

- **New code:**
  - `backend/src/acme/validation/` contains the checks, the tool wrappers, the fraud scoring, and the validation agent.
  - `backend/src/acme/approval/` contains `policy.py` (the rules engine), the VP agent, and the critic.
  - `backend/prompts/validation_v1`, `approval_v1`, and `critic_v1`.
- **New tests:** `backend/tests/` covers each check, each policy row, and the tighten-only clamp.
- **Depends on:**
  - `add-project-foundation`: the `Invoice`, `Finding`, `Decision`, `Critique`, and `InvoiceState` models; the `inventory`, `vendors`, and `processed_invoices` tables and their seed; `get_chat_model(role)`; and the `audit_log` and `llm_calls` writers.
  - `add-invoice-ingestion`: canonical `Invoice` objects with resolved SKUs, parsed dates, and USD amounts.
- **Consumed by:**
  - `add-agent-workflow`, which wires these agents into the `StateGraph` and routes on the outcome.
  - `add-payment-processing`, which acts on `REVISION` and `DUPLICATE` findings and approved decisions.
- **New dependencies:** none beyond those in `add-project-foundation`, which are LangChain core, LangGraph `ToolNode`, and Pydantic.
