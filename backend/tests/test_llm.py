import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from acme.llm import (
    ProviderConfigError, RuleBasedLLM, active_models, check_keys, get_chat_model,
    register_handler, register_tool_plan, use_provider,
)
from acme.llm import retry
from acme.llm.callbacks import LLMCallRecorder
from acme.logging import run_context
from acme.models import Decision, Outcome


@pytest.fixture(autouse=True)
def _offline_registries():
    register_handler(Decision, lambda messages: Decision(
        outcome=Outcome.APPROVE, rationale=f"Template rationale for: {messages[-1].content}"))
    yield
    register_tool_plan(None)


@tool
def check_stock(sku: str) -> str:
    """Check stock for a SKU."""
    return "15"


@tool
def check_vendor(name: str) -> str:
    """Check a vendor."""
    return "approved"


# --- RuleBasedLLM -----------------------------------------------------------

def test_offline_structured_output_is_deterministic(db):
    model = RuleBasedLLM().with_structured_output(Decision)
    first = model.invoke([HumanMessage("INV-1001")])
    second = model.invoke([HumanMessage("INV-1001")])
    assert isinstance(first, Decision) and first == second
    assert first.rationale == "Template rationale for: INV-1001"


def test_offline_missing_handler_raises():
    class Unregistered(Decision):
        pass
    with pytest.raises(LookupError, match="Unregistered"):
        RuleBasedLLM().with_structured_output(Unregistered).invoke("x")


def test_offline_tool_plan_then_final_message():
    register_tool_plan(lambda messages, names: [{"name": n, "args": {"sku": "WidgetA"} if n == "check_stock"
                                                 else {"name": "Widgets Inc."}} for n in names])
    model = RuleBasedLLM().bind_tools([check_stock, check_vendor])
    first = model.invoke([HumanMessage("validate")])
    assert [c["name"] for c in first.tool_calls] == ["check_stock", "check_vendor"]
    assert first.tool_calls[0]["args"] == {"sku": "WidgetA"}
    assert model.invoke([HumanMessage("validate")]).tool_calls == first.tool_calls
    results = [ToolMessage(content="15", tool_call_id=first.tool_calls[0]["id"]),
               ToolMessage(content="approved", tool_call_id=first.tool_calls[1]["id"])]
    final = model.invoke([HumanMessage("validate"), first, *results])
    assert final.tool_calls == [] and final.content


def test_offline_default_tool_plan_calls_each_tool():
    first = RuleBasedLLM().bind_tools([check_vendor]).invoke("validate")
    assert [(c["name"], c["args"]) for c in first.tool_calls] == [("check_vendor", {})]


# --- factory ------------------------------------------------------------------

def test_default_provider_is_grok(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    from langchain_xai import ChatXAI
    model = get_chat_model("extraction")
    assert isinstance(model, ChatXAI)
    assert model.model_name == "grok-4" and model.temperature == 0
    assert model.request_timeout == 30 and model.max_retries == 0 and model.acme_max_retries == 3
    assert any(isinstance(cb, LLMCallRecorder) for cb in model.callbacks)


def test_claude_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from langchain_anthropic import ChatAnthropic
    model = get_chat_model("approval")
    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-sonnet-5-5" and model.default_request_timeout == 30


def test_run_override_wins(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    with use_provider("offline"):
        assert all(isinstance(get_chat_model(r), RuleBasedLLM)
                   for r in ("extraction", "validation", "approval", "critic"))
        check_keys()  # offline needs no key
    assert active_models()["critic"]["provider"] == "grok"


def test_invalid_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gpt")
    with pytest.raises(ProviderConfigError) as err:
        check_keys()
    assert all(v in str(err.value) for v in ("grok", "claude", "offline"))
    with pytest.raises(ProviderConfigError):
        get_chat_model("extraction")


def test_missing_grok_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    with pytest.raises(ProviderConfigError, match="XAI_API_KEY"):
        check_keys()


def test_offline_needs_no_keys():
    check_keys()


def test_active_models_claude(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5-5")
    models = active_models()
    assert set(models) == {"extraction", "validation", "approval", "critic"}
    assert all(m == {"provider": "claude", "model": "claude-opus-5-5"} for m in models.values())


def test_critic_override_only_affects_critic(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    monkeypatch.setenv("LLM_PROVIDER_CRITIC", "claude")
    monkeypatch.setenv("XAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    from langchain_anthropic import ChatAnthropic
    from langchain_xai import ChatXAI
    assert isinstance(get_chat_model("critic"), ChatAnthropic)
    for role in ("extraction", "validation", "approval"):
        assert isinstance(get_chat_model(role), ChatXAI)
    assert active_models()["critic"]["provider"] == "claude"
    assert active_models()["approval"]["provider"] == "grok"


def test_critic_override_key_checked(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "x")
    monkeypatch.setenv("LLM_PROVIDER_CRITIC", "claude")
    with pytest.raises(ProviderConfigError, match="ANTHROPIC_API_KEY"):
        check_keys()


# --- call recording and retries ------------------------------------------------

def test_offline_call_recorded(db):
    model = get_chat_model("approval").with_structured_output(Decision)
    with run_context("r-123"):
        model.invoke([HumanMessage("INV-1001")], config={"metadata": {"prompt_version": "approval.v1"}})
    row = db.execute("SELECT * FROM llm_calls").fetchone()
    assert (row["run_id"], row["agent"], row["provider"], row["model"]) == ("r-123", "approval", "offline", "rule-based")
    assert (row["prompt_version"], row["tokens_in"], row["tokens_out"], row["retries"], row["failed"]) == \
        ("approval.v1", 0, 0, 0, 0)


class _StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _FlakyModel(BaseChatModel):
    statuses: list[int]
    calls: int = 0

    @property
    def _llm_type(self):
        return "flaky"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.statuses:
            raise _StatusError(self.statuses.pop(0))
        message = AIMessage(content="ok", usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15})
        return ChatResult(generations=[ChatGeneration(message=message)])


class _RetryingFlaky(retry.RetryingChatMixin, _FlakyModel):
    acme_max_retries: int = 3


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(retry, "sleep", calls.append)
    return calls


def test_429_twice_then_success(db, sleeps):
    model = _RetryingFlaky(statuses=[429, 429], callbacks=[LLMCallRecorder("claude", "claude-sonnet-5-5", "approval")])
    with run_context("r-123"):
        assert model.invoke("hi").content == "ok"
    assert model.calls == 3 and sleeps == [0.5, 1.0]
    row = db.execute("SELECT * FROM llm_calls").fetchone()
    assert (row["provider"], row["retries"], row["failed"], row["tokens_in"], row["tokens_out"]) == \
        ("claude", 2, 0, 12, 3)


def test_5xx_exhausts_retries(db, sleeps):
    model = _RetryingFlaky(statuses=[503] * 10, callbacks=[LLMCallRecorder("grok", "grok-4", "validation")])
    with pytest.raises(_StatusError):
        model.invoke("hi")
    assert model.calls == 4 and sleeps == [0.5, 1.0, 2.0]  # 1 try + LLM_MAX_RETRIES retries
    row = db.execute("SELECT * FROM llm_calls").fetchone()
    assert (row["retries"], row["failed"]) == (3, 1) and "503" in row["error"]


def test_non_retryable_error_not_retried(db, sleeps):
    model = _RetryingFlaky(statuses=[400])
    with pytest.raises(_StatusError):
        model.invoke("hi")
    assert model.calls == 1 and sleeps == []


def test_real_sdk_errors_classified():
    import anthropic
    import httpx
    import openai
    request = httpx.Request("POST", "https://example.invalid")
    for sdk in (openai, anthropic):
        def err(cls, status):
            return cls("x", response=httpx.Response(status, request=request), body=None)
        assert retry.is_retryable(err(sdk.RateLimitError, 429))
        assert retry.is_retryable(err(sdk.InternalServerError, 503))
        assert not retry.is_retryable(err(sdk.BadRequestError, 400))
