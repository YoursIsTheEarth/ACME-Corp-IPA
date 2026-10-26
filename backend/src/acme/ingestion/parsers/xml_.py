"""Deterministic XML parser (F2) for the `<invoice><header/><line_items/><totals/></invoice>` layout."""

import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from acme.ingestion.schema import ExtractedInvoice


def _text(root: ET.Element, *paths: str) -> str | None:
    for path in paths:
        node = root.find(path)
        if node is not None and node.text is not None:
            return node.text.strip()
    return None


def _money(raw: str | None) -> Decimal | str | None:
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return raw


def parse_xml(text: str) -> ExtractedInvoice:
    """Parse an Acme XML invoice; raises ValueError (incl. ParseError/ValidationError)."""
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise ValueError(f"XML parse error: {exc}") from exc
    return ExtractedInvoice(
        invoice_number=_text(root, "header/invoice_number", "invoice_number"),
        revision=_text(root, "header/revision", "revision") or 0,
        vendor_name=_text(root, "header/vendor", "header/vendor/name", "vendor"),
        vendor_address=_text(root, "header/vendor_address", "header/vendor/address"),
        invoice_date=_text(root, "header/date", "date"),
        due_date=_text(root, "header/due_date", "due_date"),
        currency=_text(root, "header/currency", "currency"),
        line_items=[
            {
                "raw_name": _text(item, "name", "item", "description"),
                "quantity": _text(item, "quantity"),
                "unit_price": _money(_text(item, "unit_price")),
                "amount": _money(_text(item, "amount")),
                "note": _text(item, "note"),
            }
            for item in root.findall("line_items/item")
        ],
        subtotal=_money(_text(root, "totals/subtotal", "subtotal")),
        tax=_money(_text(root, "totals/tax_amount", "totals/tax", "tax_amount")),
        shipping=_money(_text(root, "totals/shipping", "shipping")),
        total=_money(_text(root, "totals/total", "total")),
        payment_terms=_text(root, "payment_terms", "header/payment_terms"),
        notes=_text(root, "notes", "header/notes"),
    )
