import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from acme.admin import PaymentTiming, load_payment_timing, save_payment_timing
from acme.cli import main
from acme.db import connect
from workflow_helpers import INVOICES

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(*args, **env):
    clean = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and not k.startswith("LLM_")}
    return subprocess.run([sys.executable, str(REPO_ROOT / "main.py"), *args], cwd=REPO_ROOT,
                          capture_output=True, text=True, env={**clean, **env})


def test_main_help_exits_zero():
    result = _run("--help")
    assert result.returncode == 0 and "--invoice_path" in result.stdout


def test_startup_stops_without_grok_key(monkeypatch, capsys):
    monkeypatch.delenv("XAI_API_KEY")
    assert main(["--invoice_path", "data/invoices/invoice_1001.txt"]) == 2
    assert "No LLM token provided: set XAI_API_KEY" in capsys.readouterr().err


def test_startup_without_a_command_succeeds(monkeypatch, capsys):
    monkeypatch.delenv("XAI_API_KEY")
    assert main([]) == 0


def test_provider_flag_overrides(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    assert main(["--provider", "claude"]) == 0
    for value in ("gpt", "offline"):
        with pytest.raises(SystemExit) as exit_info:
            main(["--provider", value])
        assert exit_info.value.code == 2
    assert "choose from grok, claude" in capsys.readouterr().err


def test_invalid_provider_setting_stops(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "offline")
    assert main(["--invoice_path", "data/invoices/invoice_1001.txt"]) == 2
    assert "valid values are: grok, claude" in capsys.readouterr().err


# --- payment timing (add-admin-payment-settings 5.1-5.3) ----------------------------------------

I1001 = f"--invoice_path={INVOICES / 'invoice_1001.txt'}"
I1006 = f"--invoice_path={INVOICES / 'invoice_1006.csv'}"


def _lines(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _delay_off():
    main(["admin", "show"])  # creates and seeds acme.db
    save_payment_timing(PaymentTiming(delay_payments=False), "Dana")


def test_single_invoice_paid_at_approval_with_delay_off(capsys):
    _delay_off()
    capsys.readouterr()
    assert main([I1001]) == 0
    out = capsys.readouterr().out
    assert "APPROVE" in out and "(Paid)" in out and "Paid at approval: payment PAY-000001" in out
    assert main([I1006, "--json"]) == 0
    [line] = _lines(capsys.readouterr().out)  # mock_payment's print stays off stdout
    assert (line["outcome"], line["final_status"], line["payment_id"]) == ("APPROVE", "Paid", "PAY-000002")


def test_single_invoice_queued_with_delay_on(capsys):
    assert main([I1001]) == 0
    out = capsys.readouterr().out
    assert "(Queued for payment)" in out and "Queued for payment (paid by the next payment batch)" in out
    assert "PAY-" not in out
    assert main([I1006, "--json"]) == 0
    [line] = _lines(capsys.readouterr().out)
    assert (line["status"], line["payment_id"]) == ("Queued for payment", None)


def test_batch_with_delay_off_pays_as_it_goes(capsys):
    _delay_off()
    capsys.readouterr()
    assert main(["--batch", str(INVOICES), "--pay"]) == 0
    out = capsys.readouterr().out
    assert "invoice_1001.txt" in out and "-> APPROVE (Paid, payment PAY-000001)" in out
    assert "-> APPROVE (Revised, payment PAY-000003)" in out  # INV-1004 R1 delta
    assert "Nothing is queued for payment; no payments made." in out
    summary = Path("reports/summary.md").read_text()
    for row in ("| Paid | 9 |", "| Revised | 1 |", "| Superseded | 0 |", "| Held for review | 4 |",
                "| Rejected | 12 |", "| Duplicates caught | 3 |", "| Paid | $53,370.00 |"):
        assert row in summary, row
    assert main(["payments", "run"]) == 0
    assert "Nothing is queued for payment" in capsys.readouterr().out


def test_admin_show_prints_the_defaults(capsys, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY")  # no LLM key needed
    assert main(["admin", "show"]) == 0
    out = capsys.readouterr().out
    for text in ("Delay payments: on", "Pay at end of day: off (17:00 America/Chicago)",
                 "Pay when the Invoice Queue is empty: on", "Never saved"):
        assert text in out
    assert main(["admin", "show", "--json"]) == 0
    [line] = _lines(capsys.readouterr().out)
    assert line == {"delay_payments": True, "pay_at_end_of_day": False, "end_of_day_time": "17:00",
                    "end_of_day_timezone": "America/Chicago", "pay_when_queue_empty": True,
                    "updated_by": None, "updated_at": None}


def test_admin_set_delay_off_then_show(capsys, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY")
    assert main(["admin", "set", "--delay-payments", "off", "--by", "Dana"]) == 0
    capsys.readouterr()
    assert main(["admin", "show"]) == 0
    out = capsys.readouterr().out
    assert "Delay payments: off" in out and "Last saved by Dana" in out
    assert load_payment_timing() == PaymentTiming(delay_payments=False)  # other values unchanged


def test_admin_set_other_flags(capsys):
    assert main(["admin", "set", "--pay-at-end-of-day", "on", "--end-of-day-time", "15:00",
                 "--end-of-day-timezone", "America/New_York", "--pay-when-queue-empty", "off", "--by", "Sam"]) == 0
    assert load_payment_timing() == PaymentTiming(pay_at_end_of_day=True, end_of_day_time="15:00",
                                                  end_of_day_timezone="America/New_York", pay_when_queue_empty=False)


def test_admin_set_delay_off_pays_the_queue(capsys):
    assert main([I1001]) == 0
    capsys.readouterr()
    assert main(["admin", "set", "--delay-payments", "off", "--by", "Dana"]) == 0
    assert "immediate batch B-0001 paid 1 queued payment(s), total $5,000.00" in capsys.readouterr().out


@pytest.mark.parametrize("args, message", [
    (["--end-of-day-timezone", "Mars/Olympus", "--by", "Dana"], "Mars/Olympus"),
    (["--end-of-day-time", "25:00", "--by", "Dana"], "end_of_day_time"),
    (["--delay-payments", "off", "--by", "   "], "updated_by"),
    (["--delay-payments", "off"], "--by"),
])
def test_admin_set_invalid_input_saves_nothing(capsys, args, message):
    assert main(["admin", "set", *args]) != 0
    assert message in capsys.readouterr().err
    assert load_payment_timing() == PaymentTiming()
    conn = connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM admin_settings").fetchone()[0] == 0
    finally:
        conn.close()
