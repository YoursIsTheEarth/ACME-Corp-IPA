"""Scripted stand-ins for chat models, for tests that need a misbehaving LLM."""

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedToolModel(BaseChatModel):
    """`bind_tools` model whose reply is `script(messages, call_no)`."""

    script: Callable[[list[BaseMessage], int], AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=self.script(list(messages), self.calls))])


def tool_calls(*names: str, args: dict | None = None, round_no: int = 0) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": n, "args": args or {}, "id": f"c{round_no}_{i}", "type": "tool_call"}
                                             for i, n in enumerate(names)])


class ScriptedStructured:
    """`get_chat_model(role)` replacement: each `with_structured_output(schema).invoke` pops the next reply."""

    def __init__(self, replies: dict[type, list]) -> None:
        self.replies = {schema: list(items) for schema, items in replies.items()}
        self.prompts: list[tuple[type, list[BaseMessage]]] = []

    def __call__(self, role: str):
        return self

    def with_structured_output(self, schema):
        fake = self

        class _Bound:
            def invoke(self, messages, config=None):
                fake.prompts.append((schema, messages))
                return fake.replies[schema].pop(0)
        return _Bound()
