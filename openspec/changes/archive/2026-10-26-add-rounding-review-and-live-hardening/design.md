# Design

## D1. Rounding band, per check

`reconcile_math` checks three things: each line's amount, the line sum against the subtotal, and the subtotal plus tax and shipping against the total. Each check compares `diff = |expected - actual|`:

| diff | Finding |
| --- | --- |
| under $0.01 | none (sub-cent noise, unchanged) |
| $0.01 to `MATH_ROUNDING_TOLERANCE_USD` inclusive | WARNING `MATH_ROUNDING`, evidence `check`, `expected`, `actual`, `difference`, `tolerance` |
| over the tolerance | CRITICAL `MATH_MISMATCH` (unchanged evidence) |

A line with neither an amount nor a unit price stays `MATH_MISMATCH`. Each check is judged on its own, so one rounded line plus one badly wrong total gives a WARNING and a CRITICAL, and the CRITICAL decides (REJECT). The tolerance is in USD and applies to the canonical (converted) amounts. It is a flat amount, not a percentage: rounding error does not grow with the invoice size, and a flat cap is easy to explain to AP staff.

**Why $1.00:** it covers sub-dollar rounding across many lines and tax rounding. Every planted math error in the sample data is $50 or more, so all golden outcomes are unchanged.

**Approval:** no change is needed. Any WARNING with no CRITICAL already gives floor NEEDS_REVIEW, and the rationale and "Why it's held" show the finding message ("Subtotal + tax + shipping is 1000.00 but the total is 1000.02 (difference 0.02, within the 1.00 rounding tolerance)").

## D2. Ingestion line-sum check uses the same tolerance

`check_line_sum` raises (triggering a retry) when `|lines - expected| > max($0.01, tolerance)`. Without this, a 2-cent rounding difference would retry twice and fail closed as `EXTRACTION_FAILED`, never reaching review. Differences over the tolerance still trigger the self-correction retry, which is there to catch misread lines.

## D3. Retryable errors

`is_retryable` also returns true for `openai.APIConnectionError` (which includes `APITimeoutError` and the `langchain_openai` timeout wrapper used by `langchain-xai`), `anthropic.APIConnectionError`, and `httpx.TransportError`. The retry budget and backoff are unchanged. A 403 from a sandbox proxy is a status error and is still not retried.

## D4. Fraud weights merge

A `field_validator` on `fraud_signal_weights` returns `{**DEFAULT_FRAUD_SIGNAL_WEIGHTS, **value}`. A name absent from the environment value keeps its default, and an explicit 0 still turns a signal off. Unknown names are kept and ignored, as today.
