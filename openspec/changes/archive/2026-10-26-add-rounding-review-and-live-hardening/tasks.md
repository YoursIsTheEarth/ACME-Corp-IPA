# Tasks

## 1. Rounding review

- [x] 1.1 Add `MATH_ROUNDING` (WARNING) to `FindingCode` and the severity maps (`acme/models.py`, `acme/validation/codes.py`), and `math_rounding_tolerance_usd` (default 1.00) to `acme/settings.py` and `.env.example`. Verify with catalog and settings tests.
- [x] 1.2 Apply the rounding band in `reconcile_math` per check (design D1). Verify with tests for 0.02 (WARNING), exactly 1.00 (WARNING), 1.01 and INV-1007 (CRITICAL), tolerance 0 (CRITICAL), sub-cent (none), a line with no amount or price (CRITICAL), and a workflow test showing that a 1-cent total goes to NEEDS_REVIEW.
- [x] 1.3 Make `check_line_sum` accept differences within the tolerance (design D2). Verify that a 6700.02 against 6700.00 attempt is accepted with no retry, and that the 500.00 difference still retries.

## 2. Live hardening

- [x] 2.1 Retry timeouts and connection errors in `acme/llm/retry.py` (design D3). Verify that a timeout followed by success gives retry count 1, that 403 is not retried, and that 429 and 5xx behavior is unchanged.
- [x] 2.2 Merge `FRAUD_SIGNAL_WEIGHTS` over the defaults (design D4). Verify that a seven-signal setting keeps `prompt_injection` at 0.60 and that an explicit 0 turns a signal off.

## 3. Docs and verification

- [x] 3.1 Document `MATH_ROUNDING_TOLERANCE_USD` and the merge in the `backend/README.md` settings table, and add the rounding row to the approval policy table in the design spec. Verify by reading.
- [x] 3.2 Run the full backend suite and the golden suite unchanged; run `openspec validate --strict`.
