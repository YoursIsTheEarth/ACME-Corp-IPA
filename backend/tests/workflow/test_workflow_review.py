"""Review hold, resume, restart, and recovery (tasks 3.1-3.4)."""

import json
import os
import subprocess
import sys

import pytest

from acme.graph import compiled_graph
from acme.payments import mock_bank, run_batch
from acme.workflow import (
    ReviewConflict, ReviewInputError, create_run, list_reviews, process_run, recover_orphaned_runs, resume_review,
    run_invoice, run_state,
)
from workflow_helpers import INVOICES, REPO_ROOT, events, queue_rows, run_row

RATIONALE = "Rush pricing agreed by procurement"


@pytest.fixture
def held(wdb):
    result = run_invoice(INVOICES / "invoice_1010.txt")
    assert result.status == "Awaiting review"
    return result.run_id


# --- 3.1 ------------------------------------------------------------------------------------

def test_1010_pauses_awaiting_review(wdb, held):
    with compiled_graph() as graph:
        snapshot = graph.get_state({"configurable": {"thread_id": held}})
    assert snapshot.next == ("review_hold",) and snapshot.interrupts
    assert snapshot.interrupts[0].value["kind"] == "warning"
    row = run_row(wdb, held)
    assert (row["status"], row["stage"], row["invoice_number"], row["total_usd"]) == (
        "Awaiting review", "Awaiting review", "INV-1010", "7185.00")
    [item] = list_reviews()
    assert item["run_id"] == held and "PRICE_VARIANCE" in item["findings"]
    assert item["ai_recommendation"] == "NEEDS_REVIEW" and item["ai_rationale"]


def test_checkpoint_tables_live_in_acme_db(wdb, held):
    tables = {r[0] for r in wdb.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"checkpoints", "writes"} <= tables
    assert wdb.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


# --- 3.2 ------------------------------------------------------------------------------------

def test_reviewer_approves(wdb, held, bank):
    result = resume_review(held, "approve", "  Dana  ", RATIONALE)
    assert result.run_id == held and (result.outcome, result.status, result.decided_by) == (
        "APPROVE", "Queued for payment", "Dana")
    [row] = queue_rows(wdb, held)
    assert (row["status"], row["amount_usd"]) == ("queued", "7185.00")
    [decision] = [dict(r) for r in wdb.execute("SELECT * FROM review_decisions WHERE run_id = ?", (held,))]
    assert (decision["reviewer"], decision["decision"], decision["rationale"]) == ("Dana", "approve", RATIONALE)
    trail = events(held)
    assert trail.index("review.enqueued") < trail.index("review.decision") < trail.index("payment.queued")
    assert bank == []


def test_reviewer_rejects(wdb, held):
    result = resume_review(held, "reject", "Dana", "Vendor would not honor list price")
    assert (result.outcome, result.final_status, result.decided_by) == ("REJECT", "Rejected", "Dana")
    assert queue_rows(wdb, held) == [] and "rejection.recorded" in events(held)


@pytest.mark.parametrize("decision, reviewer, rationale, message", [
    ("approve", "   ", RATIONALE, "reviewer name"),
    ("approve", "x" * 51, RATIONALE, "reviewer name"),
    ("approve", "Dana", "too short", "rationale"),
    ("maybe", "Dana", RATIONALE, "decision"),
])
def test_invalid_review_input(wdb, held, decision, reviewer, rationale, message):
    with pytest.raises(ReviewInputError, match=message):
        resume_review(held, decision, reviewer, rationale)
    assert run_row(wdb, held)["status"] == "Awaiting review"
    assert wdb.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0


def test_decision_on_run_not_awaiting_review(wdb):
    result = run_invoice(INVOICES / "invoice_1001.txt")
    with pytest.raises(ReviewConflict) as exc:
        resume_review(result.run_id, "approve", "Dana", RATIONALE)
    assert exc.value.status == "Queued for payment"
    assert run_row(wdb, result.run_id)["status"] == "Queued for payment"


def test_second_decision_conflicts(wdb, held):
    resume_review(held, "approve", "Dana", RATIONALE)
    with pytest.raises(ReviewConflict):
        resume_review(held, "reject", "Lee", "Changed my mind about this one")
    assert len(queue_rows(wdb, held)) == 1


def test_unknown_run_conflicts(wdb):
    with pytest.raises(ReviewConflict):
        resume_review("run-missing", "approve", "Dana", RATIONALE)


def test_payment_failure_hold_resumes_through_executor(wdb):
    result = run_invoice(INVOICES / "invoice_1001.txt")
    mock_bank.fail_next(3, "bank timeout")
    for _ in range(3):
        run_batch("pay_all", "test")
    assert run_row(wdb, result.run_id)["status"] == "Awaiting review"
    resumed = resume_review(result.run_id, "approve", "Dana", "Bank confirmed the account is fine")
    assert resumed.status == "Queued for payment"
    assert [r["status"] for r in queue_rows(wdb, result.run_id)] == ["cancelled", "queued"]


# --- 3.3 restart ----------------------------------------------------------------------------

def test_held_invoice_survives_restart(wdb, tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and not k.startswith("LLM_")}
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "backend" / "tests" / "fake_cli.py"),
         f"--invoice_path={INVOICES / 'invoice_1010.txt'}", "--json"],
        cwd=tmp_path, capture_output=True, text=True, env={**env, "XAI_API_KEY": "test-key"}, check=True)
    run_id = json.loads(proc.stdout.splitlines()[0])["run_id"]

    state = run_state(run_id)  # fresh connection and graph in this process
    assert {f.code.value for f in state.findings} >= {"PRICE_VARIANCE"}
    assert state.decision_draft is not None and state.decision.outcome.value == "NEEDS_REVIEW"
    result = resume_review(run_id, "approve", "Dana", RATIONALE)
    assert result.run_id == run_id and result.status == "Queued for payment"
    assert len(queue_rows(wdb, run_id)) == 1


# --- 3.4 orphaned runs ----------------------------------------------------------------------

def test_recover_run_stuck_in_validating(wdb, held):
    run_id = create_run(INVOICES / "invoice_1001.txt")
    wdb.execute("UPDATE invoice_runs SET stage = 'Validating', status = 'Processing' WHERE id = ?", (run_id,))
    wdb.commit()
    assert recover_orphaned_runs() == [run_id]
    row = run_row(wdb, run_id)
    assert (row["stage"], row["status"]) == ("Uploaded", "Uploaded")
    assert run_row(wdb, held)["status"] == "Awaiting review"  # held runs are untouched
    assert process_run(run_id).status == "Queued for payment"
    assert recover_orphaned_runs() == []
