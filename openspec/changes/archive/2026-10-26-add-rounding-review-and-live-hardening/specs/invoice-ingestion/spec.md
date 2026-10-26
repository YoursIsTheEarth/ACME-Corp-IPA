## MODIFIED Requirements

### Requirement: Extraction self-correction (F4)
After each LLM extraction attempt, the system SHALL check that the result passes the `Invoice` schema. It SHALL also check that line-item amounts sum to the subtotal, or to the total when no subtotal is printed, within the larger of $0.01 and `MATH_ROUNDING_TOLERANCE_USD`. On failure it SHALL retry with the exact error text in the prompt, up to 2 retries (3 attempts in total).

#### Scenario: Schema error corrected on retry
- **WHEN** the first attempt returns a quantity as a non-numeric string and the second attempt is valid
- **THEN** the second prompt contains the validation error text, the second result is accepted, and the retry count is 1

#### Scenario: Line sum mismatch triggers retry
- **WHEN** an attempt's line amounts sum to 6200.00 but its subtotal reads 6700.00
- **THEN** the next attempt's prompt states the 500.00 difference, and the run's retry count increments

#### Scenario: Rounding difference accepted
- **WHEN** an attempt's line amounts sum to 6700.02 and its subtotal reads 6700.00, with the default tolerance
- **THEN** the attempt is accepted without a retry

#### Scenario: Invoice without a subtotal line
- **WHEN** `invoice_1002.txt` (only "Amt: $15,000.00") is extracted
- **THEN** the line sum of 15000.00 is checked against the total and passes without a retry

## ADDED Requirements

### Requirement: Blank and worded fields from the LLM
LLM extraction SHALL tolerate the ways a live model fills fields:
- A blank string for `original_total` or `extraction_confidence` SHALL mean not stated.
- The extraction prompt (`extraction.v3`) SHALL ask for null instead of `""`, and for dates written in words ("yesterday", "upon receipt") to be copied as printed.
- When the model leaves `due_date` null or blank and sets no `due_date_raw`, a printed `Due Date:` (or `Due:`) value in the document text SHALL be copied as found.

#### Scenario: Blank original total on a USD invoice
- **WHEN** the model returns `"original_total": ""` for INV-1001
- **THEN** extraction is accepted on the first attempt with `original_total` empty

#### Scenario: Worded due date left blank by the model
- **WHEN** the model returns a blank `due_date` for a document that prints "Due Date: yesterday"
- **THEN** the extracted `due_date` is "yesterday"
