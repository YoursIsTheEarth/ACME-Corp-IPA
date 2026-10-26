import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from acme.settings import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_catalog_defaults(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER")
    monkeypatch.delenv("XAI_API_KEY")
    s = Settings()
    assert s.llm_provider == "grok"
    assert s.grok_model == "grok-4"
    assert s.claude_model == "claude-sonnet-5-5"
    assert (s.llm_temperature, s.llm_timeout_s, s.llm_max_retries) == (0, 30, 3)
    assert s.xai_api_key is None and s.anthropic_api_key is None
    assert s.llm_provider_extraction is s.llm_provider_validation is None
    assert s.llm_provider_approval is s.llm_provider_critic is None
    assert s.fx_rates == {"EUR": Decimal("1.08")}
    assert s.price_variance_pct == Decimal("10")
    assert s.near_threshold_floor_usd == Decimal("9500.00")
    assert s.fraud_signal_weights["suspicious_address"] == 0.30
    assert sum(s.fraud_signal_weights.values()) == pytest.approx(1.40)
    assert s.fraud_threshold == 0.60
    assert s.vp_review_threshold_usd == Decimal("10000.00")
    assert (s.critic_max_rounds, s.extraction_max_retries, s.validation_max_tool_rounds) == (2, 2, 8)
    assert (s.payment_idle_delay_s, s.payment_max_attempts, s.payment_lock_timeout_s) == (60, 3, 30)
    assert s.api_cors_origin == "http://localhost:4200"
    assert s.upload_dir == Path("uploads")
    assert s.upload_max_bytes == 10485760
    assert s.allowed_upload_extensions == [".pdf", ".txt", ".csv", ".json", ".xml", ".eml"]
    assert s.worker_concurrency == 1


def test_dotenv_values_load(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER")
    (tmp_path / ".env").write_text(
        "LLM_PROVIDER=claude\nCLAUDE_MODEL=claude-opus-5-5\nFX_RATES={\"EUR\": \"1.10\"}\n"
        "ALLOWED_UPLOAD_EXTENSIONS=.pdf, .TXT\nPAYMENT_IDLE_DELAY_S=10\n"
    )
    s = get_settings()
    assert s.llm_provider == "claude"
    assert s.claude_model == "claude-opus-5-5"
    assert s.fx_rates == {"EUR": Decimal("1.10")}
    assert s.allowed_upload_extensions == [".pdf", ".txt"]
    assert s.payment_idle_delay_s == 10
    assert get_settings() is s  # cached


def test_env_example_matches_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER")
    monkeypatch.delenv("XAI_API_KEY")
    shutil.copy(REPO_ROOT / ".env.example", tmp_path / ".env")
    from_example = Settings().model_dump()
    (tmp_path / ".env").unlink()
    defaults = Settings().model_dump()
    # Empty keys/overrides in .env.example read as "" rather than None.
    for name in ("xai_api_key", "anthropic_api_key", "llm_provider_extraction",
                 "llm_provider_validation", "llm_provider_approval", "llm_provider_critic"):
        assert from_example.pop(name) == "" and defaults.pop(name) is None
    assert from_example == defaults
    lines = (REPO_ROOT / ".env.example").read_text().splitlines()
    names = {line.split("=", 1)[0] for line in lines if "=" in line and not line.startswith("#")}
    assert names == {name.upper() for name in Settings.model_fields}


def test_removed_suspicious_addresses_setting_is_ignored(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('SUSPICIOUS_ADDRESSES=["1600 Pennsylvania Ave"]\n')
    monkeypatch.setenv("SUSPICIOUS_ADDRESSES", '["1 Main St"]')
    assert not hasattr(get_settings(), "suspicious_addresses")


def test_removed_payment_timing_settings_are_ignored(tmp_path, monkeypatch):
    """Batch timing moved to the admin settings; the old keys in .env or the environment do nothing."""
    (tmp_path / ".env").write_text("PAYMENT_BATCH_TIME=09:30\nPAYMENT_TZ=America/New_York\n")
    monkeypatch.setenv("PAYMENT_AUTO_IDLE", "false")
    s = get_settings()
    for name in ("payment_batch_time", "payment_tz", "payment_auto_idle"):
        assert not hasattr(s, name)
    names = {line.split("=", 1)[0] for line in (REPO_ROOT / ".env.example").read_text().splitlines() if "=" in line}
    assert not names & {"PAYMENT_BATCH_TIME", "PAYMENT_TZ", "PAYMENT_AUTO_IDLE"}
