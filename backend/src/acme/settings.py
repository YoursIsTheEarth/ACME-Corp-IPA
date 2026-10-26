"""Application settings, loaded from the environment and `.env`.

One catalog for every change: later changes only read these fields.
Field names are lowercase; the matching environment variables are the
uppercase names (e.g. `llm_provider` <- `LLM_PROVIDER`).
"""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_FRAUD_SIGNAL_WEIGHTS: dict[str, float] = {
    "urgency_language": 0.25,
    "wire_transfer": 0.25,
    "immediate_terms": 0.15,
    "relative_due_date": 0.15,
    "unknown_vendor": 0.20,
    "suspicious_address": 0.30,
    "near_threshold": 0.10,
    "payee_cumulative": 0.25,
    "prompt_injection": 0.60,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Storage
    db_path: Path = Path("acme.db")

    # LLM
    llm_provider: str = "grok"
    grok_model: str = "grok-4"
    claude_model: str = "claude-sonnet-5-5"
    llm_temperature: float = 0.0
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 3
    xai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # LLM per-role overrides (P1, F37)
    llm_provider_extraction: str | None = None
    llm_provider_validation: str | None = None
    llm_provider_approval: str | None = None
    llm_provider_critic: str | None = None

    # FX: USD per one unit of the foreign currency
    fx_rates: dict[str, Decimal] = {"EUR": Decimal("1.08")}

    # Validation
    price_variance_pct: Decimal = Decimal("10")
    math_rounding_tolerance_usd: Decimal = Decimal("1.00")  # math off by up to this much goes to review
    near_threshold_floor_usd: Decimal = Decimal("9500.00")
    fraud_signal_weights: dict[str, float] = DEFAULT_FRAUD_SIGNAL_WEIGHTS  # a setting is merged over these
    fraud_threshold: float = 0.60

    # Payee registry: cumulative payee total over a rolling window
    payee_window_days: int = 30
    payee_cumulative_threshold_usd: Decimal = Decimal("10000.00")

    # Approval
    vp_review_threshold_usd: Decimal = Decimal("10000.00")
    critic_max_rounds: int = 2
    extraction_max_retries: int = 2
    validation_max_tool_rounds: int = 8

    # Payments (batch timing lives in the admin settings, `acme.admin`)
    payment_idle_delay_s: int = 60
    payment_max_attempts: int = 3
    payment_lock_timeout_s: int = 30

    # API
    api_cors_origin: str = "http://localhost:4200"
    upload_dir: Path = Path("uploads")
    upload_max_bytes: int = 10_485_760
    allowed_upload_extensions: Annotated[list[str], NoDecode] = [
        ".pdf", ".txt", ".csv", ".json", ".xml", ".eml",
    ]
    worker_concurrency: int = 1

    @field_validator("fraud_signal_weights")
    @classmethod
    def _merge_fraud_weights(cls, value):
        """A signal the setting omits keeps its default weight (an older .env cannot switch a signal off)."""
        return {**DEFAULT_FRAUD_SIGNAL_WEIGHTS, **value}

    @field_validator("allowed_upload_extensions", mode="before")
    @classmethod
    def _split_extensions(cls, value):
        if isinstance(value, str):
            return [part.strip().lower() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (call `get_settings.cache_clear()` to reload)."""
    return Settings()
