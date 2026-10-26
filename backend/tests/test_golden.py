"""Golden suite (F20): all 20 provided files in sorted filename order, with the test-only fake model, then one payment batch.

Rows that needed a P1 feature were staged as strict expected failures (`NEEDS_FEATURE`); F7, F11,
and F12 have landed, so no row is tagged and the outcome-count assert runs.
"""

from decimal import Decimal

import pytest

from acme.db import connect
from acme.db.seed import seed
from acme.logging import read_trace
from acme.payments import mock_bank, run_batch
from acme.settings import get_settings
from acme.workflow import run_folder, run_state
import fake_llm
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
}

# Rows staged until a P1 feature lands, e.g. {"invoice_1014.xml": "F7"}. Empty: F7, F11, F12 have landed.
NEEDS_FEATURE: dict[str, str] = {}

OUTCOME_OF_STATUS = {"Paid": "PAID", "Superseded": "SUPERSEDED", "Rejected": "REJECT", "Duplicate": "REJECT"}


def _snapshot(conn) -> dict:
    runs = {r["file_name"]: dict(r) for r in conn.execute("SELECT * FROM invoice_runs ORDER BY uploaded_at, id")}
    paid: dict[str, Decimal] = {}
    for r in conn.execute("SELECT q.run_id, q.amount_usd FROM payment_queue q WHERE q.status = 'paid'"):
        paid[r["run_id"]] = paid.get(r["run_id"], D("0")) + D(r["amount_usd"])
    return {"runs": runs, "paid": paid, "payments": conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]}


@pytest.fixture(scope="module")
def golden_run(tmp_path_factory):
    """Process the folder, pay once, then pay again and reprocess (idempotency). Returns plain data."""
    workdir = tmp_path_factory.mktemp("golden")
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(workdir)
        mp.setenv("LLM_PROVIDER", "grok")
        mp.setenv("XAI_API_KEY", "test-key")
        mp.setenv("DB_PATH", str(workdir / "acme.db"))
        calls = []
        real_payment = mock_bank.mock_payment
        mp.setattr(mock_bank, "mock_payment", lambda vendor, amount: calls.append((vendor, amount))
                   or real_payment(vendor, amount))
        mock_bank.reset()
        get_settings.cache_clear()
        fake_llm.install(mp)
        conn = connect()
        try:
            seed(conn)
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
        finally:
            conn.close()
            get_settings.cache_clear()
    return {"results": results, "before": before_batch, "after": after_batch, "states": states, "traces": traces,
            "batch": batch, "second": second, "rerun": rerun, "third": third, "final": final, "calls": calls,
            "fx_eur": fx_eur}


def _rows():
    return [pytest.param(name, marks=pytest.mark.xfail(strict=True, reason=f"needs {NEEDS_FEATURE[name]}"))
            if name in NEEDS_FEATURE else name for name in GOLDEN_TABLE]


def _outcome(run: dict) -> str:
    if run["status"] == "Awaiting review":
        return "NEEDS_REVIEW"
    return OUTCOME_OF_STATUS.get(run["final_status"], run["final_status"] or run["status"])


def _codes(golden_run, name) -> set[str]:
    found = {f.code.value for f in golden_run["states"][name].findings}
    # SUPERSEDED_BY_REVISION is recorded on the original's trail by the revision's disposition.
    found |= {e["payload"]["finding"]["code"] for e in golden_run["traces"][name] if e["event"] == "invoice.superseded"}
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
    assert len(files) == 20 and files == sorted(p.name for p in INVOICES.iterdir())
    assert list(golden_run["before"]["runs"]) == files  # uploaded_at order matches


def test_batch_total(golden_run):
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
    if NEEDS_FEATURE:
        pytest.skip(f"golden rows still staged: {sorted(NEEDS_FEATURE)}")
    runs = golden_run["after"]["runs"].values()
    finals = [r["final_status"] for r in runs]
    counts = {
        "paid": finals.count("Paid"), "superseded": finals.count("Superseded"),
        "held": sum(r["status"] == "Awaiting review" for r in runs),
        "rejected": finals.count("Rejected") + finals.count("Duplicate"), "duplicates": finals.count("Duplicate"),
    }
    assert counts == {"paid": 7, "superseded": 1, "held": 1, "rejected": 11, "duplicates": 3}


# --- 6.3 idempotency -------------------------------------------------------------------------

def test_second_batch_pays_nothing(golden_run):
    assert golden_run["second"].count == 0 and golden_run["second"].total_usd == D("0.00")


def test_reprocessing_folder_pays_nothing(golden_run):
    rerun = {r.file: r for r in golden_run["rerun"]}
    for name, (outcome, _, _) in GOLDEN_TABLE.items():
        if outcome == "PAID":
            assert rerun[name].final_status == "Duplicate", name
            assert "DUPLICATE" in {f.code.value for f in rerun[name].findings}
    assert golden_run["third"].count == 0
    assert golden_run["final"]["payments"] == 7 and len(golden_run["calls"]) == 7
