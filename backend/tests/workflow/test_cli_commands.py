"""CLI commands (tasks 5.1-5.5, 7.1)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from acme.cli import main
from acme.settings import get_settings
from acme.workflow import create_run
from workflow_helpers import INVOICES, REPO_ROOT, run_row

I1001, I1002, I1003, I1010 = (str(INVOICES / f"invoice_{n}.txt") for n in (1001, 1002, 1003, 1010))


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _set_env(monkeypatch, **values) -> None:
    """Set (or, for None, delete) environment variables and reload the settings."""
    for name, value in values.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def _clean_env(**extra) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and not k.startswith("LLM_")}
    return {**env, **extra}


def test_readme_command_exits_zero(tmp_path):
    """The README command in a fresh directory (fake model, dummy key): seeds acme.db, processes, prints APPROVE."""
    proc = subprocess.run([sys.executable, str(REPO_ROOT / "backend" / "tests" / "fake_cli.py"),
                           f"--invoice_path={I1001}", "--provider", "grok"],
                          cwd=tmp_path, capture_output=True, text=True, env=_clean_env(XAI_API_KEY="test-key"))
    assert proc.returncode == 0, proc.stderr
    for text in ("Extracting", "Validating", "Deciding", "No findings", "APPROVE", "Queued for payment", "Run ID: run-"):
        assert text in proc.stdout


def test_readme_command_without_a_key(tmp_path):
    """`python main.py --invoice_path=...` with no key: exit 2, the no-token message, and no run."""
    proc = subprocess.run([sys.executable, str(REPO_ROOT / "main.py"), f"--invoice_path={I1001}"],
                          cwd=tmp_path, capture_output=True, text=True, env=_clean_env())
    assert proc.returncode == 2
    assert ("No LLM token provided: set XAI_API_KEY for Grok (in .env or the environment). "
            "The app cannot process invoices without it.") in proc.stderr
    assert not (tmp_path / "acme.db").exists()


def test_claude_without_its_key_creates_no_run(seeded_db, monkeypatch, capsys):
    _set_env(monkeypatch, LLM_PROVIDER="claude")
    assert main(["--batch", str(INVOICES)]) == 2
    assert "set ANTHROPIC_API_KEY for Claude" in capsys.readouterr().err
    assert seeded_db.execute("SELECT COUNT(*) FROM invoice_runs").fetchone()[0] == 0


def test_grok_override_without_its_key(seeded_db, monkeypatch, capsys):
    _set_env(monkeypatch, LLM_PROVIDER="claude", ANTHROPIC_API_KEY="a", XAI_API_KEY=None)
    assert main([f"--invoice_path={I1001}", "--provider", "grok"]) == 2
    assert "XAI_API_KEY" in capsys.readouterr().err


def test_json_error_without_a_key(seeded_db, monkeypatch, capsys):
    _set_env(monkeypatch, XAI_API_KEY=None)
    assert main([f"--invoice_path={I1001}", "--json"]) == 2
    [obj] = _json_lines(capsys.readouterr().out)
    assert obj == {"error": "No LLM token provided: set XAI_API_KEY for Grok (in .env or the environment). "
                            "The app cannot process invoices without it.", "missing_key": "XAI_API_KEY"}
    assert seeded_db.execute("SELECT COUNT(*) FROM invoice_runs").fetchone()[0] == 0


def test_no_llm_commands_work_without_a_key(seeded_db, monkeypatch, capsys):
    assert main([f"--invoice_path={I1010}", "--json"]) == 0  # held for review
    assert main([f"--invoice_path={I1001}", "--json"]) == 0  # queued
    [held] = [r for r in _json_lines(capsys.readouterr().out) if r.get("outcome") == "NEEDS_REVIEW"]
    _set_env(monkeypatch, XAI_API_KEY=None)
    assert main(["--explain", held["run_id"]]) == 0
    assert main(["review", "--json"]) == 0
    assert main(["review", held["run_id"], "--decision", "approve", "--reviewer", "Dana",
                 "--rationale", "Rush pricing confirmed by phone."]) == 0
    capsys.readouterr()
    assert main(["payments", "run", "--json"]) == 0
    [line] = _json_lines(capsys.readouterr().out)
    assert line["batch"]["paid"] == 2


def test_offline_provider_rejected(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--invoice_path", I1001, "--provider", "offline"])
    assert exit_info.value.code == 2 and "choose from grok, claude" in capsys.readouterr().err


def test_missing_file_creates_no_run(seeded_db, capsys):
    assert main(["--invoice_path=nope/missing.txt"]) == 1
    assert "nope/missing.txt" in capsys.readouterr().err
    assert seeded_db.execute("SELECT COUNT(*) FROM invoice_runs").fetchone()[0] == 0


def test_json_output_for_1002(seeded_db, capsys):
    assert main([f"--invoice_path={I1002}", "--json"]) == 0
    [obj] = _json_lines(capsys.readouterr().out)
    assert obj["outcome"] == "REJECT" and obj["invoice_number"] == "INV-1002" and obj["total_usd"] == "15000.00"
    assert {"code": "STOCK_EXCEEDED", "severity": "CRITICAL"}.items() <= obj["findings"][0].items()
    assert obj["decided_by"] and obj["run_id"].startswith("run-")


def test_batch_pay_then_payments_run(seeded_db, capsys):
    assert main(["--batch", str(INVOICES), "--pay", "--json"]) == 0
    lines = _json_lines(capsys.readouterr().out)
    runs = [line for line in lines if "run_id" in line]
    assert len(runs) == 26 and [r["file"] for r in runs] == sorted(p.name for p in INVOICES.iterdir())
    [batch] = [line["batch"] for line in lines if "batch" in line]
    assert (batch["paid"], batch["total_usd"], batch["trigger"], batch["released_by"]) == (
        7, "37620.00", "pay_all", "cli")

    assert main(["payments", "run"]) == 0
    assert "Nothing is queued" in capsys.readouterr().out
    assert seeded_db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 7

    summary = Path("reports/summary.md").read_text()
    for row in ("| Paid | 7 |", "| Superseded | 1 |", "| Held for review | 6 |", "| Rejected | 12 |",
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


def test_orphaned_run_waits_for_a_key(wdb, monkeypatch, capsys):
    run_id = create_run(INVOICES / "invoice_1001.txt")
    wdb.execute("UPDATE invoice_runs SET stage = 'Validating', status = 'Processing' WHERE id = ?", (run_id,))
    wdb.commit()
    _set_env(monkeypatch, XAI_API_KEY=None)
    assert main(["payments", "run"]) == 0
    assert "wait for an LLM key" in capsys.readouterr().out
    assert (run_row(wdb, run_id)["stage"], run_row(wdb, run_id)["status"]) == ("Uploaded", "Uploaded")
    _set_env(monkeypatch, XAI_API_KEY="test-key")
    assert main(["payments", "run"]) == 0
    assert run_row(wdb, run_id)["final_status"] == "Paid"  # processed on restart, then paid
