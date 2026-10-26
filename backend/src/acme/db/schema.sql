-- acme.db schema. Idempotent: safe to run on an existing database.
-- Money is stored as TEXT (Decimal strings); timestamps as ISO 8601 TEXT.

CREATE TABLE IF NOT EXISTS inventory (
    item        TEXT PRIMARY KEY,
    stock       INTEGER NOT NULL,
    unit_price  TEXT,
    category    TEXT
);

CREATE TABLE IF NOT EXISTS item_aliases (
    alias  TEXT PRIMARY KEY,
    sku    TEXT NOT NULL REFERENCES inventory(item)
);

CREATE TABLE IF NOT EXISTS vendors (
    name     TEXT PRIMARY KEY,
    aliases  TEXT NOT NULL DEFAULT '[]',  -- JSON array of alternate names
    status   TEXT NOT NULL CHECK (status IN ('approved', 'unknown'))
);

CREATE TABLE IF NOT EXISTS processed_invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor          TEXT NOT NULL,
    invoice_number  TEXT NOT NULL,
    revision        INTEGER NOT NULL DEFAULT 0,
    content_hash    TEXT,
    outcome         TEXT,
    run_id          TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_processed_invoices_key
    ON processed_invoices (vendor, invoice_number, revision);

CREATE TABLE IF NOT EXISTS payments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key  TEXT NOT NULL UNIQUE,
    vendor           TEXT NOT NULL,
    amount_usd       TEXT NOT NULL,
    paid_at          TEXT NOT NULL,
    batch_id         TEXT,
    payment_id       TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    ts            TEXT NOT NULL,
    agent         TEXT,
    event         TEXT NOT NULL,
    payload_json  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_audit_log_run ON audit_log (run_id, ts, id);

CREATE TABLE IF NOT EXISTS llm_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,
    agent           TEXT,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT,
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    retries         INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    ts              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_llm_calls_run ON llm_calls (run_id);

CREATE TABLE IF NOT EXISTS invoice_runs (
    id              TEXT PRIMARY KEY,
    file_name       TEXT NOT NULL,
    stored_path     TEXT,
    uploaded_at     TEXT NOT NULL,
    status          TEXT NOT NULL,
    stage           TEXT,
    invoice_number  TEXT,
    vendor          TEXT,
    total_usd       TEXT,
    final_status    TEXT,
    decided_by      TEXT,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS review_decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    reviewer    TEXT NOT NULL,
    decision    TEXT NOT NULL,
    rationale   TEXT NOT NULL,
    decided_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_batches (
    batch_id      TEXT PRIMARY KEY,
    trigger       TEXT NOT NULL
        CHECK (trigger IN ('end_of_day', 'idle', 'pay_all', 'pay_selected', 'pay_now')),
    released_by   TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    count         INTEGER NOT NULL DEFAULT 0,
    total_usd     TEXT NOT NULL DEFAULT '0.00',
    failed_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payment_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    invoice_number  TEXT NOT NULL,
    revision        INTEGER NOT NULL DEFAULT 0,
    vendor          TEXT NOT NULL,
    amount_usd      TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('full', 'replacement', 'delta')),
    status          TEXT NOT NULL
        CHECK (status IN ('queued', 'paying', 'paid', 'failed', 'cancelled')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    queued_at       TEXT NOT NULL,
    batch_id        TEXT
);
CREATE INDEX IF NOT EXISTS ix_payment_queue_status ON payment_queue (status);
