"""Revision and adversarial scenarios, end to end through the graph (tasks 6.4, 6.5)."""

import json
from decimal import Decimal

from acme.payments import run_batch
from acme.workflow import resume_review, run_invoice
from workflow_helpers import INVOICES, codes, inv_1004, queue_rows, run_row

ORIGINAL_LINES = [("WidgetA", 3, 250.0), ("WidgetB", 2, 500.0)]  # $1,750 + 8% = $1,890.00


def _paid_original(wdb, tmp_path):
    original = run_invoice(inv_1004(tmp_path, "inv_1004.json"))
    assert run_batch("pay_all", "test").count == 1
    assert run_row(wdb, original.run_id)["final_status"] == "Paid"
    return original


# --- 6.4 revisions ---------------------------------------------------------------------------

def test_revision_of_queued_original_replaces_it(wdb, tmp_path):
    original = run_invoice(inv_1004(tmp_path, "inv_1004.json"))
    revision = run_invoice(INVOICES / "invoice_1004_revised.json")
    assert run_row(wdb, original.run_id)["final_status"] == "Superseded"
    assert [r["status"] for r in queue_rows(wdb, original.run_id)] == ["cancelled"]
    [row] = queue_rows(wdb, revision.run_id)
    assert (row["kind"], row["amount_usd"]) == ("replacement", "5940.00")


def test_paid_original_higher_revision_queues_delta(wdb, tmp_path):
    _paid_original(wdb, tmp_path)
    revision = run_invoice(INVOICES / "invoice_1004_revised.json")
    [row] = queue_rows(wdb, revision.run_id)
    assert (row["kind"], row["amount_usd"]) == ("delta", "4050.00")
    batch = run_batch("pay_all", "test")
    assert (batch.count, batch.total_usd) == (1, Decimal("4050.00"))
    assert run_row(wdb, revision.run_id)["final_status"] == "Revised"


def test_paid_original_lower_revision_held_for_credit(wdb, tmp_path):
    _paid_original(wdb, tmp_path)
    lower = inv_1004(tmp_path, "inv_1004_r1.json", "R1", [("WidgetA", 3, 250.0), ("WidgetB", 1, 500.0)])
    revision = run_invoice(lower)  # $1,350.00
    assert (revision.outcome, revision.status) == ("NEEDS_REVIEW", "Awaiting review")
    assert {"REVISION", "REVISION_CREDIT_DUE"} <= codes(revision)
    assert queue_rows(wdb, revision.run_id) == []

    result = resume_review(revision.run_id, "approve", "Dana", "Credit note CN-88 for $540 agreed with vendor")
    assert (result.final_status, result.decided_by) == ("Credit confirmed", "Dana")
    assert queue_rows(wdb, revision.run_id) == [] and run_batch("pay_all", "test").count == 0


def test_paid_original_same_total_is_revised(wdb, tmp_path):
    _paid_original(wdb, tmp_path)
    same = inv_1004(tmp_path, "inv_1004_r1.json", "R1", ORIGINAL_LINES, notes="Corrected PO reference")
    revision = run_invoice(same)
    assert (revision.outcome, revision.final_status) == ("APPROVE", "Revised")
    assert queue_rows(wdb, revision.run_id) == [] and run_batch("pay_all", "test").count == 0


def test_failing_revision_of_queued_original(wdb, tmp_path):
    original = run_invoice(inv_1004(tmp_path, "inv_1004.json"))
    bad = inv_1004(tmp_path, "inv_1004_r1.json", "R1", [*ORIGINAL_LINES, ("WidgetC", 1, 350.0)])
    revision = run_invoice(bad)
    assert (revision.outcome, revision.final_status) == ("REJECT", "Rejected")
    assert "UNKNOWN_ITEM" in codes(revision)
    assert run_row(wdb, original.run_id)["final_status"] == "Superseded"
    assert run_batch("pay_all", "test").count == 0


# --- 6.5 adversarial -------------------------------------------------------------------------

def test_total_off_by_one_cent(wdb, tmp_path):
    path = inv_1004(tmp_path, "cent.json")
    data = json.loads(path.read_text())
    data["total"] = 1890.01
    path.write_text(json.dumps(data))
    result = run_invoice(path)
    assert result.outcome == "REJECT" and "MATH_MISMATCH" in codes(result)


def test_lookalike_vendor_not_auto_approved(wdb, tmp_path):
    path = inv_1004(tmp_path, "lookalike.json")
    data = json.loads(path.read_text())
    data["vendor"]["name"] = "Precision Pаrts Ltd."  # Cyrillic a
    path.write_text(json.dumps(data, ensure_ascii=False))
    result = run_invoice(path)
    assert "UNKNOWN_VENDOR" in codes(result) and result.outcome != "APPROVE"
    assert queue_rows(wdb, result.run_id) == []


def test_zero_byte_file(wdb, tmp_path):
    path = tmp_path / "zero.pdf"
    path.write_bytes(b"")
    result = run_invoice(path)
    assert (result.outcome, codes(result)) == ("REJECT", {"EXTRACTION_FAILED"})
