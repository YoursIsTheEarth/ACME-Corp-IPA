# Tasks

Prerequisites: add-project-foundation, add-invoice-ingestion, add-validation-and-approval, and add-payment-processing are applied.

## 1. Setup

- [x] 1.1 Add `langgraph`, `langgraph-checkpoint-sqlite`, `rich`, and `pytest` to `backend/pyproject.toml` and verify `pip install -e backend` succeeds and `python -c "import langgraph, rich"` runs
- [x] 1.2 Create `backend/src/acme/graph/` (`build.py`, `nodes.py`, `routing.py`) and `backend/src/acme/workflow.py`, and verify `python -c "import acme.graph, acme.workflow"` succeeds

## 2. Graph wiring and handoffs (P0)

- [x] 2.1 Implement `ingest` node with the self-correction loop routing (max 2 retries, failure → `disposition` with `EXTRACTION_FAILED`) and verify unit tests for success, success-on-retry, and fail-after-retries routes, including an empty file
- [x] 2.2 Implement `normalize` node calling the normalization capability and verify a test that "Widget A" in INV-1012 reaches validation as `WidgetA`
- [x] 2.3 Implement `validate` ⇄ `validation_tools` tool loop plus the deterministic `run_all_checks` merge and dedupe (handoff rule 2) and verify a test where a stub LLM calls no tools still yields `STOCK_EXCEEDED` for INV-1002
- [x] 2.4 Implement `approve` and `critic` nodes with the 2-round revision loop and the `stricter()` floor clamp recording `llm_override_blocked` (F15, rules 3–4), and verify tests for REJECT→APPROVE blocked, APPROVE→NEEDS_REVIEW allowed, and critic-never-passes
- [x] 2.5 Implement deterministic `disposition` node calling `queue_payment`, `supersede_original`, `record_rejection`, `enqueue_review` and verify tests that APPROVE queues a row, REJECT writes the rejection log, and no path calls `mock_payment`
- [x] 2.6 Append trace entries from every node and persist to `audit_log` by `run_id`, and verify a test that a clean run's audit entries appear in stage order
- [x] 2.7 Wrap invoice text in untrusted-data delimiters in all LLM-calling nodes and verify the prompt-injection adversarial test returns REJECT with `UNKNOWN_ITEM`

## 3. Review hold and resume (P0, F17, F28)

- [x] 3.1 Add `review_hold` node using `interrupt()` and compile the graph with `SqliteSaver` on `acme.db` (WAL mode, `thread_id = run_id`), and verify INV-1010 pauses with status Awaiting review
- [x] 3.2 Implement `acme.workflow.resume_review(run_id, decision, reviewer, rationale)` with input validation (reviewer 1–50 chars trimmed, rationale ≥ 15), the conditional `Awaiting review → Resuming` claim (`ReviewConflict` when not awaiting review), the `review_decisions` insert, graph resume, and dispatch to `resume_payment_failure` for payment-failure holds, and verify tests for approve, reject, invalid input, and conflict
- [x] 3.3 Verify a restart test: hold INV-1010, rebuild the graph from a fresh process/connection, resume, and assert a payment queue row exists for the same `run_id`
- [x] 3.4 Implement `recover_orphaned_runs()` (mid-pipeline runs reset to Uploaded and returned) and call it plus `recover_interrupted_batch()` at CLI startup; verify a test with a run stuck in Validating

## 4. Runner API (P0)

- [x] 4.1 Implement `run_invoice(path, provider=None)` and `run_folder(dir)` (sorted filename order) updating `invoice_runs` status, stage, and final fields, and verify a test that `run_folder` processes 20 files in sorted order

## 5. CLI (P0, F18, F19)

- [x] 5.1 Implement `backend/src/acme/cli.py` (argparse) with `--invoice_path`, `--batch`, `--provider`, `--pay`, `--json`, and `--explain` (the `main.py` shim exists from `add-project-foundation`), and verify `python main.py --invoice_path=data/invoices/invoice_1001.txt --provider offline` exits 0 and prints APPROVE
- [x] 5.2 Render stage progress, findings, and outcome with `rich`; `--json` emits JSON lines on stdout with logs on stderr; verify a CLI test parsing `--json` output for INV-1002
- [x] 5.3 Implement `payments run` and `--pay` (trigger `pay_all`, `--released-by` default `cli`) and verify a test that `--batch data/invoices --pay` pays 7 rows and a second `payments run` pays 0
- [x] 5.4 Implement `review` list and `review <run_id> --decision --reviewer --rationale` and verify CLI tests for listing INV-1010, approving it, invalid input, and a non-held run
- [x] 5.5 Implement `--explain <run_id>` replay from `audit_log` and verify tests for INV-1003 output and unknown run_id
- [x] 5.6 Add a CLI usage section to `README.md` covering every flag and subcommand and verify each documented command runs as written in offline mode

## 6. Golden and scenario tests (P0, F20)

- [x] 6.1 Write `backend/tests/test_golden.py` with a session fixture (temp `acme.db`, offline provider, `run_folder` then one batch) and a parametrized test over all 20 files asserting outcome, key finding codes, and paid amounts (EUR row via configured rate); tag the rows that need P1 features (1003, 1005, 1012 → F11; 1010 → F12; 1014 → F7) with `pytest.mark.xfail(strict=True, reason="needs F#")`, and verify `pytest backend/tests/test_golden.py` is green with 15 passed and 5 xfailed
- [x] 6.2 Add aggregate asserts (no CRITICAL findings on paid files; no payment before last disposition) and verify they pass; add the count assert (7 paid, 1 superseded, 1 held, 11 rejected, 3 duplicates) skipped while any golden row is still tagged, and verify it is reported as skipped
- [x] 6.3 Add idempotency tests (second batch pays 0; reprocessing the folder yields `DUPLICATE` and no payments) and verify they pass
- [x] 6.4 Add revision scenario tests from copies of INV-1004 (paid+higher → delta, paid+lower → review, paid+same → Revised, queued+failing revision → original Superseded unpaid) and verify they pass
- [x] 6.5 Add adversarial tests (prompt-injection line, total off by $0.01 → `MATH_MISMATCH`, lookalike vendor not auto-approved, empty file → `EXTRACTION_FAILED`) and verify they pass

## 7. P1 — Batch summary report (F31)

- [x] 7.1 Write `reports/summary.md` and print the summary after `--batch` (counts per outcome, dollars queued/paid/blocked, duplicates caught) and verify a test that the golden batch summary shows 7 paid, 1 superseded, 1 held, 11 rejected, 3 duplicates

## 8. P1 — Un-stage golden rows

- [x] 8.1 As each of F7, F11, and F12 lands in its change, remove the matching xfail tags in `test_golden.py` and verify the newly untagged rows pass
- [x] 8.2 Once no row is tagged, verify the count assert runs and passes (7 paid, 1 superseded, 1 held, 11 rejected, 3 duplicates)

## 9. Integration check

- [x] 9.1 From a clean checkout, run `python -m acme.db seed`, `python main.py --batch data/invoices --provider offline --pay`, `python main.py review`, and `pytest backend/tests`, and verify all succeed (with P1 landed, with the golden counts)
