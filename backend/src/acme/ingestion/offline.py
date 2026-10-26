"""Offline (`RuleBasedLLM`) extraction: regexes for the text layouts in the sample data.

Handles labelled lines (also typo labels such as `Vndr`, `Itms`, `Amt`, and two labels on
one line), `qty:`/`@` item lines, `- Name xN $P each` email lines, and fixed-width
`Qty Rate/Price Amount` tables. Like a real model it transcribes values as printed and
leaves cleanup to the normalizer. Registered for `ExtractedInvoice` on import.
"""

import re
from typing import Any

from langchain_core.messages import BaseMessage

from acme.ingestion.llm_extract import invoice_text_from
from acme.ingestion.schema import ExtractedInvoice
from acme.llm import register_handler

# Label alternatives, tried in order at each position (longer forms first).
_LABELS = [
    ("invoice_number", r"(?:invoice|inv)(?:\s*(?:number|no\.?))?\s*(?:#\s*:?|:)"),
    ("due_date", r"due(?:\s*(?:date|dt))?\s*:"),
    ("invoice_date", r"(?:date|dt)\s*:"),
    ("vendor_name", r"(?:vendor|vndr)\s*:"),
    ("from", r"from\s*:"),
    ("subtotal", r"sub\s*total\s*:"),
    ("tax", r"(?:sales\s+)?tax(?:\s*\([^)]*\))?\s*:"),
    ("shipping", r"shipping\s*:"),
    ("total", r"(?:grand\s+)?total(?:\s+amount)?\s*:|amt\s*:"),
    ("payment_terms", r"(?:payment|pymnt)\s+terms\s*:|terms\s*:"),
    ("notes", r"notes?\s*:"),
]
_LABEL_RE = re.compile(
    "|".join(rf"(?P<{name}>(?<![\w#-]){pattern})" for name, pattern in _LABELS), re.IGNORECASE
)

_MONEY = r"-?\$?\d[\d,Oo]*(?:\.[\dOo]+)?"
_QTY_LINE = re.compile(
    rf"^\s*(?P<name>\S.*?)\s+qty:?\s*(?P<qty>-?\d+)\s+(?:unit\s+price:?|@)\s*(?P<price>{_MONEY})",
    re.IGNORECASE,
)
_EMAIL_LINE = re.compile(rf"^\s*[-*]\s*(?P<name>\S.*?)\s+x\s*(?P<qty>-?\d+)\s+(?P<price>{_MONEY})", re.IGNORECASE)
_TABLE_HEADER = re.compile(r"\bqty\b.*\b(?:rate|price)\b", re.IGNORECASE)
_TABLE_ROW = re.compile(
    rf"^\s*(?P<name>\S.*?)\s+(?P<qty>-?\d+)\s+(?P<price>{_MONEY})\s+(?P<amount>{_MONEY})(?:\s+(?P<note>\S.*?))?\s*$"
)
_QUALIFIER = re.compile(r"^(?P<name>.*?)\s*\((?P<note>[^)]*)\)$")


def _labels(line: str) -> list[tuple[str, str]]:
    """(field, value) pairs on one line; a `notes` value runs to the end of the line."""
    matches = list(_LABEL_RE.finditer(line))
    pairs = []
    for i, match in enumerate(matches):
        field = match.lastgroup
        end = len(line) if field == "notes" or i + 1 == len(matches) else matches[i + 1].start()
        pairs.append((field, line[match.end():end].strip()))
        if field == "notes":
            break
    return pairs


def _item(name: str, qty: str, price: str, amount: str | None = None, note: str | None = None) -> dict:
    name = name.strip()
    if note is None and (qualifier := _QUALIFIER.match(name)):
        name, note = qualifier.group("name"), qualifier.group("note")
    return {"raw_name": name, "quantity": int(qty), "unit_price": price, "amount": amount, "note": note}


def extract_text(text: str) -> dict[str, Any]:
    """Regex extraction of a text invoice into an `ExtractedInvoice`-shaped dict."""
    fields: dict[str, Any] = {}
    items: list[dict] = []
    lines = text.splitlines()
    in_table = False
    i = 0
    while i < len(lines):
        line = lines[i]
        pairs = _labels(line)
        if pairs:
            in_table = False
            for field, value in pairs:
                if field == "notes":
                    notes = [value]
                    while i + 1 < len(lines) and lines[i + 1].strip() and not _labels(lines[i + 1]):
                        i += 1
                        notes.append(lines[i].strip())
                    value = " ".join(part for part in notes if part)
                if field == "from" and "@" in value:
                    continue
                if value:
                    fields.setdefault(field, value)
        elif in_table and (row := _TABLE_ROW.match(line)):
            items.append(_item(row["name"], row["qty"], row["price"], row["amount"], row["note"]))
        elif row := _QTY_LINE.match(line) or _EMAIL_LINE.match(line):
            items.append(_item(row["name"], row["qty"], row["price"]))
        elif _TABLE_HEADER.search(line):
            in_table = True
        elif not line.strip():
            in_table = False
        i += 1
    vendor = fields.pop("vendor_name", None) or fields.pop("from", None)
    fields.pop("from", None)
    return {**fields, "vendor_name": vendor, "line_items": items}


@register_handler(ExtractedInvoice)
def _offline_extraction(messages: list[BaseMessage]) -> dict[str, Any]:
    return extract_text(invoice_text_from(messages))
