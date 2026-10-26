"""Reference data for `acme.db`: inventory, item aliases, approved vendors, and their payees.

Seeding upserts, so re-running restores reference rows without touching run data or learned payee data.
"""

import json
import sqlite3
from decimal import Decimal

from acme import payees
from acme.db import init_schema
from acme.payments._store import immediate

# Stock matches the case README; reference prices are inferred from the clean invoices.
INVENTORY = [
    ("WidgetA", 15, Decimal("250.00"), "widget"),
    ("WidgetB", 10, Decimal("500.00"), "widget"),
    ("GadgetX", 5, Decimal("750.00"), "gadget"),
    ("FakeItem", 0, None, None),
]

ITEM_ALIASES = [
    ("Widget A", "WidgetA"),
    ("Widget-A", "WidgetA"),
    ("Widget B", "WidgetB"),
    ("Widget-B", "WidgetB"),
    ("Gadget X", "GadgetX"),
    ("Gadget-X", "GadgetX"),
    ("Fake Item", "FakeItem"),
]

# Every vendor on the sample invoices except NoProd Industries (INV-1008), Fraudster LLC (INV-1003), and
# Apex Procurement Services (INV-1017), which must stay unknown. The last three are the split-invoicing
# fixture vendors (INV-1018 to INV-1022): approved, so only the payee threshold catches them.
VENDORS = [
    ("Widgets Inc.", []),
    ("Precision Parts Ltd.", []),
    ("Acme Industrial Supplies", []),
    ("Consolidated Materials Group", []),
    ("Summit Manufacturing Co.", []),
    ("QuickShip Distributers", ["QuickShip Distributers (formerly FastShip Ltd.)", "FastShip Ltd."]),
    ("TechParts International", []),
    ("Reliable Components Inc.", []),
    ("Gadgets Co.", []),
    ("Global Supply Chain Partners", []),
    ("MegaWidgets Corp", []),
    ("Atlas Industrial Supply", []),
    ("Northwind Fabrication LLC", ["Northwind Fabrication, LLC"]),
    ("Harbor Point Supply Co.", []),
    ("HPS Industrial Partners", []),
]

# Remit-to addresses printed on clean sample invoices; fixture vendors' addresses are learned from invoices.
PAYEE_ADDRESSES = [
    ("Widgets Inc.", "100 Main St, Chicago, IL 60601"),
    ("Precision Parts Ltd.", "742 Evergreen Terrace, Springfield, IL 62704"),
]


def seed(conn: sqlite3.Connection) -> None:
    """Create the schema and upsert the reference rows."""
    init_schema(conn)
    with conn:
        conn.executemany(
            "INSERT INTO inventory (item, stock, unit_price, category) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(item) DO UPDATE SET stock=excluded.stock, "
            "unit_price=excluded.unit_price, category=excluded.category",
            INVENTORY,
        )
        conn.executemany(
            "INSERT INTO item_aliases (alias, sku) VALUES (?, ?) "
            "ON CONFLICT(alias) DO UPDATE SET sku=excluded.sku",
            ITEM_ALIASES,
        )
        conn.executemany(
            "INSERT INTO vendors (name, aliases, status) VALUES (?, ?, 'approved') "
            "ON CONFLICT(name) DO UPDATE SET aliases=excluded.aliases, status='approved'",
            [(name, json.dumps(aliases)) for name, aliases in VENDORS],
        )
    _seed_payees(conn)


def _seed_payees(conn: sqlite3.Connection) -> None:
    """One payee per vendor (reusing a payee already holding its name) with its names and aliases, plus the
    known addresses. Only adds rows, so learned names, addresses, and ledger rows survive a re-seed."""
    with immediate(conn):
        payee_of = {}
        for name, aliases in VENDORS:
            row = conn.execute("SELECT payee_id FROM payee_names WHERE name_norm = ? ORDER BY payee_id LIMIT 1",
                               (payees.normalize_name(name),)).fetchone()
            if row is None:
                payee_of[name] = payees.create_payee(conn, name, "seed", [name, *aliases])
            else:
                payee_of[name] = row[0]
                payees.add_names(conn, row[0], [name, *aliases])
        for name, address in PAYEE_ADDRESSES:
            payees.add_address(conn, payee_of[name], address)
