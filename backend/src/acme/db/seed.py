"""Reference data for `acme.db`: inventory, item aliases, and approved vendors.

Seeding upserts, so re-running restores reference rows without touching run data.
"""

import json
import sqlite3
from decimal import Decimal

from acme.db import init_schema

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

# Every vendor on the sample invoices except NoProd Industries (INV-1008) and
# Fraudster LLC (INV-1003), which must stay unknown.
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
