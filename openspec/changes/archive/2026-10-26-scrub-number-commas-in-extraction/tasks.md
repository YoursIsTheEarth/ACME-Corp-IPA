# Tasks

## 1. Prompt v2

- [x] 1.1 Create `backend/prompts/extraction.v2.md` from v1. Replace the "Transcribe; do not correct" rule so it says to copy dates, money, and the invoice number as printed (OCR noise included) but remove thousands-separator commas from money amounts and quantities, with the examples "$5,000.00" → "$5000.00", "1,200" → 1200, "$3,500.O0" → "$3500.O0". Make the few-shot outputs comma-free. Set `PROMPT_VERSION = "extraction.v2"` in `backend/src/acme/ingestion/llm_extract.py`. Verify `backend/tests/ingestion/test_prompt.py`, updated to expect v2, asserts:
  - the rule text is present
  - no few-shot output in the rendered system prompt matches `\d,\d{3}`
  - the snapshot still passes
- [x] 1.2 Update the remaining `extraction.v1` references in tests (for example `test_llm_extract.py`'s recorded `prompt_version`) and the `acme/llm/callbacks.py` docstring. Verify `grep -rn "extraction.v1" backend/src backend/tests` returns nothing.

## 2. Comma-tolerant parsing

- [x] 2.1 Add a `mode="before"` quantity validator to `ExtractedLineItem` in `backend/src/acme/ingestion/schema.py` that strips thousands-separator commas from integer strings. Verify schema tests:
  - "1,200" → 1200
  - "-1,200" → -1200
  - 12 → 12
  - "twelve" still fails validation
- [x] 2.2 Add `parse_money` tests in `backend/tests/normalization/test_cleaners.py` for "$15,000.00", "1,234,567.89", and "$3,500.O0" (after `fix_ocr`). Verify they pass.
- [x] 2.3 Add an extraction round-trip test in `backend/tests/ingestion/test_llm_extract.py`. A scripted model returns total "$15,000.00" and a line with quantity "1,200" and amount "$1,200.00"; verify the attempt is accepted with zero retries and normalizes to total 15000.00 and quantity 1200. Add a CSV test with a quoted "1,200" quantity and verify it parses the same way.

## 3. Integration check

- [x] 3.1 Run `pytest backend/tests` and verify the full suite, including the 20-row golden test, passes unchanged.
