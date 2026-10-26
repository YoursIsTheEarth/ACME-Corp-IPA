## MODIFIED Requirements

### Requirement: Database schema
The system SHALL keep all persistent state in one SQLite file, `acme.db`, with tables `inventory` (`item` PK, `stock`, `unit_price`, `category`), `item_aliases`, `vendors`, `processed_invoices`, `payments` (unique `idempotency_key`), `audit_log`, `llm_calls`, `invoice_runs`, `review_decisions`, `payment_queue`, `payment_batches`, and `admin_settings` (`key` PK, `value`, `updated_by`, `updated_at`), with the columns listed in the design spec. `payment_batches.trigger` SHALL accept `immediate` alongside the existing triggers. Creating the schema SHALL be idempotent.

#### Scenario: Schema created on empty file
- **WHEN** schema creation runs against a missing `acme.db`
- **THEN** the file is created and contains all twelve tables

#### Scenario: Schema creation is repeatable
- **WHEN** schema creation runs a second time against an existing `acme.db`
- **THEN** no error occurs and existing rows are preserved

#### Scenario: Existing database gains the settings table
- **WHEN** schema creation runs against an `acme.db` created before `admin_settings` existed
- **THEN** the `admin_settings` table is added, it is empty, and existing rows in every other table are preserved

#### Scenario: Payment idempotency enforced by the database
- **WHEN** two rows with the same `idempotency_key` are inserted into `payments`
- **THEN** the second insert fails
