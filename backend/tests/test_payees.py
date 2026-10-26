"""Payee registry: normalization, resolution and learning, seed, the rolling window, and ledger outcomes."""

from datetime import date
from decimal import Decimal

import pytest

from acme import payees
from acme.db.seed import seed
from acme.models import Decision, Outcome
from acme.payees import PayeeSnapshot, normalize_address, normalize_name, payee_total, record_invoice, resolve
from acme.payments import enqueue_review, queue_payment, record_processed, run_batch
from golden_invoices import GOLDEN, record_processed as processed_stand_in

D = Decimal
HARBOR = "88 Harbor View Rd, Unit 4, Tacoma, WA 98402"


def _invoice(name, **update):
    return GOLDEN[name].model_copy(deep=True, update=update)


def _record(conn, run_id, invoice, outcome="APPROVE"):
    processed_stand_in(conn, invoice, outcome, run_id)


def _payee(conn, name):
    return conn.execute("SELECT payee_id FROM payee_names WHERE name_norm = ?", (normalize_name(name),)).fetchone()[0]


def _ledger(conn, run_id):
    return [dict(r) for r in conn.execute("SELECT * FROM payee_invoices WHERE run_id = ? ORDER BY payee_id",
                                          (run_id,))]


# --- normalization ---------------------------------------------------------------------------

def test_name_suffix_and_punctuation_variants_normalize_together():
    assert normalize_name("Northwind Fabrication, LLC") == normalize_name("NORTHWIND FABRICATION LLC") \
        == normalize_name("  Northwind   Fabrication ") == "northwind fabrication"
    assert normalize_name("Widgets Inc.") == normalize_name("widgets, inc") == "widgets"
    assert normalize_name("Harbor Point Supply Co.") == "harbor point supply"
    assert normalize_name("Northwind Fabrication") != normalize_name("Northwind Fabricators")
    assert normalize_name("") == normalize_name(None) == ""


def test_street_abbreviations_normalize_together():
    assert normalize_address("2200 Industrial Parkway, Columbus OH 43215") \
        == normalize_address("2200 Industrial Pkwy., Columbus, OH 43215") == "2200 industrial pkwy columbus oh 43215"
    assert normalize_address("88 Harbor View Road, Suite 4") == normalize_address("88 harbor view rd ste 4") \
        == normalize_address("88 Harbor View Rd, Unit 4")
    for long, short in (("Street", "St"), ("Avenue", "Ave"), ("Boulevard", "Blvd"), ("Drive", "Dr")):
        assert normalize_address(f"1 Oak {long}") == normalize_address(f"1 Oak {short}.")
    assert normalize_address("1 Oak St, 98402") != normalize_address("1 Oak St, 98403")  # ZIP kept


# --- seed ------------------------------------------------------------------------------------

def test_seed_creates_one_payee_per_vendor_with_aliases_and_addresses(seeded_db):
    snapshot = PayeeSnapshot.load(seeded_db)
    assert len(snapshot.canonical) == 15
    [quickship] = snapshot.match("FastShip Ltd.", None)
    assert snapshot.canonical[quickship] == "QuickShip Distributers"
    assert snapshot.match("QuickShip Distributers (formerly FastShip Ltd.)", None) == [quickship]
    [widgets] = snapshot.match(None, "100 Main St., Chicago, IL 60601")
    assert snapshot.canonical[widgets] == "Widgets Inc."
    assert snapshot.canonical[snapshot.match(None, "742 Evergreen Terrace, Springfield, IL 62704")[0]] \
        == "Precision Parts Ltd."
    assert snapshot.match(None, HARBOR) == []  # fixture vendors' addresses are learned, not seeded
    for unknown in ("Apex Procurement Services", "NoProd Industries", "Fraudster LLC"):
        assert snapshot.match(unknown, None) == []


def test_reseed_is_idempotent_and_keeps_learned_data(seeded_db):
    _record(seeded_db, "r-1021", _invoice("invoice_1021.txt"))
    counts = {t: seeded_db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("payees", "payee_names", "payee_addresses", "payee_invoices")}
    seed(seeded_db)
    assert counts == {t: seeded_db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts}
    harbor = _payee(seeded_db, "Harbor Point Supply Co.")
    assert PayeeSnapshot.load(seeded_db).match(None, HARBOR) == [harbor]
    assert [r["invoice_number"] for r in _ledger(seeded_db, "r-1021")] == ["INV-1021"]


# --- resolution and learning ---------------------------------------------------------------

def test_same_name_resolves_to_the_seeded_payee(seeded_db):
    northwind = _payee(seeded_db, "Northwind Fabrication LLC")
    assert resolve(seeded_db, "Northwind Fabrication LLC", None) == [northwind]
    assert resolve(seeded_db, "Northwind Fabrication, LLC", "2200 Industrial Pkwy, Columbus, OH 43215") == [northwind]


def test_address_learned_from_the_first_invoice(seeded_db):
    harbor = _payee(seeded_db, "Harbor Point Supply Co.")
    assert record_invoice(seeded_db, "r-1021", _invoice("invoice_1021.txt"), "APPROVE") == [harbor]
    row = seeded_db.execute("SELECT * FROM payee_addresses WHERE payee_id = ?", (harbor,)).fetchone()
    assert (row["address_norm"], row["address_raw"]) == (normalize_address(HARBOR), HARBOR)


def test_different_name_same_address_resolves_to_both_payees(seeded_db):
    record_invoice(seeded_db, "r-1021", _invoice("invoice_1021.txt"), "APPROVE")
    harbor, hps = _payee(seeded_db, "Harbor Point Supply Co."), _payee(seeded_db, "HPS Industrial Partners")
    assert resolve(seeded_db, "HPS Industrial Partners", "88 Harbor View Road, Unit 4, Tacoma, WA 98402") \
        == sorted([harbor, hps])
    # A name no payee has, at a known address: its own payee, linked to the address-matched one.
    linked = resolve(seeded_db, "Harbor Pt Supplies", HARBOR)
    assert harbor in linked and len(linked) == 2
    [new] = set(linked) - {harbor}
    assert seeded_db.execute("SELECT name_norm FROM payee_names WHERE payee_id = ?", (new,)).fetchone()[0] \
        == "harbor pt supplies"


def test_new_vendor_creates_a_payee(seeded_db):
    [apex] = record_invoice(seeded_db, "r-1017", _invoice("invoice_1017.txt"), "REJECT")
    row = seeded_db.execute("SELECT * FROM payees WHERE id = ?", (apex,)).fetchone()
    assert (row["canonical_name"], row["source"]) == ("Apex Procurement Services", "invoice")
    assert PayeeSnapshot.load(seeded_db).match(None, "4100 Commerce Way, Ste 210, Dallas, TX 75201") == [apex]
    assert resolve(seeded_db, "Apex Procurement Services", None) == [apex]  # not created twice


def test_no_vendor_name_or_address_has_no_identity(seeded_db):
    before = seeded_db.execute("SELECT COUNT(*) FROM payees").fetchone()[0]
    invoice = _invoice("invoice_1009.json")
    assert (invoice.vendor_name, invoice.vendor_address) == ("", None)
    assert resolve(seeded_db, invoice.vendor_name, invoice.vendor_address) == []
    assert record_invoice(seeded_db, "r-1009", invoice, "REJECT") == []
    assert seeded_db.execute("SELECT COUNT(*) FROM payees").fetchone()[0] == before
    assert PayeeSnapshot.load(seeded_db).lookup(invoice) is None


def test_ledger_row_per_payee_with_upload_date_fallback(seeded_db):
    record_invoice(seeded_db, "r-1021", _invoice("invoice_1021.txt"), "APPROVE")
    _record(seeded_db, "r-1022", _invoice("invoice_1022.json", invoice_date=None), "NEEDS_REVIEW")
    rows = _ledger(seeded_db, "r-1022")
    assert len(rows) == 2 and {r["invoice_date"] for r in rows} == {"2026-01-31"}  # the run's upload date
    assert {(r["invoice_number"], r["total_usd"], r["outcome"]) for r in rows} == {("INV-1022", "5250.00",
                                                                                     "NEEDS_REVIEW")}


# --- rolling window (3.2) --------------------------------------------------------------------

def _northwind(conn):
    return [_payee(conn, "Northwind Fabrication LLC")]


def test_split_invoices_summed(seeded_db):
    _record(seeded_db, "r-1018", _invoice("invoice_1018.txt"))
    result = payee_total(seeded_db, _northwind(seeded_db), _invoice("invoice_1019.json"))
    assert result.total == D("19250.00") and [m.invoice_number for m in result.members] == ["INV-1018", "INV-1019"]
    assert (result.start, result.end, result.days) == (date(2026, 2, 2), date(2026, 3, 3), 30)
    assert result.payees == ("Northwind Fabrication LLC",)


def test_duplicate_copies_count_once(seeded_db):
    quickship = [_payee(seeded_db, "QuickShip Distributers")]
    _record(seeded_db, "r-pdf", GOLDEN["invoice_1012.pdf"])
    _record(seeded_db, "r-txt", GOLDEN["invoice_1012.txt"], "REJECT")
    assert payee_total(seeded_db, quickship, GOLDEN["invoice_1012.txt"]).total == D("9975.00")


def test_revision_counts_at_its_latest_total(seeded_db):
    precision = [_payee(seeded_db, "Precision Parts Ltd.")]
    _record(seeded_db, "r-1004", GOLDEN["invoice_1004.json"])
    assert payee_total(seeded_db, precision, GOLDEN["invoice_1004_revised.json"]).total == D("5940.00")
    _record(seeded_db, "r-1004-r1", GOLDEN["invoice_1004_revised.json"])
    assert payee_total(seeded_db, precision, GOLDEN["invoice_1004.json"]).total == D("5940.00")


def test_invoices_45_days_apart_do_not_share_a_window(seeded_db):
    early = _invoice("invoice_1018.txt", invoice_date=date(2026, 1, 1))
    late = _invoice("invoice_1019.json", invoice_date=date(2026, 2, 15))
    _record(seeded_db, "r-early", early)
    assert payee_total(seeded_db, _northwind(seeded_db), late).total == D("9500.00")
    _record(seeded_db, "r-late", late)
    assert payee_total(seeded_db, _northwind(seeded_db), early).total == D("9750.00")


def test_order_independent(seeded_db):
    feb_10 = _invoice("invoice_1019.json", invoice_date=date(2026, 2, 10))
    feb_5 = _invoice("invoice_1018.txt", invoice_date=date(2026, 2, 5))
    _record(seeded_db, "r-feb10", feb_10)
    result = payee_total(seeded_db, _northwind(seeded_db), feb_5)
    assert result.total == D("19250.00") and result.start == date(2026, 2, 5)


def test_largest_span_wins():
    def entry(number, day, total):
        return payees.LedgerEntry(f"r-{number}", number, 0, "V", date(2026, 3, day), D(total), "Paid")
    current = entry("C", 15, "1000.00")
    entries = [entry("A", 1, "5000.00"), entry("B", 31, "8000.00")]
    total, start, members = payees.window_total(entries, current, 30)
    assert (total, start, [m.invoice_number for m in members]) == (D("9000.00"), date(2026, 3, 15), ["C", "B"])


# --- ledger outcomes (3.3) -------------------------------------------------------------------

def test_awaiting_review_invoice_later_paid_shows_paid(seeded_db):
    invoice = GOLDEN["invoice_1001.txt"]
    seeded_db.execute("INSERT INTO invoice_runs (id, file_name, uploaded_at, status) "
                      "VALUES ('r-1', 'a.txt', '2026-01-31T00:00:00+00:00', 'Processing')")
    seeded_db.commit()
    record_processed("r-1", invoice, Outcome.NEEDS_REVIEW)
    record_invoice(seeded_db, "r-1", invoice, "NEEDS_REVIEW")
    enqueue_review("r-1", "PRICE_VARIANCE: check", "warning")
    assert [r["outcome"] for r in _ledger(seeded_db, "r-1")] == ["Awaiting review"]
    queue_payment("r-1", invoice, Decision(outcome=Outcome.APPROVE, rationale="ok", decided_by="Dana"))
    assert [r["outcome"] for r in _ledger(seeded_db, "r-1")] == ["Queued for payment"]
    assert run_batch("pay_all", "test").count == 1
    assert [r["outcome"] for r in _ledger(seeded_db, "r-1")] == ["Paid"]


@pytest.mark.parametrize("outcome", ["REJECT", "APPROVE"])
def test_rerecording_updates_the_row(seeded_db, outcome):
    invoice = _invoice("invoice_1021.txt")
    record_invoice(seeded_db, "r-1021", invoice, "NEEDS_REVIEW")
    record_invoice(seeded_db, "r-1021", invoice, outcome)
    assert [r["outcome"] for r in _ledger(seeded_db, "r-1021")] == [outcome]
