import os
import subprocess
import sys
from pathlib import Path

from acme.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(*args, **env):
    clean = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and not k.startswith("LLM_")}
    return subprocess.run([sys.executable, str(REPO_ROOT / "main.py"), *args], cwd=REPO_ROOT,
                          capture_output=True, text=True, env={**clean, **env})


def test_main_help_exits_zero():
    result = _run("--help", LLM_PROVIDER="offline")
    assert result.returncode == 0 and "--invoice_path" in result.stdout


def test_startup_stops_without_grok_key(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    assert main(["--invoice_path", "data/invoices/invoice_1001.txt"]) == 2
    assert "XAI_API_KEY" in capsys.readouterr().err


def test_startup_offline_succeeds(capsys):
    assert main([]) == 0


def test_provider_flag_overrides(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    assert main(["--provider", "offline"]) == 0
    assert main(["--provider", "gpt"]) == 2
    assert "grok, claude, offline" in capsys.readouterr().err
