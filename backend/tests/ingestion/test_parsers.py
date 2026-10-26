from decimal import Decimal
from pathlib import Path

import pytest

from acme.ingestion import ingest
from acme.ingestion.parsers import parse_csv, parse_json, parse_xml
from acme.normalization import normalize

INVOICES = Path(__file__).resolve().parents[3] / "data" / "invoices"
STRUCTURED = sorted(p.name for p in INVOICES.iterdir() if p.suffix in (".json", ".csv", ".xml"))


def _read(name: str) -> str:
    return (INVOICES / name).read_text()


def test_json_revised_invoice():
    inv = parse_json(_read("invoice_1004_revised.json"))
    assert inv.invoice_number == "INV-1004" and inv.revision == 1  # "R1"
    assert inv.vendor_name == "Precision Parts Ltd."
    assert inv.vendor_address == "742 Evergreen Terrace, Springfield, IL 62704"
    assert len(inv.line_items) == 3
    assert (inv.subtotal, inv.tax, inv.total) == (Decimal("5500.00"), Decimal("440.00"), Decimal("5940.00"))
    assert inv.currency == "USD" and inv.payment_terms == "Net 30"
    assert inv.notes == "Revised invoice - additional items added per PO amendment"


def test_json_line_notes_and_amounts():
    inv = parse_json(_read("invoice_1013.json"))
    assert len(inv.line_items) == 8
    fourth = inv.line_items[3]
    assert (fourth.raw_name, fourth.quantity, fourth.unit_price, fourth.amount, fourth.note) == \
        ("WidgetA", 5, Decimal("240.00"), Decimal("1200.00"), "Volume discount")


def test_json_bad_values_kept_as_found():
    inv = parse_json(_read("invoice_1009.json"))
    assert inv.vendor_name == "" and inv.vendor_address is None
    assert inv.due_date is None
    assert inv.line_items[0].quantity == -5
    assert inv.total == Decimal("-250.00") and inv.subtotal == Decimal("1000.00")


def test_csv_key_value_layout():
    inv = parse_csv(_read("invoice_1006.csv"))
    assert inv.invoice_number == "INV-1006" and inv.vendor_name == "Acme Industrial Supplies"
    assert [(i.raw_name, i.quantity, i.unit_price) for i in inv.line_items] == [
        ("WidgetA", 5, Decimal("250.00")), ("WidgetB", 3, Decimal("500.00"))]
    assert (inv.subtotal, inv.tax, inv.total) == (Decimal("2750.00"), Decimal("0.00"), Decimal("2750.00"))
    assert inv.invoice_date == "2026-01-25" and inv.payment_terms == "Net 15"


def test_csv_tabular_with_tax_footer():
    inv = parse_csv(_read("invoice_1007.csv"))
    assert len(inv.line_items) == 3
    assert [i.amount for i in inv.line_items] == [Decimal("5000.00"), Decimal("7500.00"), Decimal("2250.00")]
    assert (inv.subtotal, inv.tax, inv.total) == (Decimal("14750.00"), Decimal("885.00"), Decimal("15525.00"))
    assert (inv.invoice_number, inv.vendor_name, inv.invoice_date, inv.due_date) == \
        ("INV-1007", "MegaWidgets Corp", "01/28/2026", "02/28/2026")


def test_csv_tabular_1015():
    inv = parse_csv(_read("invoice_1015.csv"))
    assert len(inv.line_items) == 3 and inv.total == Decimal("6500.00") and inv.tax == Decimal("0.00")


def test_xml_euro_invoice():
    inv = parse_xml(_read("invoice_1014.xml"))
    assert inv.currency == "EUR" and inv.vendor_name == "TechParts International"
    assert [(i.raw_name, i.quantity, i.unit_price) for i in inv.line_items] == [
        ("WidgetA", 4, Decimal("225.00")), ("WidgetB", 6, Decimal("475.00"))]
    assert (inv.subtotal, inv.tax, inv.total) == (Decimal("3750.00"), Decimal("375.00"), Decimal("4125.00"))
    assert inv.payment_terms == "Net 30"


def test_structured_files_make_no_llm_calls(db):
    assert len(STRUCTURED) == 13
    for name in STRUCTURED:
        result = ingest(INVOICES / name, run_id=f"r-{name}")
        assert result.extracted is not None and result.attempts == 1, name
    assert db.execute("SELECT count(*) FROM llm_calls").fetchone()[0] == 0
    rows = db.execute("SELECT agent, event FROM audit_log").fetchall()
    assert len(rows) == 13 and {tuple(r) for r in rows} == {("ingestion", "extraction_attempt")}


def test_csv_quoted_numbers_with_thousands_separators(seeded_db):
    inv = parse_csv('Invoice Number,Item,Qty,Unit Price,Line Total\n'
                    'INV-1,WidgetA,"1,200",12.50,"15,000.00"\n,,,Total:,"15,000.00"\n')
    assert inv.line_items[0].quantity == 1200
    invoice, _ = normalize(inv)
    assert invoice.total == Decimal("15000.00") and invoice.line_items[0].amount == Decimal("15000.00")


@pytest.mark.parametrize("text", ["field,value\nitem,WidgetA\nquantity,many\ntotal,1\n"])
def test_csv_bad_quantity_raises_for_ingest_to_catch(text):
    with pytest.raises(ValueError):
        parse_csv(text)
