from datetime import date
from decimal import Decimal

import pytest

from acme.normalization.cleaners import (
    fix_ocr, normalize_invoice_number, normalize_revision, parse_date, parse_money,
)


@pytest.mark.parametrize("raw, fixed", [
    ("26-Jan-2O26", "26-Jan-2026"),
    ("$3,500.O0", "$3,500.00"),
    ("1O0", "100"),
    ("Sono Corp", "Sono Corp"),
    ("Oct 1 2026", "Oct 1 2026"),
    ("Net 30", "Net 30"),
])
def test_fix_ocr(raw, fixed):
    assert fix_ocr(raw) == fixed


def test_ocr_repaired_values_parse():
    assert parse_date(fix_ocr("26-Jan-2O26")) == date(2026, 1, 26)
    assert parse_money(fix_ocr("$3,500.O0")) == Decimal("3500.00")
    assert parse_money(fix_ocr("$3500.O0")) == Decimal("3500.00")  # extraction.v2 drops the comma


@pytest.mark.parametrize("raw, expected", [
    ("2026-01-30", date(2026, 1, 30)),
    ("01/28/2026", date(2026, 1, 28)),  # US month first
    ("02/03/2026", date(2026, 2, 3)),
    ("Jan 30 2026", date(2026, 1, 30)),
    ("January 27, 2026", date(2026, 1, 27)),
    ("February 26, 2026", date(2026, 2, 26)),
    ("26-Jan-2026", date(2026, 1, 26)),
    ("25-Feb-2026", date(2026, 2, 25)),
    ("Feb 3, 2026", date(2026, 2, 3)),  # dateutil fallback
    (date(2026, 1, 1), date(2026, 1, 1)),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["yesterday", "Today", "tomorrow", "ASAP", "immediately", "Upon receipt",
                                 "not a date", "", None])
def test_parse_date_refuses(raw):
    assert parse_date(raw) is None


@pytest.mark.parametrize("raw, expected", [
    ("$15,000.00", Decimal("15000.00")),
    ("1,234,567.89", Decimal("1234567.89")),
    (" $750 ", Decimal("750.00")),
    (Decimal("-250.00"), Decimal("-250.00")),
    (-250.0, Decimal("-250.00")),
    ("-250.00", Decimal("-250.00")),
    (1472.8, Decimal("1472.80")),
    ("€4,125.005", Decimal("4125.01")),
    (None, None),
    ("", None),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "$3,500.O0", "NaN"])
def test_parse_money_rejects(raw):
    with pytest.raises(ValueError):
        parse_money(raw)


@pytest.mark.parametrize("raw, expected", [
    ("1002", "INV-1002"), ("INV 1012", "INV-1012"), ("INV-1001", "INV-1001"), ("Inv #: 1002", "INV-1002"),
    ("#0042", "INV-0042"), ("PO 12 / 34", "PO 12 / 34"), ("ABC", "ABC"),
])
def test_invoice_number(raw, expected):
    assert normalize_invoice_number(raw) == expected


@pytest.mark.parametrize("raw, expected", [("r1", 1), ("R1", 1), ("Rev 2", 2), (None, 0), ("", 0), (0, 0), (3, 3)])
def test_revision(raw, expected):
    # The canonical model stores revision label "R<n>" as the integer n ("r1" -> R1 -> 1).
    assert normalize_revision(raw) == expected
