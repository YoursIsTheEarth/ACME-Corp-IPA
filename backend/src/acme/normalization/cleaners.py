"""Deterministic cleanup of OCR noise, dates, money, and invoice numbers (F6, design D8-D10)."""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from dateutil import parser as dateutil_parser

CENT = Decimal("0.01")

# D8: only tokens made of digits, money punctuation, and O/o, holding at least one digit.
_OCR_TOKEN = re.compile(r"[\d$.,Oo-]+")


def fix_ocr(value: str) -> str:
    """Read the letter O/o as zero inside digit runs ("2O26" -> "2026"). For dates and money only."""
    return _OCR_TOKEN.sub(
        lambda m: re.sub("[Oo]", "0", m.group()) if any(c.isdigit() for c in m.group()) else m.group(),
        value,
    )


def parse_money(value: Decimal | int | float | str | None) -> Decimal | None:
    """Parse "$15,000.00", " 250 ", -250.00, ... to Decimal cents; negatives kept. Raises ValueError."""
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = re.sub(r"[\s$€£,]", "", value)
        if cleaned == "":
            return None
        try:
            value = Decimal(cleaned)
        except InvalidOperation:
            raise ValueError(f"not a money amount: {value!r}") from None
    elif isinstance(value, float):
        value = Decimal(str(value))
    amount = Decimal(value)
    if not amount.is_finite():
        raise ValueError(f"not a money amount: {value!r}")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%b %d %Y", "%B %d, %Y", "%d-%b-%Y")
RELATIVE_DATE_WORDS = ("yesterday", "today", "tomorrow", "asap", "immediately", "upon receipt")


def parse_date(value: date | str | None) -> date | None:
    """Parse the supported date forms (slash dates are US month-first); None if unparseable.

    Relative words ("yesterday", "ASAP", ...) are refused before any parser runs.
    """
    if value is None or isinstance(value, date):
        return value
    text = " ".join(value.split())
    if not text or is_relative_date(text):
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return dateutil_parser.parse(text, dayfirst=False, fuzzy=False).date()
    except (ValueError, OverflowError):
        return None


def is_relative_date(value: str | None) -> bool:
    return bool(value) and any(word in value.lower() for word in RELATIVE_DATE_WORDS)


def normalize_invoice_number(raw: str) -> str:
    """"1002", "INV 1012", "Inv #: 1002" -> "INV-<digits>"; kept as found unless exactly one digit run."""
    runs = re.findall(r"\d+", raw)
    if len(runs) == 1:
        return f"INV-{runs[0]}"
    return " ".join(raw.split())


def normalize_revision(raw: int | str | None) -> int:
    """"R1"/"r1"/"Rev 1"/1 -> 1; empty -> 0 (the original). The canonical model stores R<n> as n."""
    if raw is None or raw == "":
        return 0
    if isinstance(raw, int):
        return raw
    match = re.fullmatch(r"(?:r(?:ev(?:ision)?)?\.?\s*)?(\d+)", raw.strip(), re.IGNORECASE)
    if match is None:
        raise ValueError(f"unrecognized revision label: {raw!r}")
    return int(match.group(1))
