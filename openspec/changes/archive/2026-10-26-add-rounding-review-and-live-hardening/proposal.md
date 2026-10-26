# Proposal

## Why

Any arithmetic difference of a cent or more is a CRITICAL `MATH_MISMATCH` today, so an invoice whose total is a few cents off from rounding is rejected outright. A person should look at it instead. The first runs against the live Grok API also exposed gaps that the fake model hides:
- A Grok request timed out once, and timeouts are not retried.
- A partial `FRAUD_SIGNAL_WEIGHTS` in `.env` silently zeroed the prompt-injection and payee signals.
- Grok returns `""` or uses `due_date_raw` for fields in ways the code did not expect. That made clean invoices fail extraction and turned INV-1003's "yesterday" into a missing due date.

Those extraction fixes are already in the code (commits d2d68ab, 042901c, b3cbfea). This change records them in the specs.

## What Changes

- **Rounding review (new behavior).** A new setting, `MATH_ROUNDING_TOLERANCE_USD`, defaults to 1.00. A math difference of at least $0.01 and at most the tolerance raises a WARNING `MATH_ROUNDING` with the expected, actual, and difference, so the invoice goes to NEEDS REVIEW. A larger difference stays CRITICAL `MATH_MISMATCH` (REJECT). Ingestion's line-sum self-correction accepts differences within the tolerance, so a rounding difference reaches validation instead of failing extraction. Setting the tolerance to 0 restores reject-on-any-cent.
- **Timeouts retried.** LLM calls that time out or fail to connect are retried with the same backoff and `LLM_MAX_RETRIES` budget as 429 and 5xx errors.
- **Fraud weights merged.** A `FRAUD_SIGNAL_WEIGHTS` value from the environment is merged over the default weights, so a partial or older setting cannot switch off a signal it omits.
- **Spec catch-up for live extraction fixes.** A blank `original_total` or `extraction_confidence` means not stated. The extraction prompt (`extraction.v3`) asks for null instead of `""` and for dates written in words to be copied as printed. A printed `Due Date:` value is copied when the LLM leaves `due_date` blank. The normalizer falls back to `due_date_raw`.

## Capabilities

### Modified Capabilities
- `invoice-validation`: arithmetic reconciliation with a rounding band, and fraud weights merged over the defaults.
- `data-model`: the new WARNING code `MATH_ROUNDING`.
- `agent-workflow`: the one-cent adversarial scenario now goes to review; a difference over the tolerance still rejects.
- `llm-provider`: timeouts and connection errors are retried.
- `invoice-ingestion`: the line-sum self-correction uses the rounding tolerance, and blank or worded fields from the LLM are handled.
- `invoice-normalization`: the due date falls back to `due_date_raw`.

## Impact

- Code: `acme/validation/checks.py`, `acme/models.py` (code and severity), `acme/validation/codes.py`, `acme/settings.py`, `acme/llm/retry.py`, `acme/ingestion/llm_extract.py`.
- Config and docs: `.env.example`, the `backend/README.md` settings table, and the design spec's approval policy table.
- Golden outcomes are unchanged: the sample math errors ($50, $110, $1,250) are all above the $1.00 default.
