## ADDED Requirements

### Requirement: Thousands-separator commas ignored in numbers
Extraction SHALL treat thousands-separator commas in money amounts and quantities as formatting, not data:
- The LLM extraction prompt SHALL instruct the model to drop them while still copying any OCR noise as printed.
- Every extracted money amount and quantity SHALL parse to the same value with or without the commas, whichever path produced it (LLM, CSV, JSON, or XML).

Decimal-comma formats (such as "4.125,00") are out of scope.

#### Scenario: Comma in a printed total
- **WHEN** a text invoice prints "Amt: $15,000.00" and is extracted
- **THEN** the extracted total is 15000.00 and no retry is needed because of the comma

#### Scenario: Model returns a comma anyway
- **WHEN** an extraction attempt returns the total as "$5,000.00" and a quantity as "1,200"
- **THEN** the attempt passes the schema, the quantity is 1200, the total normalizes to 5000.00, and no retry is triggered

#### Scenario: OCR noise kept for the cleaner
- **WHEN** a PDF invoice prints "$3,500.O0"
- **THEN** the extraction prompt's rule yields "$3500.O0", and normalization produces 3500.00

#### Scenario: Prompt states the rule
- **WHEN** the extraction prompt is rendered
- **THEN** it instructs the model to drop thousands-separator commas from money and quantities
- **AND** none of its few-shot outputs contains a thousands separator
