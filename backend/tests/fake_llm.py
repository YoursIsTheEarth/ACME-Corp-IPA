"""Test-only fake chat model: deterministic stand-in for Grok/Claude (design D4).

Never reachable from settings or the CLI: tests (root `conftest.py`) and the e2e app factory
(`fake_server.py`) install it by replacing `acme.llm.factory._build_model`.

    @register_handler(Invoice)
    def extract(messages: list[BaseMessage]) -> Invoice | dict: ...

    register_tool_plan(lambda messages, tool_names: [{"name": "check_stock", "args": {...}}])

`with_structured_output(schema)` dispatches to the handler registered for `schema`;
`bind_tools(tools)` emits the tool-call plan once, then a final message with no tool calls
after tool results come back. No randomness, no clock reads, no network. Calls are recorded
in `llm_calls` with provider `fake`.
"""

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from acme.approval.policy import STRICTNESS
from acme.ingestion.llm_extract import invoice_text_from
from acme.ingestion.schema import ExtractedInvoice
from acme.llm import factory
from acme.llm.callbacks import LLMCallRecorder
from acme.models import Critique, Decision, Outcome
from acme.normalization.llm_fallback import DateSuggestion, SkuSuggestion
from acme.validation.address import AddressAssessment
from acme.validation.agent import END, START
from acme.validation.tools import REPORT_FINDING

StructuredHandler = Callable[[list[BaseMessage]], BaseModel | dict[str, Any]]
ToolPlan = Callable[[list[BaseMessage], list[str]], list[dict[str, Any]]]

PROVIDER = "fake"
MODEL_NAME = "fake-model"
FINAL_MESSAGE = "Tool plan complete."

_HANDLERS: dict[type[BaseModel], StructuredHandler] = {}


def default_tool_plan(messages: list[BaseMessage], tool_names: list[str]) -> list[dict[str, Any]]:
    """Call every check tool once, in the order bound, with no arguments (never `report_finding`)."""
    return [{"name": name, "args": {}} for name in tool_names if name != REPORT_FINDING]


_tool_plan: ToolPlan = default_tool_plan


def register_handler(schema: type[BaseModel], handler: StructuredHandler | None = None):
    """Register the fake's handler for `schema` (usable as a decorator)."""
    def _register(fn: StructuredHandler) -> StructuredHandler:
        _HANDLERS[schema] = fn
        return fn
    return _register(handler) if handler is not None else _register


def register_tool_plan(plan: ToolPlan | None) -> None:
    """Replace the tool plan (`None` restores the default)."""
    global _tool_plan
    _tool_plan = plan or default_tool_plan


def _tool_name(tool: Any) -> str:
    return convert_to_openai_tool(tool)["function"]["name"]


class FakeChatModel(BaseChatModel):
    model_name: str = MODEL_NAME

    @property
    def _llm_type(self) -> str:
        return "fake-test-model"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:
        return self.bind(fake_tools=[_tool_name(t) for t in tools], **kwargs)

    def with_structured_output(self, schema, *, include_raw: bool = False, **kwargs: Any) -> Runnable:
        if include_raw:
            raise NotImplementedError("FakeChatModel does not support include_raw")
        parse = RunnableLambda(lambda message: schema.model_validate_json(message.content))
        return self.bind(fake_schema=schema) | parse

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        schema = kwargs.get("fake_schema")
        tools = kwargs.get("fake_tools")
        if schema is not None:
            handler = _HANDLERS.get(schema)
            if handler is None:
                raise LookupError(f"No fake handler registered for schema {schema.__name__}")
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


def build_model(provider: str, model: str, settings, callbacks: list) -> FakeChatModel:
    """Drop-in for `acme.llm.factory._build_model`: the fake, recording calls as provider `fake`."""
    recorders = [LLMCallRecorder(PROVIDER, MODEL_NAME, cb.role) if isinstance(cb, LLMCallRecorder) else cb
                 for cb in callbacks]
    return FakeChatModel(callbacks=recorders)


def install(monkeypatch) -> None:
    """Route every `get_chat_model` call to the fake and restore the default handlers."""
    monkeypatch.setattr(factory, "_build_model", build_model)
    reset()


# --- Extraction: regexes for the text layouts in the sample data ---------------------------
# Handles labelled lines (also typo labels such as `Vndr`, `Itms`, `Amt`, and two labels on
# one line), `qty:`/`@` item lines, `- Name xN $P each` email lines, and fixed-width
# `Qty Rate/Price Amount` tables. Like a real model it transcribes values as printed and
# leaves cleanup to the normalizer.

# Label alternatives, tried in order at each position (longer forms first).
_LABELS = [
    ("invoice_number", r"(?:invoice|inv)(?:\s*(?:number|no\.?))?\s*(?:#\s*:?|:)"),
    ("due_date", r"due(?:\s*(?:date|dt))?\s*:"),
    ("invoice_date", r"(?:date|dt)\s*:"),
    ("vendor_name", r"(?:vendor|vndr)\s*:"),
    ("from", r"from\s*:"),
    ("subtotal", r"sub\s*total\s*:"),
    ("tax", r"(?:sales\s+)?tax(?:\s*\([^)]*\))?\s*:"),
    ("shipping", r"shipping\s*:"),
    ("total", r"(?:grand\s+)?total(?:\s+amount)?\s*:|amt\s*:"),
    ("payment_terms", r"(?:payment|pymnt)\s+terms\s*:|terms\s*:"),
    ("notes", r"notes?\s*:"),
]
_LABEL_RE = re.compile(
    "|".join(rf"(?P<{name}>(?<![\w#-]){pattern})" for name, pattern in _LABELS), re.IGNORECASE
)

_MONEY = r"-?\$?\d[\d,Oo]*(?:\.[\dOo]+)?"
_QTY_LINE = re.compile(
    rf"^\s*(?P<name>\S.*?)\s+qty:?\s*(?P<qty>-?\d+)\s+(?:unit\s+price:?|@)\s*(?P<price>{_MONEY})",
    re.IGNORECASE,
)
_EMAIL_LINE = re.compile(rf"^\s*[-*]\s*(?P<name>\S.*?)\s+x\s*(?P<qty>-?\d+)\s+(?P<price>{_MONEY})", re.IGNORECASE)
_TABLE_HEADER = re.compile(r"\bqty\b.*\b(?:rate|price)\b", re.IGNORECASE)
_TABLE_ROW = re.compile(
    rf"^\s*(?P<name>\S.*?)\s+(?P<qty>-?\d+)\s+(?P<price>{_MONEY})\s+(?P<amount>{_MONEY})(?:\s+(?P<note>\S.*?))?\s*$"
)
_QUALIFIER = re.compile(r"^(?P<name>.*?)\s*\((?P<note>[^)]*)\)$")


def _labels(line: str) -> list[tuple[str, str]]:
    """(field, value) pairs on one line; a `notes` value runs to the end of the line."""
    matches = list(_LABEL_RE.finditer(line))
    pairs = []
    for i, match in enumerate(matches):
        field = match.lastgroup
        end = len(line) if field == "notes" or i + 1 == len(matches) else matches[i + 1].start()
        pairs.append((field, line[match.end():end].strip()))
        if field == "notes":
            break
    return pairs


def _item(name: str, qty: str, price: str, amount: str | None = None, note: str | None = None) -> dict:
    name = name.strip()
    if note is None and (qualifier := _QUALIFIER.match(name)):
        name, note = qualifier.group("name"), qualifier.group("note")
    return {"raw_name": name, "quantity": int(qty), "unit_price": price, "amount": amount, "note": note}


def extract_text(text: str) -> dict[str, Any]:
    """Regex extraction of a text invoice into an `ExtractedInvoice`-shaped dict."""
    fields: dict[str, Any] = {}
    items: list[dict] = []
    lines = text.splitlines()
    in_table = False
    i = 0
    while i < len(lines):
        line = lines[i]
        pairs = _labels(line)
        if pairs:
            in_table = False
            for field, value in pairs:
                if field == "notes":
                    notes = [value]
                    while i + 1 < len(lines) and lines[i + 1].strip() and not _labels(lines[i + 1]):
                        i += 1
                        notes.append(lines[i].strip())
                    value = " ".join(part for part in notes if part)
                if field == "from" and "@" in value:
                    continue
                if value:
                    fields.setdefault(field, value)
        elif in_table and (row := _TABLE_ROW.match(line)):
            items.append(_item(row["name"], row["qty"], row["price"], row["amount"], row["note"]))
        elif row := _QTY_LINE.match(line) or _EMAIL_LINE.match(line):
            items.append(_item(row["name"], row["qty"], row["price"]))
        elif _TABLE_HEADER.search(line):
            in_table = True
        elif not line.strip():
            in_table = False
        i += 1
    vendor = fields.pop("vendor_name", None) or fields.pop("from", None)
    fields.pop("from", None)
    return {**fields, "vendor_name": vendor, "line_items": items}


def extraction(messages: list[BaseMessage]) -> dict[str, Any]:
    return extract_text(invoice_text_from(messages))


# --- Approval and Critic: template rationale; critic checks floor and fired rules ------------

def read_block(messages: list[BaseMessage], name: str):
    """The JSON in the last `<name>...</name>` block of the last message (the policy block comes last)."""
    content = str(messages[-1].content)
    matches = re.findall(rf"<{name}>\n(.*?)\n</{name}>", content, re.DOTALL)
    return json.loads(matches[-1]) if matches else None


def approval_draft(messages: list[BaseMessage]) -> Decision:
    policy = read_block(messages, "policy")
    findings = read_block(messages, "findings") or []
    floor, rules = Outcome(policy["floor"]), policy["rules"]
    fired = ", ".join(rules)
    if floor == Outcome.REJECT:
        details = "; ".join(f"{f['code']}: {f['message']}" for f in findings if f["severity"] == "CRITICAL")
        rationale = f"Rejected ({fired}). {details}."
    elif floor == Outcome.NEEDS_REVIEW:
        details = "; ".join(f"{f['code']}: {f['message']}" for f in findings if f["severity"] == "WARNING")
        rationale = (f"Held for review ({fired}). {details or 'Policy requires a human decision'}. "
                     "Recommend a person confirm these points with the vendor before paying.")
    elif policy["vp_scrutiny"]:
        rationale = (f"Approved under VP scrutiny ({fired}): no CRITICAL or WARNING findings; "
                     "items, vendor, and totals reconcile.")
    else:
        rationale = f"Approved ({fired}): no blocking findings."
    return Decision(outcome=floor, rationale=rationale, rules_applied=rules, confidence=1.0)


def critic_review(messages: list[BaseMessage]) -> Critique:
    policy = read_block(messages, "policy")
    draft = Decision.model_validate(read_block(messages, "draft"))
    floor = Outcome(policy["floor"])
    issues = []
    if STRICTNESS[draft.outcome] < STRICTNESS[floor]:
        issues.append(f"Draft outcome {draft.outcome} is looser than the policy floor {floor}.")
    issues += [f"Rationale does not name fired rule {rule}." for rule in policy["rules"] if rule not in draft.rationale]
    return Critique(passes=not issues, issues=issues, suggested_outcome=floor if issues else None)


# --- Address plausibility: a test-local landmark table (test data, not app logic) ------------

LANDMARKS = {
    "1600 pennsylvania ave": "1600 Pennsylvania Ave is the White House, a government building, not a supplier.",
    "350 fifth avenue": "350 Fifth Avenue is the Empire State Building, a landmark, not a supplier address.",
}


def address_payload(messages: list[BaseMessage]) -> dict[str, Any]:
    """The JSON the address prompt puts between the untrusted-data delimiters."""
    content = str(messages[-1].content)
    return json.loads(content[content.rfind(START) + len(START):content.rfind(END)])


def address_verdict(messages: list[BaseMessage]) -> AddressAssessment:
    address = " ".join((address_payload(messages).get("vendor_address") or "").split()).casefold()
    reason = next((why for landmark, why in LANDMARKS.items() if landmark in address), None)
    if reason:
        return AddressAssessment(plausible=False, reason=reason, confidence=0.95)
    return AddressAssessment(plausible=True, reason="An ordinary commercial street address.", confidence=0.9)


def reset() -> None:
    """Restore every default handler and the default tool plan."""
    _HANDLERS.clear()
    register_handler(ExtractedInvoice, extraction)
    register_handler(Decision, approval_draft)
    register_handler(Critique, critic_review)
    register_handler(SkuSuggestion, lambda messages: SkuSuggestion())
    register_handler(DateSuggestion, lambda messages: DateSuggestion())
    register_handler(AddressAssessment, address_verdict)
    register_tool_plan(None)
