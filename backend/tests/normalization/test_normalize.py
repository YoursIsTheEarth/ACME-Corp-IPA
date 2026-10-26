from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from acme.ingestion import ExtractedInvoice, ingest
from acme.llm import register_handler
from acme.logging import read_trace
from acme.models import FindingCode, Invoice
from acme.normalization import normalize
from acme.normalization.llm_fallback import DateSuggestion, SkuSuggestion

INVOICES = Path(__file__).resolve().parents[3] / "data" / "invoices"


def run(name: str, run_id: str = "r-n"):
    result = ingest(INVOICES / name, run_id=run_id)
    assert result.extracted is not None, result.findings
    return normalize(result.extracted, run_id=run_id)


def normalizer_calls(db) -> int:
    return db.execute("SELECT count(*) FROM llm_calls WHERE agent = 'normalizer'").fetchone()[0]


@pytest.fixture
def fallback_handlers():
    def install(sku=None, when=None):
        register_handler(SkuSuggestion, lambda messages: SkuSuggestion(sku=sku))
        register_handler(DateSuggestion, lambda messages: DateSuggestion(date=when))
    yield install
    install()  # back to the offline "no suggestion" handlers


def test_1012_ocr_repairs_and_aliases(seeded_db):
    invoice, findings = run("invoice_1012.pdf", "r-1012")
    assert isinstance(invoice, Invoice) and findings == []
    assert invoice.invoice_number == "INV-1012" and invoice.invoice_date == date(2026, 1, 26)
    assert [(i.raw_name, i.sku) for i in invoice.line_items] == [
        ("Widget A", "WidgetA"), ("WidgetB", "WidgetB"), ("Gadget X", "GadgetX")]
    assert invoice.line_items[1].amount == Decimal("3500.00")
    [entry] = [t for t in read_trace("r-1012") if t["agent"] == "normalizer"]
    assert entry["payload"]["ocr_repairs"] == [
        {"field": "invoice_date", "before": "26-Jan-2O26", "after": "26-Jan-2026"},
        {"field": "line_items[1].amount", "before": "$3,500.O0", "after": "$3,500.00"},
    ]
    assert [m["method"] for m in entry["payload"]["sku_matches"]] == ["exact", "exact", "exact"]


def test_free_text_not_altered(seeded_db):
    extracted = ExtractedInvoice(invoice_number="INV-7", vendor_name="Sono  Corp", total="$1O.00",
                                 notes="Ship to dock O, door 2O")
    invoice, _ = normalize(extracted)
    assert invoice.vendor_name == "Sono Corp"  # whitespace collapsed, letters untouched
    assert invoice.notes == "Ship to dock O, door 2O"
    assert invoice.total == Decimal("10.00")


def test_qualifier_does_not_block_match(seeded_db):
    invoice, _ = run("invoice_1010.txt")
    last = invoice.line_items[-1]
    assert (last.raw_name, last.note, last.sku) == ("WidgetA", "rush order", "WidgetA")
    assert (invoice.invoice_date, invoice.due_date) == (date(2026, 1, 27), date(2026, 2, 26))
    assert (invoice.subtotal, invoice.tax, invoice.shipping, invoice.total) == (
        Decimal("6700.00"), Decimal("335.00"), Decimal("150.00"), Decimal("7185.00"))


def test_unknown_items_keep_raw_names(seeded_db):
    invoice, findings = run("invoice_1008.txt")
    assert [(i.raw_name, i.sku) for i in invoice.line_items] == [("SuperGizmo", None), ("MegaSprocket", None)]
    assert findings == []  # UNKNOWN_ITEM belongs to validation
    invoice, _ = run("invoice_1016.json")
    assert invoice.line_items[2].raw_name == "WidgetC" and invoice.line_items[2].sku is None


def test_us_slash_and_month_name_dates(seeded_db):
    invoice, _ = run("invoice_1007.csv")
    assert (invoice.invoice_date, invoice.due_date) == (date(2026, 1, 28), date(2026, 2, 28))
    invoice, _ = run("invoice_1002.txt")
    assert (invoice.invoice_date, invoice.due_date) == (date(2026, 1, 30), date(2026, 1, 30))
    assert invoice.invoice_number == "INV-1002" and invoice.total == Decimal("15000.00")


def test_relative_due_date_kept_raw(seeded_db):
    invoice, findings = run("invoice_1003.txt")
    assert invoice.due_date is None and invoice.due_date_raw == "yesterday"
    assert findings == []
    assert normalizer_calls(seeded_db) == 0  # relative words never go to the LLM


def test_null_due_date_and_negative_total(seeded_db):
    invoice, findings = run("invoice_1009.json")
    assert invoice.due_date is None and invoice.due_date_raw is None and findings == []
    assert invoice.total == Decimal("-250.00") and invoice.line_items[0].quantity == -5
    assert invoice.vendor_name == ""


def test_revision_normalized(seeded_db):
    invoice, _ = run("invoice_1004_revised.json")
    assert (invoice.invoice_number, invoice.revision) == ("INV-1004", 1)
    invoice, _ = normalize(ExtractedInvoice(invoice_number="1004", revision="r1", total="1"))
    assert invoice.revision == 1


@pytest.mark.parametrize("pdf, txt", [("invoice_1011.pdf", "invoice_1011.txt"),
                                      ("invoice_1012.pdf", "invoice_1012.txt")])
def test_same_invoice_in_two_formats(seeded_db, pdf, txt):
    a, _ = run(pdf)
    b, _ = run(txt)
    assert (a.invoice_number, a.vendor_name, a.total) == (b.invoice_number, b.vendor_name, b.total)


def test_clean_invoice_needs_no_llm(seeded_db):
    invoice, findings = run("invoice_1015.csv")
    assert all(i.sku for i in invoice.line_items) and findings == []
    assert normalizer_calls(seeded_db) == 0


def test_llm_sku_must_exist_in_inventory(seeded_db, fallback_handlers):
    fallback_handlers(sku="SuperGizmoPro")
    invoice, _ = normalize(ExtractedInvoice(invoice_number="1", total="1",
                                            line_items=[{"raw_name": "SuperGizmo", "quantity": 1}]),
                           run_id="r-llm")
    assert invoice.line_items[0].sku is None
    assert normalizer_calls(seeded_db) == 1
    [entry] = [t for t in read_trace("r-llm") if t["agent"] == "normalizer"]
    assert entry["payload"]["sku_matches"][0]["method"] == "none"


def test_llm_sku_accepted_when_in_inventory(seeded_db, fallback_handlers):
    fallback_handlers(sku="WidgetB")
    invoice, _ = normalize(ExtractedInvoice(invoice_number="1", total="1",
                                            line_items=[{"raw_name": "Blue widget", "quantity": 1}]),
                           run_id="r-llm")
    assert invoice.line_items[0].sku == "WidgetB"
    [entry] = [t for t in read_trace("r-llm") if t["agent"] == "normalizer"]
    assert entry["payload"]["sku_matches"][0]["method"] == "llm"


def test_llm_date_fallback(seeded_db, fallback_handlers):
    extracted = ExtractedInvoice(invoice_number="1", total="1", due_date="the third of March 2026")
    invoice, _ = normalize(extracted)
    assert invoice.due_date is None and invoice.due_date_raw == "the third of March 2026"
    fallback_handlers(when=date(2026, 3, 3))
    invoice, _ = normalize(extracted)
    assert invoice.due_date == date(2026, 3, 3) and invoice.due_date_raw is None
    assert normalizer_calls(seeded_db) == 2


def test_unparseable_total_fails_closed(seeded_db):
    invoice, findings = normalize(ExtractedInvoice(invoice_number="1", total="lots"))
    assert invoice is None
    assert [f.code for f in findings] == [FindingCode.EXTRACTION_FAILED]
