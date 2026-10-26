from datetime import date
from decimal import Decimal

import pytest

from acme.models import FindingCode as C, Severity
from acme.normalization.fx import convert_currency
from acme.settings import get_settings
from acme.validation import ValidationContext, detect_duplicate, fraud_score
from acme.validation.checks import (
    check_duplicate, check_integrity, check_items, check_prices, check_stock, check_vendor, fraud_signals,
    reconcile_math,
)
from golden_invoices import GOLDEN, record_payment, record_processed


def codes(findings):
    return [f.code for f in findings]


# --- 2.1 inventory --------------------------------------------------------------------

def test_1002_stock_exceeded(ctx, golden):
    [f] = check_stock(golden["invoice_1002.txt"], ctx)
    assert (f.code, f.severity, f.evidence) == (C.STOCK_EXCEEDED, Severity.CRITICAL,
                                                {"sku": "GadgetX", "billed": 20, "stock": 5})


def test_1003_zero_stock(ctx, golden):
    assert codes(check_stock(golden["invoice_1003.txt"], ctx)) == [C.ZERO_STOCK]
    assert check_items(golden["invoice_1003.txt"], ctx) == []


def test_1008_unknown_items(ctx, golden):
    found = check_items(golden["invoice_1008.txt"], ctx)
    assert [(f.code, f.evidence["item"]) for f in found] == [(C.UNKNOWN_ITEM, "SuperGizmo"),
                                                             (C.UNKNOWN_ITEM, "MegaSprocket")]


def test_1010_repeated_lines_within_stock(ctx, golden):
    assert check_stock(golden["invoice_1010.txt"], ctx) == []


def test_1013_aggregated_per_sku(ctx, golden):
    found = check_stock(golden["invoice_1013.json"], ctx)
    assert {f.evidence["sku"]: (f.evidence["billed"], f.evidence["stock"]) for f in found} == {
        "WidgetA": (22, 15), "WidgetB": (18, 10), "GadgetX": (9, 5)}
    assert set(codes(found)) == {C.STOCK_EXCEEDED}


def test_1016_unknown_item(ctx, golden):
    [f] = check_items(golden["invoice_1016.json"], ctx)
    assert f.code == C.UNKNOWN_ITEM and f.evidence["item"] == "WidgetC"


def test_stock_not_consumed_between_invoices(ctx, golden):
    assert check_stock(golden["invoice_1001.txt"], ctx) == []
    assert check_stock(golden["invoice_1015.csv"], ctx) == []
    assert ValidationContext.load().inventory["WidgetA"].stock == 15


# --- 2.2 integrity --------------------------------------------------------------------

def test_1009_integrity(ctx, golden):
    found = check_integrity(golden["invoice_1009.json"], ctx)
    assert codes(found) == [C.MISSING_VENDOR, C.INVALID_QUANTITY, C.MISSING_DUE_DATE]
    assert found[1].evidence == {"line": 1, "item": "WidgetA", "quantity": -5}


def test_1003_relative_due_date(ctx, golden):
    [f] = check_integrity(golden["invoice_1003.txt"], ctx)
    assert (f.code, f.severity, f.evidence) == (C.INVALID_DUE_DATE, Severity.WARNING, {"due_date_raw": "yesterday"})


def test_1002_same_day_due_date_allowed(ctx, golden):
    assert check_integrity(golden["invoice_1002.txt"], ctx) == []


def test_due_before_invoice_date(ctx, golden):
    invoice = golden["invoice_1001.txt"].model_copy(update={"due_date": date(2026, 1, 14)})
    assert codes(check_integrity(invoice, ctx)) == [C.DUE_BEFORE_INVOICE_DATE]


def test_historical_invoice_not_past_due_by_wall_clock(ctx, golden):
    # 2026-02-01 is long past "today" in any later run; only the invoice date matters.
    assert check_integrity(golden["invoice_1001.txt"], ctx) == []


def test_zero_quantity_is_invalid(ctx, golden):
    invoice = golden["invoice_1001.txt"]
    invoice.line_items[0].quantity = 0
    assert codes(check_integrity(invoice, ctx)) == [C.INVALID_QUANTITY]


# --- 2.3 math -------------------------------------------------------------------------

def test_1009_math(ctx, golden):
    found = reconcile_math(golden["invoice_1009.json"], ctx)
    assert set(codes(found)) == {C.MATH_MISMATCH}
    assert found[0].evidence == {"check": "subtotal", "expected": "-250.00", "actual": "1000.00"}


@pytest.mark.parametrize("name", ["invoice_1010.txt", "invoice_1002.txt", "invoice_1001.txt", "invoice_1014.xml"])
def test_reconciles(ctx, golden, name):
    assert reconcile_math(golden[name], ctx) == []


def test_two_cents_over_is_flagged(ctx, golden):
    invoice = golden["invoice_1010.txt"].model_copy(update={"total": Decimal("7185.02")})
    [f] = reconcile_math(invoice, ctx)
    assert f.evidence == {"check": "total", "expected": "7185.00", "actual": "7185.02"}


def test_one_cent_off_is_flagged_sub_cent_is_not(ctx, golden):
    """Adversarial case (agent-workflow spec): a total off by $0.01 is a MATH_MISMATCH."""
    base = golden["invoice_1001.txt"]
    [f] = reconcile_math(base.model_copy(update={"total": Decimal("5000.01")}), ctx)
    assert (f.code, f.evidence) == (C.MATH_MISMATCH, {"check": "total", "expected": "5000.00", "actual": "5000.01"})
    assert reconcile_math(base.model_copy(update={"total": Decimal("5000.004")}), ctx) == []


def test_line_amount_mismatch(ctx, golden):
    invoice = golden["invoice_1010.txt"]
    invoice.line_items[0].amount = Decimal("2000.05")
    assert [f.evidence["check"] for f in reconcile_math(invoice, ctx)] == ["line_amount", "subtotal"]


# --- 2.4 vendor -----------------------------------------------------------------------

def test_1008_unknown_vendor(ctx, golden):
    [f] = check_vendor(golden["invoice_1008.txt"], ctx)
    assert (f.code, f.severity) == (C.UNKNOWN_VENDOR, Severity.WARNING)


@pytest.mark.parametrize("vendor", ["QuickShip Distributers", "QuickShip Distributers (formerly FastShip Ltd.)",
                                    "  quickship   distributers "])
def test_1012_renamed_vendor_matches(ctx, golden, vendor):
    assert check_vendor(golden["invoice_1012.pdf"].model_copy(update={"vendor_name": vendor}), ctx) == []


def test_missing_vendor_is_not_also_unknown(ctx, golden):
    assert check_vendor(golden["invoice_1009.json"], ctx) == []


# --- 2.5 duplicates and revisions -----------------------------------------------------

def test_1011_txt_duplicates_pdf(seeded_db, golden):
    record_processed(seeded_db, golden["invoice_1011.pdf"], "APPROVE", "r-pdf")
    [f] = check_duplicate(golden["invoice_1011.txt"], ValidationContext.load(seeded_db))
    assert (f.code, f.severity, f.evidence["original_run_id"]) == (C.DUPLICATE, Severity.CRITICAL, "r-pdf")


def test_1013_pdf_duplicates_rejected_json(seeded_db, golden):
    record_processed(seeded_db, golden["invoice_1013.json"], "REJECT", "r-json")
    [f] = check_duplicate(golden["invoice_1013.pdf"], ValidationContext.load(seeded_db))
    assert f.code == C.DUPLICATE and f.evidence["original_outcome"] == "REJECT"


def test_1004_revision_of_unpaid_original(seeded_db, golden):
    record_processed(seeded_db, golden["invoice_1004.json"], "APPROVE", "r-1004")
    findings, revision = detect_duplicate(golden["invoice_1004_revised.json"], ValidationContext.load(seeded_db))
    [f] = findings
    assert (f.code, f.severity) == (C.REVISION, Severity.INFO)
    assert f.evidence["original_run_id"] == "r-1004" and f.evidence["original_total"] == "1890.00"
    assert f.evidence["paid"] is False
    assert (revision.original_run_id, revision.original_outcome, revision.paid, revision.original_total) == (
        "r-1004", "APPROVE", False, Decimal("1890.00"))


def test_revision_of_paid_original_with_lower_total(seeded_db, golden):
    original = golden["invoice_1004.json"]
    record_processed(seeded_db, original, "APPROVE", "r-1004")
    record_payment(seeded_db, original)
    revision = golden["invoice_1004_revised.json"].model_copy(update={"total": Decimal("1500.00")})
    findings, ctx = detect_duplicate(revision, ValidationContext.load(seeded_db))
    assert codes(findings) == [C.REVISION, C.REVISION_CREDIT_DUE]
    assert findings[1].evidence["overpaid"] == "390.00" and findings[1].severity == Severity.WARNING
    assert ctx.paid and ctx.paid_amount == Decimal("1890.00")


def test_revision_of_paid_original_with_higher_total(seeded_db, golden):
    record_processed(seeded_db, golden["invoice_1004.json"], "APPROVE", "r-1004")
    record_payment(seeded_db, golden["invoice_1004.json"])
    findings, ctx = detect_duplicate(golden["invoice_1004_revised.json"], ValidationContext.load(seeded_db))
    assert codes(findings) == [C.REVISION] and ctx.paid


def test_paid_amount_sums_every_earlier_revision_and_delta(seeded_db, golden):
    """R0 paid 1890 and R1 paid a 4050 delta: R2 at 5000 is 940 below the 5940 already paid."""
    original = golden["invoice_1004.json"]
    r1 = golden["invoice_1004_revised.json"]
    record_processed(seeded_db, original, "APPROVE", "r-1004")
    record_payment(seeded_db, original)
    record_processed(seeded_db, r1, "APPROVE", "r-1004-r1")
    seeded_db.execute("INSERT INTO payments (idempotency_key, vendor, amount_usd, paid_at) VALUES (?, ?, ?, ?)",
                      ("precision parts ltd.|INV-1004|1|delta", r1.vendor_name, "4050.00", "2026-02-01"))
    seeded_db.commit()
    r2 = r1.model_copy(update={"revision": 2, "total": Decimal("5000.00")})
    findings, ctx = detect_duplicate(r2, ValidationContext.load(seeded_db))
    assert (ctx.original_run_id, ctx.paid, ctx.paid_amount) == ("r-1004-r1", True, Decimal("5940.00"))
    assert codes(findings) == [C.REVISION, C.REVISION_CREDIT_DUE]
    assert findings[1].evidence["overpaid"] == "940.00"


def test_same_number_new_total_without_revision(seeded_db, golden):
    record_processed(seeded_db, golden["invoice_1004.json"], "APPROVE", "r-1004")
    reused = golden["invoice_1004.json"].model_copy(update={"total": Decimal("2000.00")})
    [f] = check_duplicate(reused, ValidationContext.load(seeded_db))
    assert (f.code, f.severity, f.evidence["original_total"], f.evidence["total"]) == (
        C.INVOICE_NUMBER_REUSED, Severity.WARNING, "1890.00", "2000.00")


def test_first_sighting_has_no_finding(ctx, golden):
    assert detect_duplicate(golden["invoice_1001.txt"], ctx) == ([], None)


def test_duplicate_matched_through_vendor_alias(seeded_db, golden):
    record_processed(seeded_db, golden["invoice_1012.pdf"], "APPROVE", "r-pdf")
    alias = golden["invoice_1012.txt"].model_copy(update={"vendor_name": "FastShip Ltd."})
    assert codes(check_duplicate(alias, ValidationContext.load(seeded_db))) == [C.DUPLICATE]


# --- 6.1 / 6.2 price variance ----------------------------------------------------------

def test_1010_rush_price_flagged(ctx, golden):
    [f] = check_prices(golden["invoice_1010.txt"], ctx)
    assert (f.code, f.severity, f.evidence) == (C.PRICE_VARIANCE, Severity.WARNING, {
        "line": 4, "sku": "WidgetA", "billed": "300.00", "reference": "250.00", "pct": "+20.0"})


@pytest.mark.parametrize("name", ["invoice_1013.json", "invoice_1014.xml", "invoice_1003.txt", "invoice_1001.txt"])
def test_prices_within_tolerance_or_without_reference(ctx, golden, name):
    assert check_prices(golden[name], ctx) == []  # 1013 -4%; 1014 at 1.08; 1003 FakeItem has no reference


def _1014_in_eur():
    eur = GOLDEN["invoice_1014.xml"].model_dump()
    eur.update(currency="EUR", original_currency=None, original_total=None, total=Decimal("4125.00"),
               subtotal=Decimal("3750.00"), tax=Decimal("375.00"))
    eur["line_items"][0]["unit_price"], eur["line_items"][1]["unit_price"] = Decimal("225.00"), Decimal("475.00")
    return GOLDEN["invoice_1014.xml"].model_validate(eur)


def test_configured_eur_rate_keeps_1014_within_variance(ctx):
    rate = get_settings().fx_rates["EUR"]
    assert Decimal("1.00") <= rate <= Decimal("1.158")
    converted, _ = convert_currency(_1014_in_eur())
    assert check_prices(converted, ctx) == []


@pytest.mark.parametrize("rate,flagged", [("1.00", []), ("1.157", []), ("1.20", ["WidgetB"]), ("0.99", ["WidgetA"])])
def test_1014_variance_depends_on_rate(ctx, rate, flagged):
    # WidgetB EUR 475 crosses +10% of $500 just above 1.1578 USD/EUR.
    converted, _ = convert_currency(_1014_in_eur(), {"EUR": Decimal(rate)})
    assert [f.evidence["sku"] for f in check_prices(converted, ctx)] == flagged


# --- 6.3 / 6.4 fraud signals -------------------------------------------------------------

def test_1005_suspicious_address(ctx, golden):
    found = fraud_signals(golden["invoice_1005.json"], ctx)
    assert codes(found) == [C.SUSPICIOUS_ADDRESS] and found[0].severity == Severity.WARNING


def test_1004_fictional_address_not_flagged(ctx, golden):
    assert fraud_signals(golden["invoice_1004.json"], ctx) == []


def test_1012_near_threshold(ctx, golden):
    [f] = fraud_signals(golden["invoice_1012.pdf"], ctx)
    assert (f.code, f.severity) == (C.NEAR_THRESHOLD, Severity.INFO)


def test_1008_near_threshold_without_fraud(ctx, golden):
    assert codes(fraud_signals(golden["invoice_1008.txt"], ctx)) == [C.NEAR_THRESHOLD]


@pytest.mark.parametrize("total,near", [("9499.99", False), ("9500.00", True), ("9999.99", True),
                                        ("10000.00", False)])
def test_near_threshold_bounds(ctx, golden, total, near):
    invoice = golden["invoice_1001.txt"].model_copy(update={"total": Decimal(total)})
    assert (C.NEAR_THRESHOLD in codes(fraud_signals(invoice, ctx))) is near


def test_1003_fraud_suspected(ctx, golden):
    score, signals = fraud_score(golden["invoice_1003.txt"], ctx)
    assert score >= 0.60
    assert signals == ["urgency_language", "wire_transfer", "immediate_terms", "relative_due_date", "unknown_vendor"]
    [f] = fraud_signals(golden["invoice_1003.txt"], ctx)
    assert (f.code, f.severity, f.evidence["signals"]) == (C.FRAUD_SUSPECTED, Severity.CRITICAL, signals)


@pytest.mark.parametrize("name,expected", [("invoice_1005.json", 0.30), ("invoice_1008.txt", 0.30),
                                           ("invoice_1012.pdf", 0.10)])
def test_single_signals_stay_under_threshold(ctx, golden, name, expected):
    assert fraud_score(golden[name], ctx)[0] == pytest.approx(expected)


@pytest.mark.parametrize("name", ["invoice_1001.txt", "invoice_1004.json", "invoice_1004_revised.json",
                                  "invoice_1006.csv", "invoice_1011.pdf", "invoice_1014.xml", "invoice_1015.csv"])
def test_clean_invoices_score_zero(ctx, golden, name):
    assert fraud_score(golden[name], ctx) == (0, [])


def test_weights_and_threshold_come_from_settings(ctx, golden, monkeypatch):
    monkeypatch.setenv("FRAUD_THRESHOLD", "0.25")
    get_settings.cache_clear()
    assert C.FRAUD_SUSPECTED in codes(fraud_signals(golden["invoice_1005.json"], ctx))
