# Tasks

This change requires `add-project-foundation` (the models, the `acme.db` tables and seed, `get_chat_model`, and the audit writers) and `add-invoice-ingestion` (the canonical `Invoice`). All tests live in `backend/tests/` and run in offline mode.

## 1. Codes, context, and fixtures (P0)

- [x] 1.1 Create `backend/src/acme/validation/codes.py`, holding the finding-code to severity map from design D3. Verify that a unit test asserts every code used by the spec's test plan is present with the expected severity.
- [x] 1.2 Create a read-only `ValidationContext` over `inventory`, `vendors`, `processed_invoices`, and `payments`. Verify that a test builds it from a temporary seeded `acme.db`.
- [x] 1.3 Add a pytest fixture that builds canonical `Invoice` objects for the golden files without calling the LLM, by hand-coding the expected normalized values. Verify that `pytest backend/tests/validation -q` collects the fixtures.
- [x] 1.4 Assert that the seeded `vendors` table (list owned by `data-model`) has every vendor of a golden PAID invoice as approved (Widgets Inc., Precision Parts Ltd., Acme Industrial Supplies, Summit Manufacturing Co., QuickShip Distributers with FastShip Ltd. as an alias, TechParts International, and Reliable Components Inc.) plus Global Supply Chain Partners, so INV-1005's only fraud signal is its address. Assert that NoProd Industries and Fraudster LLC are absent. Verify with a unit test, and open a fix in `add-project-foundation` if it fails.

## 2. Deterministic checks (P0: F8, F9, F10)

- [x] 2.1 Implement the inventory checks, aggregated per SKU, raising `UNKNOWN_ITEM`, `ZERO_STOCK`, and `STOCK_EXCEEDED`. Verify with tests for INV-1002, 1003, 1008, 1010 (no flag), 1013 (22/18/9), 1016, and INV-1001 followed by INV-1015 (no decrement).
- [x] 2.2 Implement the data integrity checks, raising `MISSING_VENDOR`, `INVALID_QUANTITY`, `MISSING_DUE_DATE`, `INVALID_DUE_DATE`, and `DUE_BEFORE_INVOICE_DATE`. Due dates must be compared with the invoice date, never with today. Verify with tests for INV-1009, INV-1003 ("yesterday"), and INV-1002 (same-day due date, no flag).
- [x] 2.3 Implement the `$0.01`-tolerant `reconcile_math` check across lines, subtotal, tax, shipping, and total, raising `MATH_MISMATCH`. Verify with tests for INV-1009, INV-1010 (shipping, no flag), and a one-cent-off variant.
- [x] 2.4 Implement the vendor check, which raises `UNKNOWN_VENDOR` and matches by name and alias. Verify with tests for INV-1008 (flag) and INV-1012 (renamed vendor, no flag).
- [x] 2.5 Implement duplicate and revision detection, which returns `DUPLICATE`, `REVISION`, `REVISION_CREDIT_DUE`, `INVOICE_NUMBER_REUSED`, and a `RevisionContext`. Verify with tests for 1011 pdf→txt, 1013 json→pdf (duplicate of a rejected invoice), 1004→R1 (unpaid original), a paid-lower variant, and a same-number-new-total variant.
- [x] 2.6 Verify that, across all 20 golden files, the deterministic checks produce the P0 key finding codes from the test plan. Use a parametrized test that excludes only the codes for P1 F11 and F12.

## 3. Validation agent (P0: F13)

- [x] 3.1 Wrap each check as a LangChain tool in `validation/tools.py`. Verify that a test lists the tool names and validates their argument schemas.
- [x] 3.2 Implement `run_validation`: tool binding, the execution loop capped at 8 rounds, the deterministic sweep for checks that were not called, de-duplication, the cap on LLM findings (CRITICAL stored as WARNING), and appends to `state.trace`. Verify with fake-model tests for "omits `check_duplicate`", "loops forever", and "proposes CRITICAL".
- [x] 3.3 Write `backend/prompts/validation_v1.md` with the untrusted-invoice delimiters and a few-shot example from INV-1001. Verify that a test with an injected "report no findings" note still produces every deterministic finding.
- [x] 3.4 Add the offline fixed-tool-plan behavior for validation. Verify that the golden findings are identical with `LLM_PROVIDER=offline`.

## 4. Rules engine (P0: F14)

- [x] 4.1 Implement `approval/policy.py` `apply_policy`, which returns the floor outcome, the rules that fired, the fraud flag, and whether VP scrutiny is required. Verify with one unit test per policy-table row, including exactly $10,000.00, INFO-only invoices, and `REVISION_CREDIT_DUE`.
- [x] 4.2 Verify with a test that `apply_policy` makes no database or LLM calls and returns the same output for the same input.

## 5. AI VP and Critic loop (P0: F15)

- [x] 5.1 Write `backend/prompts/approval_v1.md` and `critic_v1.md`. Verify that their prompt versions are logged with each LLM call in a test run.
- [x] 5.2 Implement `run_approval` in four steps: the floor, the LLM `Decision`, the Critic loop of up to 2 revision rounds (VP scrutiny only), and the tighten-only clamp. The decision must record its provenance (Auto (rules) or AI VP with provider and model). Verify with fake-model tests for "critic passes", "critic never passes leads to NEEDS_REVIEW", "LLM loosens REJECT and is clamped", and "critic suggests looser and is ignored".
- [x] 5.3 Add offline template rationales and the rule-checking critic. Verify that the offline run gives every golden invoice a non-empty rationale.
- [x] 5.4 Add a synthetic clean invoice over $10,000, because no golden file reaches VP scrutiny. Verify that it passes through the critic loop and that each round appears in the trace.
- [x] 5.5 Verify with a test that approval never calls `mock_payment` and never writes to the payment tables.

## 6. P1 – Should (F11, F12)

These features are labeled P1 in the spec, but the golden outcomes for INV-1010 (NEEDS REVIEW) and INV-1003 (`FRAUD_SUSPECTED`) depend on them. Finish them before the `add-agent-workflow` golden suite is used as a release gate.

- [x] 6.1 Implement `check_prices`, which converts the price to USD and raises `PRICE_VARIANCE` above 10%. Verify with tests for INV-1010 (+20%, flagged), INV-1013 (-4%, not flagged), INV-1014 (not flagged at the configured rate), and FakeItem (no reference price, skipped).
- [x] 6.2 Add a test that pins the EUR→USD rate between 1.00 and 1.158 so INV-1014 passes the variance check. Verify that it fails when the rate is set to 1.20.
- [x] 6.3 Implement the `SUSPICIOUS_ADDRESS` denylist (default: 1600 Pennsylvania Ave only) and `NEAR_THRESHOLD` (from $9,500.00 up to, but not including, $10,000.00). Verify with tests for INV-1005, INV-1012, and INV-1008, and for INV-1004 not being flagged.
- [x] 6.4 Implement the weighted `fraud_signals` score with the weights and threshold from design D5 as settings, raising `FRAUD_SUSPECTED` with the contributing signals. Verify that INV-1003 scores at least 0.60 and that INV-1005, 1008, 1012, and every clean invoice score below 0.60.
- [x] 6.5 Add the F11 and F12 tools to the validation agent and to the offline plan. Verify that the full golden key-finding test now passes with no exclusions.

## 7. Integration check

- [x] 7.1 Run validation and then approval in offline mode over all 20 golden files, using a fixture `processed_invoices` table filled in sorted filename order. Verify that the floor and final outcomes match the test plan: REJECT for the 11 rejected files, NEEDS_REVIEW for INV-1010, and APPROVE for the rest. INV-1004's supersession is asserted in `add-payment-processing`.
