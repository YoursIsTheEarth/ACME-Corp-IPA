"""Hand-coded canonical `Invoice` for each golden file (what ingestion + normalization produce).

Lets validation and approval tests run without extraction or an LLM. `GOLDEN_FILES` is the
sorted filename order the golden batch uses.
"""

import dataclasses
from datetime import date
from decimal import Decimal

from acme.models import Invoice, LineItem
from acme.validation.address import assess_address

D = Decimal


def _line(sku, qty, price, amount=None, note=None, raw=None):
    return LineItem(sku=sku, raw_name=raw or sku, quantity=qty, unit_price=D(price),
                    amount=None if amount is None else D(amount), note=note)


def _inv(number, vendor, invoice_date, due, lines, total, subtotal=None, tax="0.00", shipping="0.00", **kw):
    return Invoice(
        invoice_number=number, vendor_name=vendor, invoice_date=date.fromisoformat(invoice_date),
        due_date=None if due is None else date.fromisoformat(due), line_items=lines, total=D(total),
        subtotal=None if subtotal is None else D(subtotal), tax=D(tax), shipping=D(shipping), **kw,
    )


_INV_1004_LINES = [_line("WidgetA", 3, "250.00"), _line("WidgetB", 2, "500.00")]
_EVERGREEN = "742 Evergreen Terrace, Springfield, IL 62704"

_INV_1011 = dict(lines=[_line("WidgetA", 6, "250.00", "1500.00"), _line("WidgetB", 3, "500.00", "1500.00")])
_INV_1012_LINES = [
    _line("WidgetA", 12, "250.00", "3000.00", raw="Widget A"),
    _line("WidgetB", 7, "500.00", "3500.00"),
    _line("GadgetX", 4, "750.00", "3000.00", raw="Gadget X"),
]
_INV_1012_NOTES = "Ref PO-20260115. Deliver to warehouse dock B. Contact Jim at ext 4421 with questions."
_INV_1013_LINES = [
    _line("WidgetA", 15, "250.00", "3750.00"),
    _line("WidgetB", 10, "500.00", "5000.00"),
    _line("GadgetX", 5, "750.00", "3750.00"),
    _line("WidgetA", 5, "240.00", "1200.00", "Volume discount"),
    _line("WidgetB", 8, "480.00", "3840.00", "Volume discount"),
    _line("GadgetX", 3, "750.00", "2250.00", "Expedited"),
    _line("WidgetA", 2, "250.00", "500.00", "Replacement"),
    _line("GadgetX", 1, "750.00", "750.00", "Sample"),
]

GOLDEN: dict[str, Invoice] = {
    "invoice_1001.txt": _inv("INV-1001", "Widgets Inc.", "2026-01-15", "2026-02-01",
                             [_line("WidgetA", 10, "250.00"), _line("WidgetB", 5, "500.00")],
                             "5000.00", "5000.00", payment_terms="Net 15"),
    "invoice_1002.txt": _inv("INV-1002", "Gadgets Co.", "2026-01-30", "2026-01-30",
                             [_line("GadgetX", 20, "750.00")], "15000.00", payment_terms="Net 30"),
    "invoice_1003.txt": _inv("INV-1003", "Fraudster LLC", "2026-01-20", None,
                             [_line("FakeItem", 100, "1000.00")], "100000.00", due_date_raw="yesterday",
                             payment_terms="Immediate",
                             notes="URGENT - Pay immediately to avoid penalties!!! Wire transfer preferred."),
    "invoice_1004.json": _inv("INV-1004", "Precision Parts Ltd.", "2026-01-22", "2026-02-22", _INV_1004_LINES,
                              "1890.00", "1750.00", "140.00", vendor_address=_EVERGREEN, payment_terms="Net 30"),
    "invoice_1004_revised.json": _inv(
        "INV-1004", "Precision Parts Ltd.", "2026-01-22", "2026-02-22",
        [*_INV_1004_LINES, _line("GadgetX", 5, "750.00")], "5940.00", "5500.00", "440.00", revision=1,
        vendor_address=_EVERGREEN, payment_terms="Net 30",
        notes="Revised invoice - additional items added per PO amendment"),
    "invoice_1005.json": _inv(
        "INV-1005", "Global Supply Chain Partners", "2026-01-18", "2026-03-18",
        [_line("WidgetA", 14, "250.00"), _line("GadgetX", 8, "750.00"), _line("WidgetB", 10, "500.00")],
        "15225.00", "14500.00", "725.00", vendor_address="1600 Pennsylvania Ave, Washington, DC 20500",
        payment_terms="Net 60"),
    "invoice_1006.csv": _inv("INV-1006", "Acme Industrial Supplies", "2026-01-25", "2026-02-10",
                             [_line("WidgetA", 5, "250.00"), _line("WidgetB", 3, "500.00")],
                             "2750.00", "2750.00", payment_terms="Net 15"),
    "invoice_1007.csv": _inv(
        "INV-1007", "MegaWidgets Corp", "2026-01-28", "2026-02-28",
        [_line("WidgetA", 20, "250.00", "5000.00"), _line("WidgetB", 15, "500.00", "7500.00"),
         _line("GadgetX", 3, "750.00", "2250.00")],
        "15525.00", "14750.00", "885.00"),
    "invoice_1008.txt": _inv(
        "INV-1008", "NoProd Industries", "2026-01-10", "2026-01-20",
        [_line(None, 12, "400.00", raw="SuperGizmo"), _line(None, 6, "850.00", raw="MegaSprocket")], "9900.00"),
    "invoice_1009.json": _inv("INV-1009", "", "2026-01-15", None,
                              [_line("WidgetA", -5, "250.00"), _line("WidgetB", 2, "500.00")],
                              "-250.00", "1000.00", payment_terms=""),
    "invoice_1010.txt": _inv(
        "INV-1010", "Consolidated Materials Group", "2026-01-27", "2026-02-26",
        [_line("WidgetA", 8, "250.00", "2000.00"), _line("WidgetB", 4, "500.00", "2000.00"),
         _line("GadgetX", 2, "750.00", "1500.00"), _line("WidgetA", 4, "300.00", "1200.00", "rush order")],
        "7185.00", "6700.00", "335.00", "150.00", payment_terms="Net 30"),
    "invoice_1011.pdf": _inv("INV-1011", "Summit Manufacturing Co.", "2026-01-20", "2026-02-20",
                             _INV_1011["lines"], "3000.00"),
    "invoice_1011.txt": _inv("INV-1011", "Summit Manufacturing Co.", "2026-01-20", "2026-02-20",
                             _INV_1011["lines"], "3000.00", "3000.00", payment_terms="Net 30"),
    "invoice_1012.pdf": _inv("INV-1012", "QuickShip Distributers", "2026-01-26", "2026-02-25", _INV_1012_LINES,
                             "9975.00", "9500.00", "475.00", payment_terms="Net 30", notes=_INV_1012_NOTES),
    "invoice_1012.txt": _inv("INV-1012", "QuickShip Distributers", "2026-01-26", "2026-02-25", _INV_1012_LINES,
                             "9975.00", "9500.00", "475.00", payment_terms="Net 30", notes=_INV_1012_NOTES),
    "invoice_1013.json": _inv("INV-1013", "Atlas Industrial Supply", "2026-01-24", "2026-03-24", _INV_1013_LINES,
                              "22562.80", "21040.00", "1472.80",
                              vendor_address="500 Commerce Blvd, Detroit, MI 48201", payment_terms="Net 60"),
    "invoice_1013.pdf": _inv("INV-1013", "Atlas Industrial Supply", "2026-01-24", "2026-03-24", _INV_1013_LINES,
                             "22562.80", "21040.00", "1472.80", payment_terms="Net 60"),
    # EUR 225 / 475 converted at the default 1.08 USD per EUR.
    "invoice_1014.xml": _inv("INV-1014", "TechParts International", "2026-01-26", "2026-02-26",
                             [_line("WidgetA", 4, "243.00"), _line("WidgetB", 6, "513.00")],
                             "4455.00", "4050.00", "405.00", original_currency="EUR",
                             original_total=D("4125.00"), payment_terms="Net 30"),
    "invoice_1015.csv": _inv(
        "INV-1015", "Reliable Components Inc.", "2026-01-29", "2026-02-28",
        [_line("WidgetA", 10, "250.00", "2500.00"), _line("WidgetB", 5, "500.00", "2500.00"),
         _line("GadgetX", 2, "750.00", "1500.00")],
        "6500.00", "6500.00"),
    "invoice_1016.json": _inv(
        "INV-1016", "Widgets Inc.", "2026-01-27", "2026-02-27",
        [_line("WidgetA", 4, "250.00", "1000.00"), _line("WidgetB", 2, "500.00", "1000.00"),
         _line(None, 3, "350.00", "1050.00", raw="WidgetC")],
        "3233.00", "3050.00", "183.00", vendor_address="100 Main St, Chicago, IL 60601", payment_terms="Net 30"),
}
GOLDEN_FILES = sorted(GOLDEN)

# Key finding codes per file from the test plan (validation's share; SUPERSEDED_BY_REVISION is
# set by payment processing). Duplicates assume the files ran in GOLDEN_FILES order.
KEY_CODES: dict[str, set[str]] = {
    "invoice_1001.txt": set(),
    "invoice_1002.txt": {"STOCK_EXCEEDED"},
    "invoice_1003.txt": {"ZERO_STOCK", "INVALID_DUE_DATE", "FRAUD_SUSPECTED"},
    "invoice_1004.json": set(),
    "invoice_1004_revised.json": {"REVISION"},
    "invoice_1005.json": {"STOCK_EXCEEDED", "SUSPICIOUS_ADDRESS"},
    "invoice_1006.csv": set(),
    "invoice_1007.csv": {"STOCK_EXCEEDED"},
    "invoice_1008.txt": {"UNKNOWN_ITEM", "UNKNOWN_VENDOR"},
    "invoice_1009.json": {"MISSING_VENDOR", "INVALID_QUANTITY", "MATH_MISMATCH", "MISSING_DUE_DATE"},
    "invoice_1010.txt": {"PRICE_VARIANCE"},
    "invoice_1011.pdf": set(),
    "invoice_1011.txt": {"DUPLICATE"},
    "invoice_1012.pdf": {"NEAR_THRESHOLD"},
    "invoice_1012.txt": {"DUPLICATE"},
    "invoice_1013.json": {"STOCK_EXCEEDED"},
    "invoice_1013.pdf": {"DUPLICATE"},
    "invoice_1014.xml": set(),  # CURRENCY_CONVERTED comes from normalization
    "invoice_1015.csv": set(),
    "invoice_1016.json": {"UNKNOWN_ITEM"},
}

REJECTED = {"invoice_1002.txt", "invoice_1003.txt", "invoice_1005.json", "invoice_1007.csv", "invoice_1008.txt",
            "invoice_1009.json", "invoice_1011.txt", "invoice_1012.txt", "invoice_1013.json", "invoice_1013.pdf",
            "invoice_1016.json"}
EXPECTED_OUTCOME = {name: "REJECT" if name in REJECTED else "NEEDS_REVIEW" if name == "invoice_1010.txt"
                    else "APPROVE" for name in GOLDEN_FILES}


def record_processed(conn, invoice: Invoice, outcome: str, run_id: str) -> None:
    """Stand-in for disposition: the `invoice_runs` total and the `processed_invoices` row."""
    from acme.validation import ValidationContext, content_hash

    vendor = ValidationContext.load(conn).vendor_key(invoice.vendor_name)
    conn.execute("INSERT INTO invoice_runs (id, file_name, uploaded_at, status, total_usd) VALUES (?, ?, ?, ?, ?)",
                 (run_id, run_id, "2026-01-31T00:00:00+00:00", "done", invoice.total))
    conn.execute("INSERT OR IGNORE INTO processed_invoices (vendor, invoice_number, revision, content_hash, "
                 "outcome, run_id) VALUES (?, ?, ?, ?, ?, ?)",
                 (vendor, invoice.invoice_number, invoice.revision, content_hash(invoice), outcome, run_id))
    conn.commit()


def record_payment(conn, invoice: Invoice, amount=None) -> None:
    """A `payments` ledger row using payment-processing's key: vendor|invoice_number|revision."""
    key = f"{invoice.vendor_name.strip().casefold()}|{invoice.invoice_number}|{invoice.revision}"
    conn.execute("INSERT INTO payments (idempotency_key, vendor, amount_usd, paid_at) VALUES (?, ?, ?, ?)",
                 (key, invoice.vendor_name, amount if amount is not None else invoice.total, "2026-01-31"))
    conn.commit()


def assessed(ctx, invoice: Invoice):
    """`ctx` with the (fake) model's address verdict for `invoice`, as `run_validation` builds it."""
    return dataclasses.replace(ctx, address_assessment=assess_address(invoice))
