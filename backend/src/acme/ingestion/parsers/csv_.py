"""Deterministic CSV parser (F2, design D3): key/value or tabular-with-footer layout."""

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any

from acme.ingestion.schema import ExtractedInvoice

# Header/key synonyms -> ExtractedInvoice / line-item field names.
_FIELDS = {
    "invoice_number": "invoice_number", "invoice number": "invoice_number", "invoice": "invoice_number",
    "revision": "revision",
    "vendor": "vendor_name", "vendor_name": "vendor_name", "vendor address": "vendor_address",
    "vendor_address": "vendor_address",
    "date": "invoice_date", "invoice_date": "invoice_date", "invoice date": "invoice_date",
    "due_date": "due_date", "due date": "due_date",
    "currency": "currency",
    "subtotal": "subtotal", "tax": "tax", "tax_amount": "tax", "shipping": "shipping", "total": "total",
    "payment_terms": "payment_terms", "payment terms": "payment_terms", "notes": "notes",
}
_LINE_FIELDS = {
    "item": "raw_name", "description": "raw_name", "name": "raw_name",
    "quantity": "quantity", "qty": "quantity",
    "unit_price": "unit_price", "unit price": "unit_price", "price": "unit_price", "rate": "unit_price",
    "amount": "amount", "line total": "amount", "line_total": "amount",
    "note": "note",
}
_MONEY = {"subtotal", "tax", "shipping", "total", "unit_price", "amount"}


def parse_csv(text: str) -> ExtractedInvoice:
    """Parse an Acme CSV invoice; raises ValueError (incl. ValidationError)."""
    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("CSV has no rows")
    header = [cell.strip().lower() for cell in rows[0]]
    fields = _key_value(rows[1:]) if header == ["field", "value"] else _tabular(header, rows[1:])
    return ExtractedInvoice(**fields)


def _value(name: str, raw: str) -> Any:
    raw = raw.strip()
    if name in _MONEY:
        try:
            return Decimal(raw)
        except InvalidOperation:
            return raw  # kept as found; normalization parses or rejects it
    return raw


def _key_value(rows: list[list[str]]) -> dict[str, Any]:
    fields: dict[str, Any] = {"line_items": []}
    for row in rows:
        key, raw = row[0].strip().lower(), (row[1] if len(row) > 1 else "")
        if key in _LINE_FIELDS:
            name = _LINE_FIELDS[key]
            if name == "raw_name":
                fields["line_items"].append({})
            elif not fields["line_items"]:
                raise ValueError(f"line-item key {key!r} before any 'item' row")
            fields["line_items"][-1][name] = _value(name, raw)
        elif key in _FIELDS:
            fields[_FIELDS[key]] = _value(_FIELDS[key], raw)
    return fields


def _footer_label(row: list[str]) -> str | None:
    if len(row) >= 2 and not row[0].strip() and row[-2].strip().endswith(":"):
        return row[-2].strip()[:-1].strip().lower()
    return None


def _tabular(header: list[str], rows: list[list[str]]) -> dict[str, Any]:
    fields: dict[str, Any] = {"line_items": []}
    for row in rows:
        label = _footer_label(row)
        if label is not None:
            for prefix, name in (("subtotal", "subtotal"), ("tax", "tax"), ("shipping", "shipping"),
                                 ("total", "total")):
                if label.startswith(prefix):
                    fields[name] = _value(name, row[-1])
                    break
            continue
        line: dict[str, Any] = {}
        for column, raw in zip(header, row):
            if column in _LINE_FIELDS:
                line[_LINE_FIELDS[column]] = _value(_LINE_FIELDS[column], raw)
            elif column in _FIELDS and raw.strip():
                fields.setdefault(_FIELDS[column], _value(_FIELDS[column], raw))
        fields["line_items"].append(line)
    return fields
