"""LLM access: `get_chat_model(role)` and the API key status that gates invoice processing."""

from acme.llm.factory import (
    PROVIDERS,
    ROLES,
    KeyStatus,
    ProviderConfigError,
    active_models,
    get_chat_model,
    key_status,
    missing_key_message,
    require_llm,
    resolve_provider,
    use_provider,
)

__all__ = [
    "PROVIDERS",
    "ROLES",
    "KeyStatus",
    "ProviderConfigError",
    "active_models",
    "get_chat_model",
    "key_status",
    "missing_key_message",
    "require_llm",
    "resolve_provider",
    "use_provider",
]
