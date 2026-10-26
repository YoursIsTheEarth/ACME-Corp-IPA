## MODIFIED Requirements

### Requirement: Finding code catalog
The system SHALL define one enumerated catalog of finding codes used verbatim across all stages, each with one canonical severity that rule-sourced findings SHALL use. The CRITICAL codes SHALL be `EXTRACTION_FAILED`, `UNKNOWN_ITEM`, `ZERO_STOCK`, `STOCK_EXCEEDED`, `INVALID_QUANTITY`, `MATH_MISMATCH`, `MISSING_VENDOR`, `DUPLICATE`, `FRAUD_SUSPECTED`, and `PROMPT_INJECTION_SUSPECTED`.

#### Scenario: Critical code
- **WHEN** the catalog is asked for the severity of `DUPLICATE`
- **THEN** it returns CRITICAL

#### Scenario: Prompt injection is critical
- **WHEN** the catalog is asked for the severity of `PROMPT_INJECTION_SUSPECTED`
- **THEN** it returns CRITICAL

### Requirement: Warning and info finding codes
The catalog's WARNING codes SHALL be `UNKNOWN_VENDOR`, `MISSING_DUE_DATE`, `INVALID_DUE_DATE`, `DUE_BEFORE_INVOICE_DATE`, `PRICE_VARIANCE`, `SUSPICIOUS_ADDRESS`, `REVISION_CREDIT_DUE`, `INVOICE_NUMBER_REUSED`, `CURRENCY_UNSUPPORTED`, and `PAYEE_CUMULATIVE_THRESHOLD`. Its INFO codes SHALL be `REVISION`, `SUPERSEDED_BY_REVISION`, `NEAR_THRESHOLD`, and `CURRENCY_CONVERTED`.

#### Scenario: Info code
- **WHEN** the catalog is asked for the severity of `NEAR_THRESHOLD`
- **THEN** it returns INFO

#### Scenario: Canonical severity
- **WHEN** the catalog is asked for the severity of `CURRENCY_UNSUPPORTED`
- **THEN** it returns WARNING

#### Scenario: Payee threshold is a warning
- **WHEN** the catalog is asked for the severity of `PAYEE_CUMULATIVE_THRESHOLD`
- **THEN** it returns WARNING

#### Scenario: Codes serialize verbatim
- **WHEN** a finding with code `STOCK_EXCEEDED` is serialized to JSON
- **THEN** the JSON value is exactly "STOCK_EXCEEDED"

### Requirement: Database schema
The system SHALL keep all persistent state in one SQLite file, `acme.db`, with tables `inventory` (`item` PK, `stock`, `unit_price`, `category`), `item_aliases`, `vendors`, `processed_invoices`, `payments` (unique `idempotency_key`), `audit_log`, `llm_calls`, `invoice_runs`, `review_decisions`, `payment_queue`, `payment_batches`, `admin_settings` (`key` PK, `value`, `updated_by`, `updated_at`), `payees`, `payee_names`, `payee_addresses`, and `payee_invoices`, with the columns listed in the design spec. `payment_batches.trigger` SHALL accept `immediate` alongside the existing triggers. Creating the schema SHALL be idempotent.

#### Scenario: Schema created on empty file
- **WHEN** schema creation runs against a missing `acme.db`
- **THEN** the file is created and contains all sixteen tables

#### Scenario: Schema creation is repeatable
- **WHEN** schema creation runs a second time against an existing `acme.db`
- **THEN** no error occurs and existing rows are preserved

#### Scenario: Existing database gains the settings table
- **WHEN** schema creation runs against an `acme.db` created before `admin_settings` existed
- **THEN** the `admin_settings` table is added, it is empty, and existing rows in every other table are preserved

#### Scenario: Existing database gains the payee tables
- **WHEN** schema creation runs against an `acme.db` created before the payee tables existed
- **THEN** the four payee tables are added and existing rows in every other table are preserved

#### Scenario: Payment idempotency enforced by the database
- **WHEN** two rows with the same `idempotency_key` are inserted into `payments`
- **THEN** the second insert fails

### Requirement: Vendor seed
Seed SHALL mark as approved: Widgets Inc., Precision Parts Ltd., Acme Industrial Supplies, Consolidated Materials Group, Summit Manufacturing Co., QuickShip Distributers (aliases "QuickShip Distributers (formerly FastShip Ltd.)" and "FastShip Ltd."), TechParts International, Reliable Components Inc., Gadgets Co., Global Supply Chain Partners, MegaWidgets Corp, Atlas Industrial Supply, Northwind Fabrication LLC, Harbor Point Supply Co., and HPS Industrial Partners. It SHALL NOT seed NoProd Industries, Fraudster LLC, or Apex Procurement Services.

#### Scenario: Renamed vendor seeded with aliases
- **WHEN** the seeded `vendors` table is queried for "FastShip Ltd."
- **THEN** it resolves to the approved vendor QuickShip Distributers

#### Scenario: Unknown vendors absent
- **WHEN** the seeded `vendors` table is queried for NoProd Industries, Fraudster LLC, or Apex Procurement Services
- **THEN** no approved row is found

#### Scenario: Split-invoicing vendors look legitimate
- **WHEN** the seeded `vendors` table is queried for Northwind Fabrication LLC, Harbor Point Supply Co., or HPS Industrial Partners
- **THEN** each is an approved vendor, so their invoices raise no `UNKNOWN_VENDOR` finding

## ADDED Requirements

### Requirement: Payee seed
Seed SHALL create one payee for each seeded vendor, with its name and aliases. It SHALL record the remit-to addresses printed on clean sample invoices: Widgets Inc. "100 Main St, Chicago, IL 60601" and Precision Parts Ltd. "742 Evergreen Terrace, Springfield, IL 62704". It SHALL NOT seed addresses for the fixture vendors, which the system learns from their invoices. Re-running seed SHALL NOT duplicate payees or remove learned names, addresses, or ledger rows.

#### Scenario: Seeded payee resolves by alias
- **WHEN** the seeded payees are searched for "FastShip Ltd."
- **THEN** the QuickShip Distributers payee is found

#### Scenario: Seed keeps learned data
- **WHEN** seed runs again after Harbor Point Supply Co.'s address was learned from INV-1021
- **THEN** that address and the INV-1021 ledger row are still present
