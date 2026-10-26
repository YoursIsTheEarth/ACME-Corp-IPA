"""SQLite access for `acme.db`.

    conn = connect()          # path from settings.db_path unless given
    init_schema(conn)         # idempotent; creates all tables

Decimals and dates can be bound directly as parameters (stored as TEXT).
"""

import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

from acme.settings import get_settings

sqlite3.register_adapter(Decimal, str)
sqlite3.register_adapter(date, date.isoformat)
sqlite3.register_adapter(datetime, datetime.isoformat)

TABLES = (
    "inventory",
    "item_aliases",
    "vendors",
    "processed_invoices",
    "payments",
    "audit_log",
    "llm_calls",
    "invoice_runs",
    "review_decisions",
    "payment_queue",
    "payment_batches",
    "admin_settings",
    "payees",
    "payee_names",
    "payee_addresses",
    "payee_invoices",
)


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open `acme.db` with WAL, foreign keys, and `sqlite3.Row` rows."""
    db_path = Path(path) if path is not None else get_settings().db_path
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create every table and index that doesn't exist yet; existing rows are kept."""
    schema = files("acme.db").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
    _rebuild_payment_batches(conn, schema)


def _rebuild_payment_batches(conn: sqlite3.Connection, schema: str) -> None:
    """SQLite cannot alter a CHECK: copy an old `payment_batches` (no `immediate` trigger) into the new shape."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'payment_batches'").fetchone()
    if row is None or "'immediate'" in row[0]:
        return
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS payment_batches \(.*?\);", schema, re.S).group(0)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(ddl.replace("payment_batches", "payment_batches_new", 1))
        conn.execute("INSERT INTO payment_batches_new SELECT * FROM payment_batches")
        conn.execute("DROP TABLE payment_batches")
        conn.execute("ALTER TABLE payment_batches_new RENAME TO payment_batches")
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
