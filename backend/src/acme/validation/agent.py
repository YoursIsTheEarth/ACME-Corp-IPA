"""`run_validation(state)`: the tool-calling Validation agent (F13, design D2).

The LLM picks which checks to call (at most `validation_max_tool_rounds` rounds); then every
check it skipped runs anyway. `state.findings` becomes the de-duplicated union of the earlier
findings (normalization), every deterministic check, and capped LLM judgment findings.
"""

import dataclasses
import json
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from acme.llm import active_models, get_chat_model
from acme.logging import agent_context, audit, dumps, run_context
from acme.models import Finding, Invoice, InvoiceState
from acme.settings import get_settings
from acme.validation import checks
from acme.validation.address import assess_address
from acme.validation.context import ValidationContext
from acme.validation.tools import ToolRun, build_tools, run_check

AGENT = "validation"
PROMPT_VERSION = "validation_v1"
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
START, END = "<untrusted_invoice>", "</untrusted_invoice>"
_USER_SPLIT = "\n---- user ----\n"


def untrusted(text: str) -> str:
    """Wrap untrusted text in the delimiters, removing any delimiter it contains."""
    for marker in (START, END):
        text = text.replace(marker, "[marker removed]")
    return f"{START}\n{text}\n{END}"


def render_prompt(invoice: Invoice) -> list[BaseMessage]:
    system, user = (PROMPTS_DIR / f"{PROMPT_VERSION}.md").read_text(encoding="utf-8").split(_USER_SPLIT, 1)
    invoice_json = invoice.model_dump_json(indent=2, exclude_none=True)
    return [SystemMessage(system), HumanMessage(user.replace("{{invoice}}", untrusted(invoice_json)))]


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Keep the first finding per (code, evidence)."""
    seen, result = set(), []
    for f in findings:
        key = (f.code, json.dumps(f.evidence, sort_keys=True, default=str))
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result


def _trace(state: InvoiceState, event: str, payload: dict) -> None:
    entry = {"agent": AGENT, "event": event, **payload}
    state.trace.append(json.loads(dumps(entry)))
    audit(state.run_id, AGENT, event, payload)


def _agent_loop(state: InvoiceState, invoice: Invoice, ctx: ValidationContext, run: ToolRun) -> None:
    tools = build_tools(invoice, ctx, run)
    by_name = {tool.name: tool for tool in tools}
    model = get_chat_model(AGENT).bind_tools(tools)
    llm = active_models()[AGENT]
    messages = render_prompt(invoice)
    max_rounds = get_settings().validation_max_tool_rounds
    for round_no in range(1, max_rounds + 1):
        reply = model.invoke(messages, config={"metadata": {"prompt_version": PROMPT_VERSION}})
        messages.append(reply)
        if not reply.tool_calls:
            _trace(state, "validation.summary", {"rounds": round_no - 1, "summary": str(reply.content), **llm})
            return
        _trace(state, "validation.tool_calls", {"round": round_no, "tools": [c["name"] for c in reply.tool_calls],
                                                **llm})
        for call in reply.tool_calls:
            tool = by_name.get(call["name"])
            if tool is None:
                messages.append(ToolMessage(content=f"Unknown tool {call['name']!r}", tool_call_id=call["id"]))
            else:
                messages.append(tool.invoke(call))
    _trace(state, "validation.tool_round_cap", {"rounds": max_rounds, **llm})


def run_validation(state: InvoiceState, ctx: ValidationContext | None = None) -> InvoiceState:
    """Validate `state.invoice`; returns a new state with findings, revision context, and trace."""
    state = state.model_copy(deep=True)
    if state.invoice is None:
        return state
    invoice = state.invoice
    ctx = ctx or ValidationContext.load()
    run = ToolRun()
    with run_context(state.run_id), agent_context(AGENT):
        ctx = dataclasses.replace(ctx, address_assessment=assess_address(invoice))
        _agent_loop(state, invoice, ctx, run)
        swept = [name for name in checks.CHECKS if name not in run.results]
        for name in swept:
            run_check(name, invoice, ctx, run)
        deterministic = [f for name in checks.CHECKS for f in run.results[name]]
        state.findings = dedupe([*state.findings, *deterministic, *run.llm_findings])
        state.revision_context = run.revision_context
        _trace(state, "validation.findings", {
            "swept": swept,
            "findings": [f.model_dump(mode="json") for f in state.findings],
            "revision_context": run.revision_context.model_dump(mode="json") if run.revision_context else None,
        })
    return state
