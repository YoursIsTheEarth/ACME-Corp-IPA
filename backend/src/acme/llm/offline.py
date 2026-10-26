"""Offline, deterministic stand-in for the real chat models.

Later changes teach it their schemas and tool plans:

    @register_handler(Invoice)
    def extract(messages: list[BaseMessage]) -> Invoice | dict: ...

    register_tool_plan(lambda messages, tool_names: [{"name": "check_stock", "args": {...}}])

`with_structured_output(schema)` dispatches to the handler registered for `schema`;
`bind_tools(tools)` emits the tool-call plan once, then a final message with no tool calls
after tool results come back. No randomness, no clock reads, no network.
"""

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

StructuredHandler = Callable[[list[BaseMessage]], BaseModel | dict[str, Any]]
ToolPlan = Callable[[list[BaseMessage], list[str]], list[dict[str, Any]]]

_HANDLERS: dict[type[BaseModel], StructuredHandler] = {}


def _default_tool_plan(messages: list[BaseMessage], tool_names: list[str]) -> list[dict[str, Any]]:
    """Call each bound tool once, in the order bound, with no arguments."""
    return [{"name": name, "args": {}} for name in tool_names]


_tool_plan: ToolPlan = _default_tool_plan

FINAL_MESSAGE = "Tool plan complete."
MODEL_NAME = "rule-based"


def register_handler(schema: type[BaseModel], handler: StructuredHandler | None = None):
    """Register the offline handler for `schema` (usable as a decorator)."""
    def _register(fn: StructuredHandler) -> StructuredHandler:
        _HANDLERS[schema] = fn
        return fn
    return _register(handler) if handler is not None else _register


def register_tool_plan(plan: ToolPlan | None) -> None:
    """Replace the fixed tool plan (`None` restores the default)."""
    global _tool_plan
    _tool_plan = plan or _default_tool_plan


def _tool_name(tool: Any) -> str:
    return convert_to_openai_tool(tool)["function"]["name"]


class RuleBasedLLM(BaseChatModel):
    model_name: str = MODEL_NAME

    @property
    def _llm_type(self) -> str:
        return "rule-based-offline"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:
        return self.bind(offline_tools=[_tool_name(t) for t in tools], **kwargs)

    def with_structured_output(self, schema, *, include_raw: bool = False, **kwargs: Any) -> Runnable:
        if include_raw:
            raise NotImplementedError("RuleBasedLLM does not support include_raw")
        parse = RunnableLambda(lambda message: schema.model_validate_json(message.content))
        return self.bind(offline_schema=schema) | parse

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        schema = kwargs.get("offline_schema")
        tools = kwargs.get("offline_tools")
        if schema is not None:
            handler = _HANDLERS.get(schema)
            if handler is None:
                raise LookupError(f"No offline handler registered for schema {schema.__name__}")
            result = handler(list(messages))
            obj = result if isinstance(result, schema) else schema.model_validate(result)
            message = AIMessage(content=obj.model_dump_json())
        elif tools:
            if any(isinstance(m, ToolMessage) for m in messages):
                message = AIMessage(content=FINAL_MESSAGE)
            else:
                calls = _tool_plan(list(messages), list(tools))
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {"name": c["name"], "args": c.get("args", {}), "id": f"call_{i}_{c['name']}",
                         "type": "tool_call"}
                        for i, c in enumerate(calls)
                    ],
                )
        else:
            message = AIMessage(content="")
        message.usage_metadata = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        message.response_metadata = {"model_name": self.model_name, "retries": 0}
        return ChatResult(generations=[ChatGeneration(message=message)])
