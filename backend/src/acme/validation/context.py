"""Read-only lookups the checks run against (design D1).

    ctx = ValidationContext.load(conn)

Snapshots `inventory`, `vendors`, `processed_invoices` (with the original's total from
`invoice_runs.total_usd`), `payments`, and the payee registry (read through `payee_lookup`).
Validation never writes to these tables. `run_validation` adds the document's `raw_text` and the
LLM's `address_assessment` for the invoice under validation.

Contract for the writer of `processed_invoices` (disposition): store
`vendor = ctx.vendor_key(invoice.vendor_name)` and `content_hash = content_hash(invoice)`,
for every outcome (duplicates of rejected invoices are still duplicates).
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Callable, Mapping

from acme.db import connect
from acme.models import Invoice

if TYPE_CHECKING:
    from acme.payees import PayeeTotal
    from acme.validation.address import AddressAssessment


def normalize_name(name: str | None) -> str:
    """Trim, collapse whitespace, and case-fold. No fuzzy matching: lookalikes stay distinct."""
    return " ".join((name or "").split()).casefold()


@dataclass(frozen=True)
class StockItem:
    sku: str
    stock: int
    unit_price: Decimal | None


@dataclass(frozen=True)
class ProcessedInvoice:
    vendor: str
    invoice_number: str
    revision: int
    content_hash: str | None
    outcome: str | None
    run_id: str | None
    total: Decimal | None


@dataclass(frozen=True)
class Payment:
    idempotency_key: str
    vendor: str
    amount_usd: Decimal


@dataclass(frozen=True)
class ValidationContext:
    inventory: Mapping[str, StockItem]
    approved_vendors: Mapping[str, str]  # normalized name or alias -> canonical vendor name
    processed: tuple[ProcessedInvoice, ...]
    payments: tuple[Payment, ...]
    address_assessment: "AddressAssessment | None" = None  # set per invoice by run_validation
    raw_text: str | None = None  # the document text, set per invoice by run_validation
    payee_lookup: "Callable[[Invoice], PayeeTotal | None] | None" = None  # rolling payee total (read-only)

    @classmethod
    def load(cls, conn: sqlite3.Connection | None = None) -> "ValidationContext":
        from acme.payees import PayeeSnapshot  # acme.payees imports this module

        own = conn is None
        conn = conn or connect()
        try:
            inventory = {
                r["item"]: StockItem(r["item"], r["stock"], Decimal(r["unit_price"]) if r["unit_price"] else None)
                for r in conn.execute("SELECT item, stock, unit_price FROM inventory")
            }
            vendors: dict[str, str] = {}
            for r in conn.execute("SELECT name, aliases FROM vendors WHERE status = 'approved' ORDER BY name"):
                for name in [r["name"], *json.loads(r["aliases"] or "[]")]:
                    vendors.setdefault(normalize_name(name), r["name"])
            processed = tuple(
                ProcessedInvoice(r["vendor"], r["invoice_number"], r["revision"], r["content_hash"],
                                 r["outcome"], r["run_id"], Decimal(r["total_usd"]) if r["total_usd"] else None)
                for r in conn.execute(
                    "SELECT p.vendor, p.invoice_number, p.revision, p.content_hash, p.outcome, p.run_id, "
                    "r.total_usd FROM processed_invoices p LEFT JOIN invoice_runs r ON r.id = p.run_id "
                    "ORDER BY p.id"
                )
            )
            payments = tuple(
                Payment(r["idempotency_key"], r["vendor"], Decimal(r["amount_usd"]))
                for r in conn.execute("SELECT idempotency_key, vendor, amount_usd FROM payments ORDER BY id")
            )
            payees = PayeeSnapshot.load(conn)
        finally:
            if own:
                conn.close()
        return cls(MappingProxyType(inventory), MappingProxyType(vendors), processed, payments,
                   payee_lookup=payees.lookup)

    def approved_vendor(self, name: str | None) -> str | None:
        """Canonical approved vendor name matched by name or alias, else None."""
        return self.approved_vendors.get(normalize_name(name))

    def vendor_key(self, name: str | None) -> str:
        """Vendor identity for duplicate detection: the approved vendor (aliases folded in), else the name."""
        return normalize_name(self.approved_vendor(name) or name)


def content_hash(invoice: Invoice) -> str:
    """Hash of what makes two copies the same invoice, independent of the source format."""
    lines = sorted(
        ((item.sku or normalize_name(item.raw_name)), item.quantity, str(item.unit_price))
        for item in invoice.line_items
    )
    payload = json.dumps([invoice.invoice_number, invoice.revision, str(invoice.total), lines])
    return hashlib.sha256(payload.encode()).hexdigest()
