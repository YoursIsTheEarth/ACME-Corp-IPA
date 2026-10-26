"""Payment timing end to end through the graph (add-admin-payment-settings 2.4, 2.5).

The default is delay on; immediate-mode tests turn delay off explicitly.
"""

from decimal import Decimal

from acme.admin import PaymentTiming, load_payment_timing, save_payment_timing
from acme.workflow import run_invoice
from workflow_helpers import INVOICES, queue_rows, run_row

THREE = ("invoice_1001.txt", "invoice_1006.csv", "invoice_1015.csv")


def batches(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM payment_batches ORDER BY batch_id")]


def payments(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM payments ORDER BY id")]


def set_delay(on: bool, by: str = "Dana"):
    return save_payment_timing(PaymentTiming(delay_payments=on), by)


def test_workflow_fixtures_run_with_the_default_timing(wdb):
    assert load_payment_timing(wdb) == PaymentTiming() and load_payment_timing(wdb).delay_payments


def test_delay_off_pays_at_approval(wdb, bank):
    set_delay(False)
    result = run_invoice(INVOICES / "invoice_1001.txt")
    assert (result.outcome, result.status, result.final_status) == ("APPROVE", "Resolved", "Paid")
    [row] = queue_rows(wdb, result.run_id)
    assert (row["status"], row["kind"], row["amount_usd"]) == ("paid", "full", "5000.00")
    [batch] = batches(wdb)
    assert (batch["trigger"], batch["released_by"], batch["count"], batch["total_usd"]) == (
        "immediate", "System", 1, "5000.00")
    [payment] = payments(wdb)
    assert (payment["amount_usd"], payment["batch_id"]) == ("5000.00", batch["batch_id"])
    assert bank == [("Widgets Inc.", Decimal("5000.00"))]


def test_delay_on_leaves_it_queued(wdb, bank):
    set_delay(True)
    result = run_invoice(INVOICES / "invoice_1001.txt")
    assert (result.status, result.final_status) == ("Queued for payment", None)
    assert queue_rows(wdb, result.run_id)[0]["status"] == "queued"
    assert batches(wdb) == [] and bank == []


def test_rejected_and_held_runs_start_no_batch(wdb, bank):
    set_delay(False)
    run_invoice(INVOICES / "invoice_1002.txt")
    run_invoice(INVOICES / "invoice_1010.txt")
    assert batches(wdb) == [] and bank == []


def test_switching_delay_off_pays_the_queue_in_one_batch(wdb, bank):
    ids = [run_invoice(INVOICES / name).run_id for name in THREE]
    assert [r["status"] for r in queue_rows(wdb)] == ["queued"] * 3 and bank == []
    view = set_delay(False)
    assert view["delay_payments"] is False
    [batch] = batches(wdb)
    assert (batch["trigger"], batch["released_by"], batch["count"], batch["total_usd"]) == (
        "immediate", "System", 3, "14250.00")
    assert [run_row(wdb, i)["final_status"] for i in ids] == ["Paid"] * 3


def test_switching_delay_on_pays_nothing(wdb, bank):
    set_delay(False)
    set_delay(True)
    ids = [run_invoice(INVOICES / name).run_id for name in THREE[:2]]
    assert [r["status"] for r in queue_rows(wdb)] == ["queued", "queued"]
    assert batches(wdb) == [] and bank == []
    assert [run_row(wdb, i)["status"] for i in ids] == ["Queued for payment"] * 2


def test_immediate_revision_pays_only_the_delta(wdb, bank):
    set_delay(False)
    original = run_invoice(INVOICES / "invoice_1004.json")
    assert original.final_status == "Paid"
    assert bank == [("Precision Parts Ltd.", Decimal("1890.00"))]
    revision = run_invoice(INVOICES / "invoice_1004_revised.json")
    assert revision.final_status == "Revised"
    assert "REVISION" in {f.code.value for f in revision.findings}
    [row] = queue_rows(wdb, revision.run_id)
    assert (row["kind"], row["amount_usd"], row["status"]) == ("delta", "4050.00", "paid")
    assert run_row(wdb, original.run_id)["final_status"] == "Paid"  # not superseded
    assert [b["trigger"] for b in batches(wdb)] == ["immediate", "immediate"]
    assert [p["amount_usd"] for p in payments(wdb)] == ["1890.00", "4050.00"]
