"""Deterministic JSON parser (F2). Values are carried over as found; no repair."""

import json
from decimal import Decimal
from typing import Any

from acme.ingestion.schema import ExtractedInvoice


def parse_json(text: str) -> ExtractedInvoice:
    """Parse an Acme JSON invoice; raises ValueError (incl. JSONDecodeError/ValidationError)."""
    data = json.loads(text, parse_float=Decimal)
    if not isinstance(data, dict):
        raise ValueError("JSON invoice must be an object")
    vendor = data.get("vendor")
    if isinstance(vendor, dict):
        vendor_name, vendor_address = vendor.get("name"), vendor.get("address")
    else:
        vendor_name, vendor_address = vendor, data.get("vendor_address")
    return ExtractedInvoice(
        invoice_number=data.get("invoice_number"),
        revision=data.get("revision") or 0,
        vendor_name=vendor_name,
        vendor_address=vendor_address,
        invoice_date=data.get("date", data.get("invoice_date")),
        due_date=data.get("due_date"),
        currency=data.get("currency"),
        line_items=[_line(item) for item in data.get("line_items") or []],
        subtotal=data.get("subtotal"),
        tax=_first(data, "tax_amount", "tax"),
        shipping=data.get("shipping"),
        total=data.get("total"),
        payment_terms=data.get("payment_terms"),
        notes=data.get("notes"),
    )


def _first(data: dict[str, Any], *keys: str) -> Any:
    return next((data[k] for k in keys if data.get(k) is not None), None)


def _line(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_name": _first(item, "item", "name", "description"),
        "quantity": item.get("quantity"),
        "unit_price": item.get("unit_price"),
        "amount": item.get("amount"),
        "note": item.get("note"),
    }
