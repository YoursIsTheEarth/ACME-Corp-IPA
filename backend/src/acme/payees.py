"""Payee registry (design D1-D3): one identity per payee, its names and remit-to addresses, and a ledger
of every invoice received for it, so split invoices can be totalled over a rolling window.

    payee_ids = resolve(conn, vendor_name, vendor_address)    # creates a payee for an unknown vendor
    record_invoice(conn, run_id, invoice, outcome)             # disposition: ledger row per payee, learns
    set_outcome(conn, run_id, outcome)                         # the run's outcome changed later
    payee_total(conn, payee_ids, invoice)                      # largest N-day span total and its members

Validation reads a `PayeeSnapshot` (via `ValidationContext.payee_lookup`) and never writes.
`vendors` stays the approved list; payees also exist for unknown and rejected vendors.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from acme.models import Invoice
from acme.settings import get_settings
from acme.validation.context import normalize_name as _fold

SUFFIXES = frozenset({"inc", "llc", "ltd", "co", "corp", "company", "corporation"})
STREET_WORDS = {"street": "st", "avenue": "ave", "road": "rd", "parkway": "pkwy", "suite": "unit", "ste": "unit",
                "boulevard": "blvd", "drive": "dr"}
_PUNCTUATION = re.compile(r"[^\w\s]")


def normalize_name(name: str | None) -> str:
    """Case-folded words without punctuation or trailing business suffixes ("Northwind Fabrication, LLC" ->
    "northwind fabrication")."""
    words = _PUNCTUATION.sub(" ", _fold(name)).split()
    while len(words) > 1 and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def normalize_address(address: str | None) -> str:
    """Case-folded words without punctuation, street abbreviations canonical ("Parkway" -> "pkwy"); ZIP kept."""
    return " ".join(STREET_WORDS.get(word, word) for word in _PUNCTUATION.sub(" ", _fold(address)).split())


@dataclass(frozen=True)
class LedgerEntry:
    run_id: str | None  # None for the invoice under validation
    invoice_number: str
    revision: int
    vendor_name: str | None
    invoice_date: date
    total: Decimal
    outcome: str | None


@dataclass(frozen=True)
class PayeeTotal:
    payees: tuple[str, ...]  # canonical names of the resolved payees
    start: date
    end: date
    days: int
    total: Decimal
    members: tuple[LedgerEntry, ...]  # one per invoice number, by date


def window_total(entries: list[LedgerEntry], current: LedgerEntry, days: int) -> tuple[Decimal, date,
                                                                                        list[LedgerEntry]]:
    """The largest total of any `days`-day span that includes `current`'s date (design D3).

    Each invoice number counts once, at its latest revision (duplicate copies share the number); the
    current invoice replaces a recorded copy of the same revision. Returns (total, span start, members).
    """
    latest: dict[str, LedgerEntry] = {}
    for entry in entries:
        if current.run_id is not None and entry.run_id == current.run_id:
            continue
        kept = latest.get(entry.invoice_number)
        if kept is None or entry.revision > kept.revision:
            latest[entry.invoice_number] = entry
    kept = latest.get(current.invoice_number)
    if kept is None or current.revision >= kept.revision:
        latest[current.invoice_number] = current
    day, span = current.invoice_date, timedelta(days=days - 1)
    starts = sorted({day} | {e.invoice_date for e in latest.values() if day - span <= e.invoice_date <= day})
    best: tuple[Decimal, date, list[LedgerEntry]] | None = None
    for start in starts:
        members = sorted((e for e in latest.values() if start <= e.invoice_date <= start + span),
                         key=lambda e: (e.invoice_date, e.invoice_number))
        total = sum((e.total for e in members), Decimal("0"))
        if best is None or total > best[0]:
            best = (total, start, members)
    return best


def _entry(invoice: Invoice, day: date, run_id: str | None = None, outcome: str | None = None) -> LedgerEntry:
    return LedgerEntry(run_id, invoice.invoice_number, invoice.revision, invoice.vendor_name, day, invoice.total,
                       outcome)


@dataclass(frozen=True)
class PayeeSnapshot:
    """Read-only copy of the registry and ledger, for validation."""

    names: Mapping[str, tuple[int, ...]]
    addresses: Mapping[str, tuple[int, ...]]
    canonical: Mapping[int, str]
    ledger: tuple[tuple[int, LedgerEntry], ...]

    @classmethod
    def load(cls, conn: sqlite3.Connection) -> "PayeeSnapshot":
        names: dict[str, tuple[int, ...]] = {}
        for r in conn.execute("SELECT name_norm, payee_id FROM payee_names ORDER BY payee_id"):
            names[r["name_norm"]] = (*names.get(r["name_norm"], ()), r["payee_id"])
        addresses: dict[str, tuple[int, ...]] = {}
        for r in conn.execute("SELECT address_norm, payee_id FROM payee_addresses ORDER BY payee_id"):
            addresses[r["address_norm"]] = (*addresses.get(r["address_norm"], ()), r["payee_id"])
        canonical = {r["id"]: r["canonical_name"] for r in conn.execute("SELECT id, canonical_name FROM payees")}
        ledger = tuple(
            (r["payee_id"], LedgerEntry(r["run_id"], r["invoice_number"], r["revision"], r["vendor_name"],
                                        date.fromisoformat(r["invoice_date"]), Decimal(r["total_usd"]), r["outcome"]))
            for r in conn.execute("SELECT * FROM payee_invoices ORDER BY id")
        )
        return cls(MappingProxyType(names), MappingProxyType(addresses), MappingProxyType(canonical), ledger)

    def match(self, vendor_name: str | None, vendor_address: str | None) -> list[int]:
        """Existing payees matched by normalized name or alias, or by normalized address."""
        name, address = normalize_name(vendor_name), normalize_address(vendor_address)
        ids = set(self.names.get(name, ())) if name else set()
        ids |= set(self.addresses.get(address, ())) if address else set()
        return sorted(ids)

    def total(self, payee_ids: list[int], invoice: Invoice, run_id: str | None = None) -> PayeeTotal | None:
        """The rolling payee total for `invoice` over the payees' ledger; None when there are no payees."""
        if not payee_ids:
            return None
        days = get_settings().payee_window_days
        wanted = set(payee_ids)
        seen, entries = set(), []
        for payee_id, entry in self.ledger:
            if payee_id in wanted and entry.run_id not in seen:  # an invoice linked to two payees counts once
                seen.add(entry.run_id)
                entries.append(entry)
        current = _entry(invoice, invoice.invoice_date or date.today(), run_id)
        total, start, members = window_total(entries, current, days)
        return PayeeTotal(tuple(self.canonical.get(i, str(i)) for i in sorted(wanted)), start,
                          start + timedelta(days=days - 1), days, total, tuple(members))

    def lookup(self, invoice: Invoice) -> PayeeTotal | None:
        """`ValidationContext.payee_lookup`: resolve without creating, then total."""
        return self.total(self.match(invoice.vendor_name, invoice.vendor_address), invoice)


def payee_total(conn: sqlite3.Connection, payee_ids: list[int], invoice: Invoice) -> PayeeTotal | None:
    return PayeeSnapshot.load(conn).total(payee_ids, invoice)


# --- writes (disposition and seed) -----------------------------------------------------------

def create_payee(conn: sqlite3.Connection, canonical_name: str, source: str, names: list[str]) -> int:
    from acme.payments._store import utcnow

    payee_id = conn.execute("INSERT INTO payees (canonical_name, source, created_at) VALUES (?, ?, ?)",
                            (canonical_name, source, utcnow())).lastrowid
    add_names(conn, payee_id, names)
    return payee_id


def add_names(conn: sqlite3.Connection, payee_id: int, names: list[str]) -> None:
    conn.executemany("INSERT OR IGNORE INTO payee_names (name_norm, payee_id) VALUES (?, ?)",
                     [(norm, payee_id) for norm in dict.fromkeys(map(normalize_name, names)) if norm])


def add_address(conn: sqlite3.Connection, payee_id: int, address: str) -> None:
    if norm := normalize_address(address):
        conn.execute("INSERT OR IGNORE INTO payee_addresses (address_norm, payee_id, address_raw) VALUES (?, ?, ?)",
                     (norm, payee_id, address.strip()))


def _resolve(conn: sqlite3.Connection, vendor_name: str | None,
             vendor_address: str | None) -> tuple[list[int], list[int]]:
    """(name-matched payees, address-matched payees); creates a payee for a name no payee has."""
    name, address = normalize_name(vendor_name), normalize_address(vendor_address)
    by_address = [r[0] for r in conn.execute("SELECT payee_id FROM payee_addresses WHERE address_norm = ? "
                                             "ORDER BY payee_id", (address,))] if address else []
    if not name:
        if address and not by_address:
            by_address = [create_payee(conn, vendor_address.strip(), "invoice", [])]
        return [], by_address
    by_name = [r[0] for r in conn.execute("SELECT payee_id FROM payee_names WHERE name_norm = ? ORDER BY payee_id",
                                          (name,))]
    if not by_name:  # a new vendor, or a new name at a known address: its own payee, linked by the address
        by_name = [create_payee(conn, vendor_name.strip(), "invoice", [vendor_name])]
    return by_name, by_address


def resolve(conn: sqlite3.Connection, vendor_name: str | None, vendor_address: str | None) -> list[int]:
    """Every payee the vendor name/alias or address matches; a new payee when none match; [] with neither."""
    from acme.payments._store import immediate

    with immediate(conn):
        by_name, by_address = _resolve(conn, vendor_name, vendor_address)
    return sorted({*by_name, *by_address})


def _upload_day(conn: sqlite3.Connection, run_id: str) -> date:
    row = conn.execute("SELECT uploaded_at FROM invoice_runs WHERE id = ?", (run_id,)).fetchone()
    return date.fromisoformat(row[0][:10]) if row and row[0] else date.today()


def record_invoice(conn: sqlite3.Connection, run_id: str, invoice: Invoice, outcome: str) -> list[int]:
    """Link the run's invoice to each payee it resolves to (re-recording updates it) and learn its address
    under the name-matched payees. Returns the payee ids ([] for an invoice with no vendor name or address)."""
    from acme.payments._store import immediate, utcnow

    with immediate(conn):
        by_name, by_address = _resolve(conn, invoice.vendor_name, invoice.vendor_address)
        payee_ids = sorted({*by_name, *by_address})
        if invoice.vendor_address:
            for payee_id in by_name or payee_ids:
                add_address(conn, payee_id, invoice.vendor_address)
        day = invoice.invoice_date or _upload_day(conn, run_id)
        conn.executemany(
            "INSERT INTO payee_invoices (payee_id, run_id, invoice_number, revision, vendor_name, vendor_address, "
            "invoice_date, total_usd, outcome, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (payee_id, run_id) DO UPDATE SET invoice_number = excluded.invoice_number, "
            "revision = excluded.revision, vendor_name = excluded.vendor_name, "
            "vendor_address = excluded.vendor_address, invoice_date = excluded.invoice_date, "
            "total_usd = excluded.total_usd, outcome = excluded.outcome",
            [(payee_id, run_id, invoice.invoice_number, invoice.revision, invoice.vendor_name, invoice.vendor_address,
              day, f"{invoice.total:.2f}", str(outcome), utcnow()) for payee_id in payee_ids],
        )
    return payee_ids


def set_outcome(conn: sqlite3.Connection, run_id: str, outcome: str) -> None:
    """Keep the ledger's outcome in step with the run (call inside the caller's transaction)."""
    conn.execute("UPDATE payee_invoices SET outcome = ? WHERE run_id = ?", (outcome, run_id))
