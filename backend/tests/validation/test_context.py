from decimal import Decimal

import pytest

from acme.validation import ValidationContext
from golden_invoices import GOLDEN, record_payment, record_processed

PAID_VENDORS = ["Widgets Inc.", "Precision Parts Ltd.", "Acme Industrial Supplies", "Summit Manufacturing Co.",
                "QuickShip Distributers", "TechParts International", "Reliable Components Inc."]


def test_builds_from_a_seeded_db(seeded_db):
    ctx = ValidationContext.load(seeded_db)
    assert ctx.inventory["WidgetA"].stock == 15 and ctx.inventory["WidgetA"].unit_price == Decimal("250.00")
    assert ctx.inventory["FakeItem"].stock == 0 and ctx.inventory["FakeItem"].unit_price is None
    assert ctx.processed == () and ctx.payments == ()


def test_reads_processed_invoices_and_payments(seeded_db):
    invoice = GOLDEN["invoice_1004.json"]
    record_processed(seeded_db, invoice, "APPROVE", "r-1")
    record_payment(seeded_db, invoice)
    ctx = ValidationContext.load(seeded_db)
    [row] = ctx.processed
    assert (row.vendor, row.invoice_number, row.revision, row.outcome, row.run_id, row.total) == (
        "precision parts ltd.", "INV-1004", 0, "APPROVE", "r-1", Decimal("1890.00"))
    assert ctx.payments[0].amount_usd == Decimal("1890.00")


def test_is_read_only(seeded_db):
    ctx = ValidationContext.load(seeded_db)
    with pytest.raises(TypeError):
        ctx.inventory["WidgetA"] = None
    with pytest.raises(AttributeError):
        ctx.processed = ()


@pytest.mark.parametrize("vendor", [*PAID_VENDORS, "Global Supply Chain Partners"])
def test_golden_paid_vendors_are_seeded_as_approved(seeded_db, vendor):
    assert ValidationContext.load(seeded_db).approved_vendor(vendor) == vendor


def test_quickship_former_name_is_an_alias(seeded_db):
    ctx = ValidationContext.load(seeded_db)
    assert ctx.approved_vendor("FastShip Ltd.") == "QuickShip Distributers"
    assert ctx.approved_vendor("QuickShip Distributers (formerly FastShip Ltd.)") == "QuickShip Distributers"


@pytest.mark.parametrize("vendor", ["NoProd Industries", "Fraudster LLC"])
def test_unapproved_golden_vendors_are_absent(seeded_db, vendor):
    assert ValidationContext.load(seeded_db).approved_vendor(vendor) is None
    assert seeded_db.execute("SELECT 1 FROM vendors WHERE name = ?", (vendor,)).fetchone() is None


def test_lookalike_vendor_is_not_matched(seeded_db):
    assert ValidationContext.load(seeded_db).approved_vendor("Widgets Inс.") is None  # Cyrillic "с"
