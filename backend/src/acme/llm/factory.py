"""One place to get a chat model for an agent role.

Provider resolution for a role: run override (`use_provider`) ->
`LLM_PROVIDER_<ROLE>` -> `LLM_PROVIDER`. Agents depend only on `bind_tools`
and `with_structured_output` of what `get_chat_model(role)` returns.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from langchain_core.language_models import BaseChatModel

from acme.llm.callbacks import LLMCallRecorder
from acme.llm.offline import MODEL_NAME as OFFLINE_MODEL, RuleBasedLLM
from acme.settings import Settings, get_settings

ROLES = ("extraction", "validation", "approval", "critic")
PROVIDERS = ("grok", "claude", "offline")
KEY_SETTINGS = {"grok": "XAI_API_KEY", "claude": "ANTHROPIC_API_KEY"}

_provider_override: ContextVar[str | None] = ContextVar("acme_provider_override", default=None)


class ProviderConfigError(RuntimeError):
    """Invalid provider selection or a missing API key; stops startup."""


def _validate(provider: str, source: str) -> str:
    value = provider.strip().lower()
    if value not in PROVIDERS:
        raise ProviderConfigError(
            f"Invalid LLM provider {provider!r} from {source}; valid values are: {', '.join(PROVIDERS)}"
        )
    return value


@contextmanager
def use_provider(provider: str | None) -> Iterator[None]:
    """Override the provider for every role within this run (e.g. the CLI's --provider)."""
    token = _provider_override.set(_validate(provider, "--provider") if provider else None)
    try:
        yield
    finally:
        _provider_override.reset(token)


def resolve_provider(role: str, settings: Settings | None = None) -> str:
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}; expected one of {', '.join(ROLES)}")
    if (override := _provider_override.get()) is not None:
        return override
    settings = settings or get_settings()
    role_value = getattr(settings, f"llm_provider_{role}")
    if role_value:
        return _validate(role_value, f"LLM_PROVIDER_{role.upper()}")
    return _validate(settings.llm_provider, "LLM_PROVIDER")


def _model_name(provider: str, settings: Settings) -> str:
    return {"grok": settings.grok_model, "claude": settings.claude_model, "offline": OFFLINE_MODEL}[provider]


def get_chat_model(role: str) -> BaseChatModel:
    """Return the configured chat model for `role`, with timeout, retries, and call recording."""
    settings = get_settings()
    provider = resolve_provider(role, settings)
    model = _model_name(provider, settings)
    callbacks = [LLMCallRecorder(provider, model, role)]
    if provider == "offline":
        return RuleBasedLLM(callbacks=callbacks)

    from acme.llm.providers import RetryingChatAnthropic, RetryingChatXAI

    common = dict(
        model=model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_s,
        max_retries=0,  # retries are done (and counted) by RetryingChatMixin
        acme_max_retries=settings.llm_max_retries,
        disable_streaming=True,  # keep every call on the retrying path
        callbacks=callbacks,
    )
    if provider == "grok":
        return RetryingChatXAI(api_key=settings.xai_api_key, **common)
    return RetryingChatAnthropic(api_key=settings.anthropic_api_key, **common)


def active_models() -> dict[str, dict[str, str]]:
    """Provider and model name per role, e.g. {"critic": {"provider": "claude", "model": "..."}}."""
    settings = get_settings()
    result = {}
    for role in ROLES:
        provider = resolve_provider(role, settings)
        result[role] = {"provider": provider, "model": _model_name(provider, settings)}
    return result


def check_keys() -> None:
    """Raise ProviderConfigError if any provider in use is invalid or lacks its API key."""
    settings = get_settings()
    in_use = {resolve_provider(role, settings) for role in ROLES}
    for provider in PROVIDERS:
        env_name = KEY_SETTINGS.get(provider)
        if provider in in_use and env_name and not getattr(settings, env_name.lower()):
            raise ProviderConfigError(
                f"{env_name} is required when the {provider!r} provider is in use "
                f"(set it in .env, or use LLM_PROVIDER=offline)"
            )
