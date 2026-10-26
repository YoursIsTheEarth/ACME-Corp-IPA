"""CLI commands (tasks 5.1-5.5, 7.1)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from acme.cli import main
from acme.workflow import create_run
from workflow_helpers import INVOICES, REPO_ROOT, run_row

I1001, I1002, I1003, I1010 = (str(INVOICES / f"invoice_{n}.txt") for n in (1001, 1002, 1003, 1010))


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_readme_command_exits_zero(tmp_path):
    """`python main.py --invoice_path=...` in a fresh directory: seeds acme.db, processes, prints APPROVE."""
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and not k.startswith("LLM_")}
    proc = subprocess.run([sys.executable, str(REPO_ROOT / "main.py"), f"--invoice_path={I1001}",
                           "--provider", "offline"], cwd=tmp_path, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    for text in ("Extracting", "Validating", "Deciding", "No findings", "APPROVE", "Queued for payment", "Run ID: run-"):
        assert text in proc.stdout


def test_missing_file_creates_no_run(seeded_db, capsys):
    assert main(["--invoice_path=nope/missing.txt", "--provider", "offline"]) == 1
    assert "nope/missing.txt" in capsys.readouterr().err
    assert seeded_db.execute("SELECT COUNT(*) FROM invoice_runs").fetchone()[0] == 0


def test_json_output_for_1002(seeded_db, capsys):
    assert main([f"--invoice_path={I1002}", "--json"]) == 0
    [obj] = _json_lines(capsys.readouterr().out)
    assert obj["outcome"] == "REJECT" and obj["invoice_number"] == "INV-1002" and obj["total_usd"] == "15000.00"
    assert {"code": "STOCK_EXCEEDED", "severity": "CRITICAL"}.items() <= obj["findings"][0].items()
    assert obj["decided_by"] and obj["run_id"].startswith("run-")


def test_batch_pay_then_payments_run(seeded_db, capsys):
    assert main(["--batch", str(INVOICES), "--provider", "offline", "--pay", "--json"]) == 0
    lines = _json_lines(capsys.readouterr().out)
    runs = [line for line in lines if "run_id" in line]
    assert [r["file"] for r in runs] == sorted(p.name for p in INVOICES.iterdir())
    [batch] = [line["batch"] for line in lines if "batch" in line]
    assert (batch["paid"], batch["total_usd"], batch["trigger"], batch["released_by"]) == (
        7, "37620.00", "pay_all", "cli")

    assert main(["payments", "run"]) == 0
    assert "Nothing is queued" in capsys.readouterr().out
    assert seeded_db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 7

    summary = Path("reports/summary.md").read_text()
    for row in ("| Paid | 7 |", "| Superseded | 1 |", "| Held for review | 1 |", "| Rejected | 11 |",
                "| Duplicates caught | 3 |", "| Paid | $37,620.00 |"):
        assert row in summary


def test_payments_run_released_by(seeded_db, capsys):
    assert main([f"--invoice_path={I1001}"]) == 0
    capsys.readouterr()
    assert main(["payments", "run", "--released-by", "Dana", "--json"]) == 0
    [line] = _json_lines(capsys.readouterr().out)
    assert (line["batch"]["paid"], line["batch"]["released_by"]) == (1, "Dana")


def test_review_list_and_approve(seeded_db, capsys):
    assert main([f"--invoice_path={I1010}", "--json"]) == 0
    run_id = _json_lines(capsys.readouterr().out)[0]["run_id"]

    assert main(["review"]) == 0
    out = capsys.readouterr().out
    assert run_id in out and "PRICE_VARIANCE" in out and "NEEDS_REVIEW" in out

    assert main(["review", run_id, "--decision", "approve", "--reviewer", "Dana",
                 "--rationale", "Rush pricing agreed by procurement"]) == 0
    assert "Queued for payment" in capsys.readouterr().out
    assert run_row(seeded_db, run_id)["decided_by"] == "Dana"
    assert seeded_db.execute("SELECT COUNT(*) FROM payment_queue WHERE run_id = ?", (run_id,)).fetchone()[0] == 1


@pytest.mark.parametrize("reviewer, rationale, rule", [("  ", "Rush pricing agreed by procurement", "reviewer name"),
                                                       ("Dana", "short", "at least 15")])
def test_review_invalid_input(seeded_db, capsys, reviewer, rationale, rule):
    assert main([f"--invoice_path={I1010}", "--json"]) == 0
    run_id = _json_lines(capsys.readouterr().out)[0]["run_id"]
    assert main(["review", run_id, "--decision", "approve", "--reviewer", reviewer, "--rationale", rationale]) == 1
    assert rule in capsys.readouterr().err
    assert run_row(seeded_db, run_id)["status"] == "Awaiting review"


def test_review_run_not_held(seeded_db, capsys):
    assert main([f"--invoice_path={I1001}", "--json"]) == 0
    run_id = _json_lines(capsys.readouterr().out)[0]["run_id"]
    assert main(["review", run_id, "--decision", "approve", "--reviewer", "Dana",
                 "--rationale", "Rush pricing agreed by procurement"]) == 1
    assert "no longer awaiting review" in capsys.readouterr().err


def test_explain_1003(seeded_db, capsys):
    assert main([f"--invoice_path={I1003}", "--json"]) == 0
    run_id = _json_lines(capsys.readouterr().out)[0]["run_id"]
    assert main(["--explain", run_id]) == 0
    out = capsys.readouterr().out
    for text in ("ZERO_STOCK", "INVALID_DUE_DATE", "FRAUD_SUSPECTED", "evidence=", "CRITICAL_ZERO_STOCK",
                 "rejection.recorded", "Rejected by Auto (rules)", "extraction_attempt", "AI VP draft"):
        assert text in out
    assert out.index("extraction_attempt") < out.index("approval.policy") < out.index("rejection.recorded")


def test_explain_unknown_run(seeded_db, capsys):
    assert main(["--explain", "run-nope"]) == 1
    assert "run not found" in capsys.readouterr().err


def test_startup_recovers_orphaned_run(seeded_db, capsys):
    run_id = create_run(I1001)
    seeded_db.execute("UPDATE invoice_runs SET stage = 'Validating', status = 'Processing' WHERE id = ?", (run_id,))
    seeded_db.commit()
    assert main(["review"]) == 0
    assert run_row(seeded_db, run_id)["status"] == "Queued for payment"
    assert f"Resuming interrupted run {run_id}" in capsys.readouterr().out
