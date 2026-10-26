"""LLM extraction for TXT, PDF, and email text (F3) plus the self-correction check (F4)."""

import json
from decimal import Decimal
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from acme.ingestion.schema import ExtractedInvoice
from acme.llm import get_chat_model
from acme.normalization.cleaners import fix_ocr, parse_money

PROMPT_VERSION = "extraction.v2"
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
START_MARKER, END_MARKER = "<<<INVOICE_DATA", "INVOICE_DATA>>>"
_USER_SPLIT = "\n---- user ----\n"
TOLERANCE = Decimal("0.01")


def render_prompt(text: str, error: str | None = None) -> list[BaseMessage]:
    """System + user messages for one extraction attempt; `error` is the previous attempt's failure."""
    template = (PROMPTS_DIR / f"{PROMPT_VERSION}.md").read_text(encoding="utf-8")
    system, user = template.split(_USER_SPLIT, 1)
    schema = json.dumps(ExtractedInvoice.model_json_schema())
    # The document must not be able to close the untrusted-data block early.
    text = text.replace(START_MARKER, "[marker removed]").replace(END_MARKER, "[marker removed]")
    feedback = (
        f"\nYour previous answer failed: {error}\nReturn a corrected JSON object for the same invoice."
        if error else ""
    )
    return [
        SystemMessage(system.replace("{{schema}}", schema)),
        HumanMessage(user.replace("{{invoice_text}}", text).replace("{{feedback}}", feedback).rstrip() + "\n"),
    ]


def invoice_text_from(messages: list[BaseMessage]) -> str:
    """The invoice text inside the markers of the last user message (used by the test fake model)."""
    content = str(messages[-1].content)
    start, end = content.rfind(START_MARKER), content.rfind(END_MARKER)
    if start == -1 or end < start:
        return content
    return content[start + len(START_MARKER):end].strip("\n")


def llm_extract(text: str, error: str | None = None) -> ExtractedInvoice:
    """One structured-output extraction attempt. Raises on schema/provider failure."""
    model = get_chat_model("extraction").with_structured_output(ExtractedInvoice)
    result = model.invoke(render_prompt(text, error), config={"metadata": {"prompt_version": PROMPT_VERSION}})
    if not isinstance(result, ExtractedInvoice):  # some providers return a dict
        result = ExtractedInvoice.model_validate(result)
    return result


def _money(value) -> Decimal | None:
    return parse_money(fix_ocr(value) if isinstance(value, str) else value)


def check_line_sum(extracted: ExtractedInvoice) -> None:
    """D5: line amounts (or qty x unit price) must sum to the subtotal, else the total, within $0.01."""
    lines = Decimal("0")
    for i, item in enumerate(extracted.line_items, 1):
        amount = _money(item.amount)
        if amount is None:
            unit_price = _money(item.unit_price)
            if unit_price is None:
                raise ValueError(f"line item {i} ({item.raw_name!r}) has neither an amount nor a unit price")
            amount = unit_price * item.quantity
        lines += amount
    subtotal = _money(extracted.subtotal)
    label, expected = ("subtotal", subtotal) if subtotal is not None else ("total", _money(extracted.total))
    if expected is None or abs(lines - expected) > TOLERANCE:
        raise ValueError(
            f"line items sum to {lines:.2f} but the {label} reads {expected}; "
            f"difference {abs(lines - (expected or 0)):.2f}. Re-read every line item and the {label}."
        )
