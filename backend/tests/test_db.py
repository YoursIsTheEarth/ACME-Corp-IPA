import json
import sqlite3
import subprocess
import sys
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

import pytest

from acme.db import TABLES, connect, init_schema
from acme.db.seed import seed

BACKEND = Path(__file__).resolve().parents[1]


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_schema_created_on_missing_file(tmp_path):
    path = tmp_path / "new" / "acme.db"
    path.parent.mkdir()
    conn = connect(path)
    init_schema(conn)
    assert path.exists()
    assert set(TABLES) <= _tables(conn)
    assert len(TABLES) == 16 and len(_tables(conn) & set(TABLES)) == 16
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(payment_queue)")}
    assert columns >= {"id", "run_id", "invoice_number", "revision", "vendor", "amount_usd", "kind",
                       "status", "attempts", "last_error", "queued_at", "batch_id"}
    conn.close()


def test_connect_pragmas(db):
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert isinstance(db.execute("SELECT 1 AS x").fetchone(), sqlite3.Row)


def test_init_schema_twice_keeps_rows(db):
    db.execute("INSERT INTO audit_log (run_id, ts, event) VALUES ('r-1', '2026-01-01', 'e')")
    db.commit()
    init_schema(db)
    assert db.execute("SELECT count(*) FROM audit_log").fetchone()[0] == 1


def _old_schema() -> str:
    """The schema as it was before `admin_settings` and the `immediate` trigger."""
    schema = files("acme.db").joinpath("schema.sql").read_text(encoding="utf-8")
    old = schema.replace("'idle', 'immediate', 'pay_all'", "'idle', 'pay_all'")
    old = old[:old.index("-- Operator settings")]
    assert old != schema and "immediate" not in old and "admin_settings" not in old
    return old


def test_init_schema_upgrades_an_old_database(tmp_path):
    conn = connect(tmp_path / "old.db")
    conn.executescript(_old_schema())
    conn.execute("INSERT INTO payment_batches (batch_id, trigger, released_by, started_at, count, total_usd) "
                 "VALUES ('B-0001', 'pay_all', 'Dana', '2026-01-15T17:00:00', 2, '7750.00')")
    conn.execute("INSERT INTO audit_log (run_id, ts, event) VALUES ('r-1', '2026-01-01', 'e')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO payment_batches (batch_id, trigger, released_by, started_at) "
                     "VALUES ('B-0002', 'immediate', 'System', 'x')")
    init_schema(conn)
    assert set(TABLES) <= _tables(conn) and "payment_batches_new" not in _tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM admin_settings").fetchone()[0] == 0
    assert dict(conn.execute("SELECT batch_id, trigger, released_by, count, total_usd FROM payment_batches")
                .fetchone()) == {"batch_id": "B-0001", "trigger": "pay_all", "released_by": "Dana", "count": 2,
                                 "total_usd": "7750.00"}
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1
    conn.execute("INSERT INTO payment_batches (batch_id, trigger, released_by, started_at) "
                 "VALUES ('B-0002', 'immediate', 'System', 'x')")
    conn.commit()
    init_schema(conn)  # repeatable after the rebuild
    assert conn.execute("SELECT COUNT(*) FROM payment_batches").fetchone()[0] == 2
    conn.close()


def test_init_schema_adds_payee_tables_to_an_older_database(tmp_path):
    schema = files("acme.db").joinpath("schema.sql").read_text(encoding="utf-8")
    conn = connect(tmp_path / "older.db")
    conn.executescript(schema[:schema.index("-- Payee registry")])
    conn.execute("INSERT INTO audit_log (run_id, ts, event) VALUES ('r-1', '2026-01-01', 'e')")
    conn.execute("INSERT INTO invoice_runs (id, file_name, uploaded_at, status) "
                 "VALUES ('r-1', 'a.txt', 'x', 'Uploaded')")
    conn.commit()
    payee_tables = {"payees", "payee_names", "payee_addresses", "payee_invoices"}
    assert not payee_tables & _tables(conn)
    init_schema(conn)
    assert payee_tables <= _tables(conn)
    for table in ("audit_log", "invoice_runs"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
    init_schema(conn)  # repeatable
    conn.close()


def test_fresh_schema_accepts_immediate_and_rejects_unknown_triggers(db):
    sql = "INSERT INTO payment_batches (batch_id, trigger, released_by, started_at) VALUES (?, ?, 'System', 'x')"
    db.execute(sql, ("B-0001", "immediate"))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, ("B-0002", "cli"))


def test_duplicate_idempotency_key_rejected(db):
    sql = "INSERT INTO payments (idempotency_key, vendor, amount_usd, paid_at) VALUES (?, ?, ?, ?)"
    db.execute(sql, ("widgets inc.|INV-1001|0", "Widgets Inc.", Decimal("5000.00"), "2026-01-15T17:00:00"))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, ("widgets inc.|INV-1001|0", "Widgets Inc.", Decimal("5000.00"), "2026-01-15T17:01:00"))
    assert db.execute("SELECT amount_usd FROM payments").fetchone()[0] == "5000.00"


def test_processed_invoice_key_unique(db):
    sql = "INSERT INTO processed_invoices (vendor, invoice_number, revision) VALUES (?, ?, ?)"
    db.execute(sql, ("Precision Parts Ltd.", "INV-1004", 0))
    db.execute(sql, ("Precision Parts Ltd.", "INV-1004", 1))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, ("Precision Parts Ltd.", "INV-1004", 1))


def test_seed_stock_values(db):
    seed(db)
    rows = {r["item"]: (r["stock"], r["unit_price"]) for r in db.execute("SELECT * FROM inventory")}
    assert rows == {
        "WidgetA": (15, "250.00"),
        "WidgetB": (10, "500.00"),
        "GadgetX": (5, "750.00"),
        "FakeItem": (0, None),
    }
    aliases = dict(db.execute("SELECT alias, sku FROM item_aliases").fetchall())
    assert aliases["Widget A"] == "WidgetA" and aliases["Gadget X"] == "GadgetX"


def test_seed_repeatable_and_keeps_run_data(db):
    seed(db)
    db.execute("INSERT INTO audit_log (run_id, ts, event) VALUES ('r-1', '2026-01-01', 'e')")
    db.execute("UPDATE inventory SET stock = 99 WHERE item = 'WidgetA'")
    db.commit()
    seed(db)
    for table, expected in (("inventory", 4), ("item_aliases", 7), ("vendors", 15), ("audit_log", 1)):
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == expected
    assert db.execute("SELECT stock FROM inventory WHERE item='WidgetA'").fetchone()[0] == 15


def _vendor_for(db, name):
    row = db.execute(
        "SELECT v.name FROM vendors v WHERE v.status = 'approved' AND (v.name = ?1 "
        "OR EXISTS (SELECT 1 FROM json_each(v.aliases) WHERE json_each.value = ?1))",
        (name,),
    ).fetchone()
    return row[0] if row else None


def test_vendor_seed(db):
    seed(db)
    assert _vendor_for(db, "FastShip Ltd.") == "QuickShip Distributers"
    assert _vendor_for(db, "QuickShip Distributers (formerly FastShip Ltd.)") == "QuickShip Distributers"
    assert _vendor_for(db, "Atlas Industrial Supply") == "Atlas Industrial Supply"
    assert _vendor_for(db, "NoProd Industries") is None
    assert _vendor_for(db, "Fraudster LLC") is None
    assert _vendor_for(db, "Apex Procurement Services") is None
    for name in ("Northwind Fabrication LLC", "Harbor Point Supply Co.", "HPS Industrial Partners"):
        assert _vendor_for(db, name) == name  # split-invoicing fixture vendors look legitimate
    assert _vendor_for(db, "Northwind Fabrication, LLC") == "Northwind Fabrication LLC"  # INV-1020's spelling
    assert json.loads(db.execute("SELECT aliases FROM vendors WHERE name='Widgets Inc.'").fetchone()[0]) == []


def test_unknown_items_absent(db):
    seed(db)
    for item in ("SuperGizmo", "MegaSprocket", "WidgetC"):
        assert db.execute("SELECT 1 FROM inventory WHERE item = ?", (item,)).fetchone() is None


def test_seed_command(tmp_path):
    env_path = str(BACKEND / "src")
    result = subprocess.run(
        [sys.executable, "-m", "acme.db", "seed"],
        cwd=tmp_path, capture_output=True, text=True,
        env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    conn = connect(tmp_path / "acme.db")
    assert conn.execute("SELECT count(*) FROM inventory").fetchone()[0] == 4
    conn.close()
