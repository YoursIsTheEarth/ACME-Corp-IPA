"""Golden suite (F20): all 26 provided files in sorted filename order, with the test-only fake model, then one payment batch.

It runs with the default payment timing (delay on, end of day off, pay when queue empty on; no scheduler, so
the explicit batch pays), and again with delay explicitly off (immediate payments, see the end of the file).

Rows that needed a P1 feature were staged as strict expected failures (`NEEDS_FEATURE`); F7, F11,
and F12 have landed, so no row is tagged and the outcome-count assert runs.
"""

from decimal import Decimal

import pytest

from acme.admin import PaymentTiming
from acme.logging import read_trace
from acme.payments import run_batch
from acme.settings import get_settings
from acme.workflow import run_folder, run_state
from workflow_helpers import INVOICES

D = Decimal
EUR_4125 = "EUR"  # paid amount computed from the configured rate

# file: (expected outcome, paid in batch, key finding codes)
GOLDEN_TABLE = {
    "invoice_1001.txt": ("PAID", D("5000.00"), set()),
    "invoice_1002.txt": ("REJECT", None, {"STOCK_EXCEEDED"}),
    "invoice_1003.txt": ("REJECT", None, {"ZERO_STOCK", "INVALID_DUE_DATE", "FRAUD_SUSPECTED"}),
    "invoice_1004.json": ("SUPERSEDED", None, {"SUPERSEDED_BY_REVISION"}),
    "invoice_1004_revised.json": ("PAID", D("5940.00"), {"REVISION"}),
    "invoice_1005.json": ("REJECT", None, {"STOCK_EXCEEDED", "SUSPICIOUS_ADDRESS"}),
    "invoice_1006.csv": ("PAID", D("2750.00"), set()),
    "invoice_1007.csv": ("REJECT", None, {"STOCK_EXCEEDED"}),
    "invoice_1008.txt": ("REJECT", None, {"UNKNOWN_ITEM", "UNKNOWN_VENDOR"}),
    "invoice_1009.json": ("REJECT", None, {"MISSING_VENDOR", "INVALID_QUANTITY", "MATH_MISMATCH", "MISSING_DUE_DATE"}),
    "invoice_1010.txt": ("NEEDS_REVIEW", None, {"PRICE_VARIANCE"}),
    "invoice_1011.pdf": ("PAID", D("3000.00"), set()),
    "invoice_1011.txt": ("REJECT", None, {"DUPLICATE"}),
    "invoice_1012.pdf": ("PAID", D("9975.00"), {"NEAR_THRESHOLD"}),
    "invoice_1012.txt": ("REJECT", None, {"DUPLICATE"}),
    "invoice_1013.json": ("REJECT", None, {"STOCK_EXCEEDED"}),
    "invoice_1013.pdf": ("REJECT", None, {"DUPLICATE"}),
    "invoice_1014.xml": ("PAID", EUR_4125, {"CURRENCY_CONVERTED"}),
    "invoice_1015.csv": ("PAID", D("6500.00"), set()),
    "invoice_1016.json": ("REJECT", None, {"UNKNOWN_ITEM"}),
    "invoice_1017.txt": ("REJECT", None, {"PROMPT_INJECTION_SUSPECTED", "FRAUD_SUSPECTED", "UNKNOWN_VENDOR",
                                          "PRICE_VARIANCE"}),
    # Approved and queued, then pulled from the Payment Queue into review when INV-1019 arrives.
    "invoice_1018.txt": ("NEEDS_REVIEW", None, {"NEAR_THRESHOLD", "PAYEE_CUMULATIVE_THRESHOLD"}),
    "invoice_1019.json": ("NEEDS_REVIEW", None, {"PAYEE_CUMULATIVE_THRESHOLD", "NEAR_THRESHOLD"}),
    "invoice_1020.csv": ("NEEDS_REVIEW", None, {"PAYEE_CUMULATIVE_THRESHOLD", "NEAR_THRESHOLD"}),
    # Approved and queued, then pulled from the Payment Queue into review when INV-1022 arrives.
    "invoice_1021.txt": ("NEEDS_REVIEW", None, {"PAYEE_CUMULATIVE_THRESHOLD"}),
    "invoice_1022.json": ("NEEDS_REVIEW", None, {"PAYEE_CUMULATIVE_THRESHOLD"}),
}

# Rows staged until a feature lands, e.g. {"invoice_1017.txt": "payee/injection"}. While any row is staged the
# count asserts are skipped. Empty: the payee threshold and prompt-injection detection have landed.
NEEDS_FEATURE: dict[str, str] = {}

OUTCOME_OF_STATUS = {"Paid": "PAID", "Superseded": "SUPERSEDED", "Rejected": "REJECT", "Duplicate": "REJECT",
                     "Revised": "REVISED"}


def _snapshot(conn) -> dict:
    runs = {r["file_name"]: dict(r) for r in conn.execute("SELECT * FROM invoice_runs ORDER BY uploaded_at, id")}
    paid: dict[str, Decimal] = {}
    for r in conn.execute("SELECT q.run_id, q.amount_usd FROM payment_queue q WHERE q.status = 'paid'"):
        paid[r["run_id"]] = paid.get(r["run_id"], D("0")) + D(r["amount_usd"])
    return {"runs": runs, "paid": paid, "payments": conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]}


DEFAULT_TIMING = PaymentTiming(delay_payments=True, pay_at_end_of_day=False, pay_when_queue_empty=True)
IMMEDIATE_TIMING = PaymentTiming(delay_payments=False)


@pytest.fixture(scope="module")
def golden_run(run_golden):
    """Default timing: process the folder, pay once, then pay again and reprocess (idempotency). Plain data."""
    with run_golden(DEFAULT_TIMING) as (conn, calls):
        results = run_folder(INVOICES)
        before_batch = _snapshot(conn)
        states = {r.file: run_state(r.run_id) for r in results}
        traces = {r.file: read_trace(r.run_id) for r in results}
        batch = run_batch("pay_all", "test")
        after_batch = _snapshot(conn)
        second = run_batch("pay_all", "test")
        rerun = run_folder(INVOICES)
        third = run_batch("pay_all", "test")
        final = _snapshot(conn)
        fx_eur = get_settings().fx_rates["EUR"]
    return {"results": results, "before": before_batch, "after": after_batch, "states": states, "traces": traces,
            "batch": batch, "second": second, "rerun": rerun, "third": third, "final": final, "calls": calls,
            "fx_eur": fx_eur}


def _rows():
    return [pytest.param(name, marks=pytest.mark.xfail(strict=True, reason=f"needs {NEEDS_FEATURE[name]}"))
            if name in NEEDS_FEATURE else name for name in GOLDEN_TABLE]


def _skip_while_staged():
    if NEEDS_FEATURE:
        pytest.skip(f"golden rows still staged: {sorted(NEEDS_FEATURE)}")


def _outcome(run: dict) -> str:
    if run["status"] == "Awaiting review":
        return "NEEDS_REVIEW"
    return OUTCOME_OF_STATUS.get(run["final_status"], run["final_status"] or run["status"])


def _codes(golden_run, name) -> set[str]:
    found = {f.code.value for f in golden_run["states"][name].findings}
    for e in golden_run["traces"][name]:
        # SUPERSEDED_BY_REVISION is recorded on the original's trail by the revision's disposition, and a payee
        # threshold flag by the disposition of the invoice that crossed it (a hold, or a retroactive flag).
        if e["event"] in ("invoice.superseded", "finding.retroactive"):
            found.add(e["payload"]["finding"]["code"])
        elif e["event"] == "review.enqueued":
            found |= set(e["payload"]["details"].get("findings", []))
    return found


@pytest.mark.parametrize("name", _rows())
def test_golden_row(golden_run, name):
    expected_outcome, expected_paid, expected_codes = GOLDEN_TABLE[name]
    run = golden_run["after"]["runs"][name]
    assert _outcome(run) == expected_outcome
    assert expected_codes <= _codes(golden_run, name)
    if expected_paid == EUR_4125:
        expected_paid = (D("4125.00") * golden_run["fx_eur"]).quantize(D("0.01"))
        assert expected_paid == D("4455.00")  # default 1.08 USD per EUR
    assert golden_run["after"]["paid"].get(run["id"]) == expected_paid


def test_folder_runs_in_sorted_filename_order(golden_run):
    files = [r.file for r in golden_run["results"]]
    assert len(files) == 26 and files == sorted(p.name for p in INVOICES.iterdir())
    assert list(golden_run["before"]["runs"]) == files  # uploaded_at order matches


def test_batch_total(golden_run):
    _skip_while_staged()
    batch = golden_run["batch"]
    assert (batch.count, batch.total_usd, batch.failed_count) == (7, D("37620.00"), 0)
    assert len(golden_run["calls"]) == 7


def test_aggregated_stock_overrun_1013(golden_run):
    stock = [f for f in golden_run["states"]["invoice_1013.json"].findings
             if f.code.value == "STOCK_EXCEEDED" and f.evidence["sku"] == "WidgetA"]
    assert [(f.evidence["billed"], f.evidence["stock"]) for f in stock] == [(22, 15)]


def test_1005_address_verdict_from_the_model(golden_run):
    [address] = [f for f in golden_run["states"]["invoice_1005.json"].findings if f.code.value == "SUSPICIOUS_ADDRESS"]
    assert address.source.value == "llm" and address.severity.value == "WARNING"
    assert address.evidence["reason"] and "matched" not in address.evidence


def _payee_totals(golden_run, name) -> list[str]:
    """Payee totals the file was flagged with: its own finding, then hold updates and retroactive flags."""
    totals = [f.evidence["total"] for f in golden_run["states"][name].findings
              if f.code.value == "PAYEE_CUMULATIVE_THRESHOLD"]
    for e in golden_run["traces"][name]:
        if e["event"] == "review.enqueued" and "payee_threshold" in e["payload"]["details"]:
            totals.append(e["payload"]["details"]["payee_threshold"]["total"])
        elif e["event"] == "finding.retroactive":
            totals.append(e["payload"]["total"])
    return totals


def test_split_invoice_payee_totals(golden_run):
    for name in ("invoice_1018.txt", "invoice_1019.json", "invoice_1020.csv"):
        assert _payee_totals(golden_run, name)[-1] == "29000.00", name
    for name in ("invoice_1021.txt", "invoice_1022.json"):
        assert _payee_totals(golden_run, name)[-1] == "11250.00", name
    held = {name: golden_run["after"]["runs"][name]["status"] for name in ("invoice_1018.txt", "invoice_1021.txt")}
    assert held == {"invoice_1018.txt": "Awaiting review", "invoice_1021.txt": "Awaiting review"}


def test_injection_does_not_sway_the_agents(golden_run):
    name = "invoice_1017.txt"
    run = golden_run["after"]["runs"][name]
    assert (run["final_status"], golden_run["states"][name].decision.outcome.value) == ("Rejected", "REJECT")
    trace = golden_run["traces"][name]
    [policy] = [e["payload"] for e in trace if e["event"] == "approval.policy"]
    assert policy["fraud"] is True and "CRITICAL_PROMPT_INJECTION_SUSPECTED" in policy["rules"]
    drafts = [e["payload"]["draft"]["outcome"] for e in trace if e["event"] == "approval.draft"]
    critiques = [e["payload"]["critique"] for e in trace if e["event"] == "approval.critique"]
    assert drafts and "APPROVE" not in drafts
    assert all(c.get("suggested_outcome") != "APPROVE" for c in critiques)
    assert not [e for e in trace if e["event"] in ("payment.queued", "review.enqueued")]
    assert golden_run["after"]["paid"].get(run["id"]) is None


# --- 6.2 aggregate asserts -------------------------------------------------------------------

def test_no_critical_finding_on_paid_files(golden_run):
    for name, (outcome, _, _) in GOLDEN_TABLE.items():
        if outcome == "PAID":
            assert not [f for f in golden_run["states"][name].findings if f.severity.value == "CRITICAL"], name


def test_no_payment_before_last_disposition(golden_run):
    before = golden_run["before"]
    assert before["payments"] == 0 and before["paid"] == {}
    assert all(r["stage"] not in ("Uploaded", "Extracting", "Validating", "Deciding") for r in before["runs"].values())
    # INV-1004 was still queued when R1 arrived: superseding it cancelled a queued row.
    [superseded] = [e["payload"] for e in golden_run["traces"]["invoice_1004.json"] if e["event"] == "invoice.superseded"]
    assert len(superseded["finding"]["evidence"]["cancelled_rows"]) == 1


def test_outcome_counts(golden_run):
    _skip_while_staged()
    runs = golden_run["after"]["runs"].values()
    finals = [r["final_status"] for r in runs]
    counts = {
        "paid": finals.count("Paid"), "superseded": finals.count("Superseded"),
        "held": sum(r["status"] == "Awaiting review" for r in runs),
        "rejected": finals.count("Rejected") + finals.count("Duplicate"), "duplicates": finals.count("Duplicate"),
    }
    assert counts == {"paid": 7, "superseded": 1, "held": 6, "rejected": 12, "duplicates": 3}


# --- 6.3 idempotency -------------------------------------------------------------------------

def test_second_batch_pays_nothing(golden_run):
    assert golden_run["second"].count == 0 and golden_run["second"].total_usd == D("0.00")


def test_reprocessing_folder_pays_nothing(golden_run):
    rerun = {r.file: r for r in golden_run["rerun"]}
    for name, (outcome, _, _) in GOLDEN_TABLE.items():
        if outcome == "PAID":
            assert rerun[name].final_status == "Duplicate", name
            assert "DUPLICATE" in {f.code.value for f in rerun[name].findings}
    _skip_while_staged()
    assert golden_run["third"].count == 0
    assert golden_run["final"]["payments"] == 7 and len(golden_run["calls"]) == 7


# --- immediate payments (delay off, set explicitly) ------------------------------------------

IMMEDIATE_CHANGES = {
    "invoice_1004.json": ("PAID", D("1890.00"), set()),
    "invoice_1004_revised.json": ("REVISED", D("4050.00"), {"REVISION"}),
    # Paid at approval, before INV-1019 / INV-1022 crossed the payee threshold: flagged retroactively.
    "invoice_1018.txt": ("PAID", D("9750.00"), {"NEAR_THRESHOLD", "PAYEE_CUMULATIVE_THRESHOLD"}),
    "invoice_1021.txt": ("PAID", D("6000.00"), {"PAYEE_CUMULATIVE_THRESHOLD"}),
}


@pytest.fixture(scope="module")
def golden_immediate(run_golden):
    """Delay off: every approval is paid by its own `immediate` batch; no manual batch runs before `after`."""
    with run_golden(IMMEDIATE_TIMING) as (conn, calls):
        results = run_folder(INVOICES)
        after = _snapshot(conn)
        states = {r.file: run_state(r.run_id) for r in results}
        traces = {r.file: read_trace(r.run_id) for r in results}
        batches = [dict(b) for b in conn.execute("SELECT * FROM payment_batches ORDER BY batch_id")]
        kinds = {r["run_id"]: r["kind"] for r in conn.execute("SELECT run_id, kind FROM payment_queue")}
        following = run_batch("pay_all", "test")
        fx_eur = get_settings().fx_rates["EUR"]
    return {"results": results, "after": after, "states": states, "traces": traces, "batches": batches,
            "kinds": kinds, "following": following, "calls": calls, "fx_eur": fx_eur}


@pytest.mark.parametrize("name", _rows())
def test_immediate_golden_row(golden_immediate, name):
    expected_outcome, expected_paid, expected_codes = IMMEDIATE_CHANGES.get(name, GOLDEN_TABLE[name])
    run = golden_immediate["after"]["runs"][name]
    assert _outcome(run) == expected_outcome
    assert expected_codes <= _codes(golden_immediate, name)
    if expected_paid == EUR_4125:
        expected_paid = (D("4125.00") * golden_immediate["fx_eur"]).quantize(D("0.01"))
    assert golden_immediate["after"]["paid"].get(run["id"]) == expected_paid


def test_immediate_split_invoices_paid_then_flagged(golden_immediate):
    for name, total in (("invoice_1018.txt", "29000.00"), ("invoice_1021.txt", "11250.00")):
        run = golden_immediate["after"]["runs"][name]
        assert run["final_status"] == "Paid", name
        flags = [e["payload"] for e in golden_immediate["traces"][name] if e["event"] == "finding.retroactive"]
        assert flags and flags[-1]["finding"]["code"] == "PAYEE_CUMULATIVE_THRESHOLD" and flags[-1]["total"] == total


def test_immediate_1004_paid_and_revision_pays_the_delta(golden_immediate):
    original = golden_immediate["after"]["runs"]["invoice_1004.json"]
    revision = golden_immediate["after"]["runs"]["invoice_1004_revised.json"]
    assert original["final_status"] == "Paid"
    assert "SUPERSEDED_BY_REVISION" not in _codes(golden_immediate, "invoice_1004.json")
    assert revision["final_status"] == "Revised"
    assert golden_immediate["kinds"][revision["id"]] == "delta"
    assert golden_immediate["after"]["paid"][revision["id"]] == D("4050.00")  # $5,940.00 - $1,890.00


def test_immediate_outcome_counts(golden_immediate):
    _skip_while_staged()
    runs = golden_immediate["after"]["runs"].values()
    finals = [r["final_status"] for r in runs]
    counts = {
        "paid": finals.count("Paid"), "revised": finals.count("Revised"), "superseded": finals.count("Superseded"),
        "held": sum(r["status"] == "Awaiting review" for r in runs),
        "rejected": finals.count("Rejected") + finals.count("Duplicate"), "duplicates": finals.count("Duplicate"),
    }
    assert counts == {"paid": 9, "revised": 1, "superseded": 0, "held": 4, "rejected": 12, "duplicates": 3}


def test_immediate_batches(golden_immediate):
    _skip_while_staged()
    batches = golden_immediate["batches"]
    assert len(batches) == 10 and len(golden_immediate["calls"]) == 10
    assert {(b["trigger"], b["released_by"], b["count"], b["failed_count"]) for b in batches} == {
        ("immediate", "System", 1, 0)}
    assert sum(D(b["total_usd"]) for b in batches) == D("53370.00")
    assert golden_immediate["after"]["payments"] == 10


def test_immediate_following_batch_pays_nothing(golden_immediate):
    following = golden_immediate["following"]
    assert (following.count, following.total_usd, following.results) == (0, D("0.00"), [])
