import json
import sqlite3
import subprocess
import sys
from decimal import Decimal
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
    assert len(TABLES) == 11
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
    for table, expected in (("inventory", 4), ("item_aliases", 7), ("vendors", 12), ("audit_log", 1)):
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
