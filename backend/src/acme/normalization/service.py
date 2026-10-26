"""`normalize(extracted)`: ExtractedInvoice -> canonical `Invoice` plus findings (F5-F7)."""

import sqlite3
from decimal import Decimal
from typing import Any

from acme.ingestion.schema import ExtractedInvoice
from acme.logging import audit, run_context, run_id_var
from acme.models import Finding, FindingCode, Invoice, LineItem
from acme.normalization import llm_fallback
from acme.normalization.cleaners import (
    fix_ocr, is_relative_date, normalize_invoice_number, normalize_revision, parse_date, parse_money,
)
from acme.normalization.fx import convert_currency
from acme.normalization.sku import SkuCatalog, SkuMatch, match_sku

AGENT = "normalizer"


class _Normalizer:
    def __init__(self, catalog: SkuCatalog) -> None:
        self.catalog = catalog
        self.repairs: list[dict[str, str]] = []
        self.sku_matches: list[dict[str, Any]] = []

    def _ocr(self, field: str, value):
        if not isinstance(value, str):
            return value
        fixed = fix_ocr(value)
        if fixed != value:
            self.repairs.append({"field": field, "before": value, "after": fixed})
        return fixed

    def money(self, field: str, value):
        return parse_money(self._ocr(field, value))

    def date(self, field: str, value):
        value = self._ocr(field, value)
        parsed = parse_date(value)
        if parsed is None and isinstance(value, str) and value.strip() and not is_relative_date(value):
            parsed = llm_fallback.suggest_date(value)
        return parsed

    def sku(self, index: int, raw_name: str) -> str | None:
        match = match_sku(raw_name, self.catalog)
        if match.sku is None:
            suggestion = llm_fallback.suggest_sku(raw_name, sorted(self.catalog.skus))
            match = SkuMatch(suggestion, "llm") if suggestion else match
        self.sku_matches.append({"line": index, "raw_name": raw_name, "sku": match.sku, "method": match.method})
        return match.sku


def _text(value: str | None) -> str | None:
    return None if value is None else " ".join(value.split())


def _or_zero(amount: Decimal | None) -> Decimal:
    return Decimal("0.00") if amount is None else amount


def _build(extracted: ExtractedInvoice, n: _Normalizer) -> Invoice:
    due_date = n.date("due_date", extracted.due_date)
    raw_due = extracted.due_date if isinstance(extracted.due_date, str) and extracted.due_date.strip() else None
    return Invoice(
        invoice_number=normalize_invoice_number(extracted.invoice_number),
        revision=normalize_revision(extracted.revision),
        vendor_name=_text(extracted.vendor_name),
        vendor_address=_text(extracted.vendor_address),
        invoice_date=n.date("invoice_date", extracted.invoice_date),
        due_date=due_date,
        due_date_raw=raw_due.strip() if due_date is None and raw_due else None,
        currency=(extracted.currency or "USD").strip().upper() or "USD",
        line_items=[
            LineItem(
                sku=n.sku(i, item.raw_name),
                raw_name=item.raw_name,
                quantity=item.quantity,
                unit_price=n.money(f"line_items[{i}].unit_price", item.unit_price),
                amount=n.money(f"line_items[{i}].amount", item.amount),
                note=item.note,
            )
            for i, item in enumerate(extracted.line_items)
        ],
        subtotal=n.money("subtotal", extracted.subtotal),
        tax=_or_zero(n.money("tax", extracted.tax)),
        shipping=_or_zero(n.money("shipping", extracted.shipping)),
        total=n.money("total", extracted.total),
        payment_terms=_text(extracted.payment_terms),
        notes=extracted.notes,
    )


def normalize(
    extracted: ExtractedInvoice,
    conn: sqlite3.Connection | None = None,
    run_id: str | None = None,
) -> tuple[Invoice | None, list[Finding]]:
    """Return the canonical invoice and normalization findings (CURRENCY_CONVERTED/UNSUPPORTED).

    Returns (None, [EXTRACTION_FAILED]) if a required value (e.g. the total) can't be parsed.
    Business-rule findings (unknown items, due dates, ...) are left to validation.
    """
    run_id = run_id if run_id is not None else run_id_var.get()
    with run_context(run_id, agent=AGENT):
        n = _Normalizer(SkuCatalog.load(conn))
        try:
            invoice = _build(extracted, n)
        except ValueError as exc:  # includes pydantic ValidationError
            code = FindingCode.EXTRACTION_FAILED
            cause = f"normalization failed: {type(exc).__name__}: {exc}"
            audit(run_id, AGENT, "normalization_failed", {"error": cause, "ocr_repairs": n.repairs}, conn=conn)
            return None, [Finding(code=code, severity=code.severity, message=cause, evidence={"cause": cause})]
        invoice, findings = convert_currency(invoice)
        audit(run_id, AGENT, "normalized", {
            "invoice_number": {"raw": extracted.invoice_number, "normalized": invoice.invoice_number},
            "sku_matches": n.sku_matches,
            "ocr_repairs": n.repairs,
            "findings": [f.code for f in findings],
        }, conn=conn)
        return invoice, findings
