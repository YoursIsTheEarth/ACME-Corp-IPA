# Proposal

## Why

The user reports that commas in numbers cause parsing issues. Today's extraction prompt (`extraction.v1`) tells the LLM to copy money "exactly as printed … including "$3,500.O0"", and its few-shot outputs contain "$5,000.00". A comma in a quantity such as "1,200" doesn't fit the integer quantity field at all, and a model that sometimes drops the comma and sometimes keeps it causes avoidable schema errors and retries. Thousands separators carry no information, so they should be removed at the source and tolerated everywhere downstream.

## What Changes

- A new extraction prompt version, `extraction.v2`, replaces `extraction.v1` (`prompt_version` bumped). It tells the LLM to drop thousands-separator commas from every money amount and quantity ("$5,000.00" → "$5000.00", "1,200" → 1200) while still copying OCR noise as printed for the cleaner ("$3,500.O0" → "$3500.O0"). Its few-shot outputs contain no thousands separators.
- The deterministic side tolerates commas regardless of what the model returns:
  - money strings are already parsed comma-free by `parse_money`; this is confirmed with tests
  - extracted quantities given as strings with thousands separators ("1,200") are accepted as integers instead of failing the schema
  - CSV and XML numeric values with thousands separators normalize the same way
- Out of scope: decimal-comma formats such as "4.125,00". The TXT/PDF LLM path is US-formatted in every sample; INV-1014 (EUR) is XML and parsed deterministically with a decimal point.
- The source design doc's prompt bullet is updated to mention the rule.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `invoice-ingestion`: adds a requirement that thousands-separator commas are ignored when extracting numbers.

## Impact

- `backend/prompts/extraction.v2.md` (new) and `backend/src/acme/ingestion/llm_extract.py` (`PROMPT_VERSION`). `extraction.v1.md` stays, so old `llm_calls` rows keep a readable prompt.
- `backend/src/acme/ingestion/schema.py` (quantity coercion on `ExtractedLineItem`).
- Tests in `backend/tests/ingestion/` and `backend/tests/normalization/`, plus references to `extraction.v1` in tests and the `llm/callbacks.py` docstring.
- No API, UI, or data model change.
