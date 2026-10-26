"""Shared helpers for the workflow, CLI, and golden tests."""

import json
from decimal import Decimal
from pathlib import Path

from acme.approval.offline import register_offline as register_approval_offline
from acme.ingestion.offline import _offline_extraction
from acme.ingestion.schema import ExtractedInvoice
from acme.llm import register_handler
from acme.logging import read_trace
from acme.normalization.llm_fallback import DateSuggestion, SkuSuggestion
from acme.validation.agent import register_offline as register_validation_offline

REPO_ROOT = Path(__file__).resolve().parents[2]
INVOICES = REPO_ROOT / "data" / "invoices"


def restore_offline() -> None:
    """Other suites replace the global offline handlers and tool plan; restore the defaults."""
    register_validation_offline()
    register_approval_offline()
    register_handler(ExtractedInvoice, _offline_extraction)
    register_handler(SkuSuggestion, lambda messages: SkuSuggestion())
    register_handler(DateSuggestion, lambda messages: DateSuggestion())


def events(run_id: str) -> list[str]:
    return [e["event"] for e in read_trace(run_id)]


def codes(result) -> set[str]:
    return {f.code.value for f in result.findings}


def queue_rows(conn, run_id=None) -> list[dict]:
    sql = "SELECT * FROM payment_queue" + (" WHERE run_id = ?" if run_id else "") + " ORDER BY id"
    return [dict(r) for r in conn.execute(sql, (run_id,) if run_id else ())]


def run_row(conn, run_id) -> dict:
    return dict(conn.execute("SELECT * FROM invoice_runs WHERE id = ?", (run_id,)).fetchone())


def inv_1004(tmp_path: Path, name: str, revision: str | None = None, lines=None, notes=None) -> Path:
    """A copy of invoice_1004.json, optionally as a revision with other lines (8% tax, totals recomputed)."""
    data = json.loads((INVOICES / "invoice_1004.json").read_text())
    if revision:
        data["revision"] = revision
    if lines is not None:
        data["line_items"] = [{"item": item, "quantity": qty, "unit_price": price} for item, qty, price in lines]
        subtotal = sum(Decimal(str(price)) * qty for _, qty, price in lines)
        tax = (subtotal * Decimal("0.08")).quantize(Decimal("0.01"))
        data |= {"subtotal": float(subtotal), "tax_amount": float(tax), "total": float(subtotal + tax)}
    if notes:
        data["notes"] = notes
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path
