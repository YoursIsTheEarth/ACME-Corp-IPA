## MODIFIED Requirements

### Requirement: Golden outcomes for the provided files
Processing all 20 files in `data/invoices/` in sorted filename order with the test-only fake model standing in for the LLM provider and payment delay on (pay at end of day off, pay when the Invoice Queue is empty on), followed by one payment batch, SHALL produce the outcome, paid amount, and key finding codes listed for each file in the Full golden batch scenario (F20).

#### Scenario: Full golden batch
- **WHEN** all 20 files are processed in sorted filename order with the test-only fake model and payment delay on, and one payment batch runs
- **THEN** each file's outcome and key finding codes match the table below, the paid amounts match, and the counts are 7 paid, 1 superseded, 1 held, 11 rejected (3 as duplicates)

| File | Outcome | Paid in batch | Key finding codes |
| --- | --- | --- | --- |
| invoice_1001.txt | PAID | $5,000.00 | none |
| invoice_1002.txt | REJECT | | `STOCK_EXCEEDED` |
| invoice_1003.txt | REJECT | | `ZERO_STOCK`, `INVALID_DUE_DATE`, `FRAUD_SUSPECTED` |
| invoice_1004.json | SUPERSEDED | | `SUPERSEDED_BY_REVISION` |
| invoice_1004_revised.json | PAID | $5,940.00 | `REVISION` |
| invoice_1005.json | REJECT | | `STOCK_EXCEEDED`, `SUSPICIOUS_ADDRESS` |
| invoice_1006.csv | PAID | $2,750.00 | none |
| invoice_1007.csv | REJECT | | `STOCK_EXCEEDED` |
| invoice_1008.txt | REJECT | | `UNKNOWN_ITEM`, `UNKNOWN_VENDOR` |
| invoice_1009.json | REJECT | | `MISSING_VENDOR`, `INVALID_QUANTITY`, `MATH_MISMATCH`, `MISSING_DUE_DATE` |
| invoice_1010.txt | NEEDS REVIEW | | `PRICE_VARIANCE` |
| invoice_1011.pdf | PAID | $3,000.00 | none |
| invoice_1011.txt | REJECT | | `DUPLICATE` |
| invoice_1012.pdf | PAID | $9,975.00 | `NEAR_THRESHOLD` |
| invoice_1012.txt | REJECT | | `DUPLICATE` |
| invoice_1013.json | REJECT | | `STOCK_EXCEEDED` |
| invoice_1013.pdf | REJECT | | `DUPLICATE` |
| invoice_1014.xml | PAID | EUR 4,125.00 converted to USD at the configured rate | `CURRENCY_CONVERTED` |
| invoice_1015.csv | PAID | $6,500.00 | none |
| invoice_1016.json | REJECT | | `UNKNOWN_ITEM` |

#### Scenario: Address verdict from the model
- **WHEN** invoice_1005.json is processed in the golden batch
- **THEN** its `SUSPICIOUS_ADDRESS` finding comes from the address assessment with `source` = `llm`, not from a configured address list

## ADDED Requirements

### Requirement: Golden outcomes with immediate payments
Processing all 20 files in sorted filename order with the test-only fake model and the default payment timing (delay off) SHALL pay each approved invoice as it is approved, with every file's outcome, finding codes, and paid amount as in the delayed golden table except for the INV-1004 pair.

#### Scenario: Full golden run with delay off
- **WHEN** all 20 files are processed in sorted filename order with payment delay off and no manual batch runs
- **THEN** invoice_1004.json is PAID $1,890.00 with no `SUPERSEDED_BY_REVISION` finding
- **AND** invoice_1004_revised.json is Revised with `REVISION` and a $4,050.00 delta payment
- **AND** the counts are 7 paid, 1 revised, 0 superseded, 1 held, 11 rejected (3 as duplicates), with 8 payments totalling $37,620.00 (EUR at the default 1.08), each made by its own `immediate` batch

#### Scenario: Nothing left to pay
- **WHEN** a payment batch runs after that golden run
- **THEN** it pays nothing
