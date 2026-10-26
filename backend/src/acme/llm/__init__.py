"""LLM access: `get_chat_model(role)` plus the offline `RuleBasedLLM` registries."""

from acme.llm.factory import (
    PROVIDERS,
    ROLES,
    ProviderConfigError,
    active_models,
    check_keys,
    get_chat_model,
    resolve_provider,
    use_provider,
)
from acme.llm.offline import RuleBasedLLM, register_handler, register_tool_plan

__all__ = [
    "PROVIDERS",
    "ROLES",
    "ProviderConfigError",
    "RuleBasedLLM",
    "active_models",
    "check_keys",
    "get_chat_model",
    "register_handler",
    "register_tool_plan",
    "resolve_provider",
    "use_provider",
]
