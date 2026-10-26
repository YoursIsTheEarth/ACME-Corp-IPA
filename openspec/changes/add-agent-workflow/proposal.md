# Proposal

## Why

The ingestion, normalization, validation, approval, and payment capabilities are separate pieces; nothing yet runs an invoice through them in order, pauses for a person, or gives the README's required `python main.py --invoice_path=...` entry point. This change wires the six agents into one LangGraph `StateGraph`, adds the CLI that the case evaluates, and adds the golden test suite (F20) that proves all 20 provided files reach the expected outcome.

## What Changes

- **P0** Add the `agent-workflow` capability: one LangGraph `StateGraph` over `InvoiceState` with nodes Ingestion → Normalizer → Validation → Approval ⇄ Critic → Disposition, implementing the spec's five handoff rules and the three loops (extraction self-correction, validation tool loop, Approval/Critic revision).
- **P0** Disposition node (deterministic): APPROVE → `queue_payment` (plus `supersede_original` for revisions); REJECT → `record_rejection`; NEEDS_REVIEW → `enqueue_review`. The graph never calls `mock_payment`.
- **P0** Human-in-the-loop (F17, F28): NEEDS_REVIEW pauses the run with LangGraph `interrupt()`; state is persisted by a SQLite checkpointer so a held invoice survives a restart and resumes in the same run with the reviewer's decision.
- **P0** Add the `cli` capability (F18, F19): `python main.py --invoice_path=<file>`, `--batch <dir>`, `--provider`, `--pay`, `--json`, `--explain <run_id>`, `python main.py payments run`, and a `python main.py review <run_id>` command that decides held invoices from the terminal. Progress, findings, and outcomes render with `rich`.
- **P0** Golden test suite (F20): `backend/tests/test_golden.py` runs all 20 files in offline mode in sorted filename order, then one payment batch, and asserts outcome, key finding codes, and amounts paid. Adds the idempotency test, revision/payment scenario tests, and adversarial cases. The five rows that depend on P1 F7, F11, and F12 are staged as strict expected-failures, so the suite is green at the end of P0 and fully passing once P1 lands (see design).
- **P1** Batch summary report (F31): after a CLI batch, write `reports/summary.md` with counts per outcome, dollars queued, paid, and blocked, and duplicates caught.

## Capabilities

### New Capabilities
- `agent-workflow`: The LangGraph graph that carries one invoice from file to exactly one outcome (queued for payment, rejected, or held for review), including handoff rules, loops, the disposition node, and pause/resume for human review.
- `cli`: The command-line interface for processing invoices, deciding held ones, running payment batches, replaying audit trails, and writing the batch summary.

### Modified Capabilities
<!-- None: no specs exist yet. -->

## Impact

- New code: `backend/src/acme/graph/` (state graph, nodes, routing), `backend/src/acme/cli.py`, repo-root `main.py` shim, `backend/tests/test_golden.py` and related tests, `reports/` output folder.
- Depends on capabilities from earlier changes: `data-model`, `llm-provider`, `audit-logging` (add-project-foundation); `invoice-ingestion`, `invoice-normalization` (add-invoice-ingestion); `invoice-validation`, `invoice-approval` (add-validation-and-approval); `payment-processing` (add-payment-processing).
- Used by later changes: `backend-api` (add-backend-api) runs the same compiled graph and resumes reviews through it.
- New dependencies: `langgraph`, `langgraph-checkpoint-sqlite`, `rich`, `pytest`.
