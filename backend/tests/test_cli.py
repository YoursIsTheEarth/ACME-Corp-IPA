import os
import subprocess
import sys
from pathlib import Path

import pytest

from acme.cli import main

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
