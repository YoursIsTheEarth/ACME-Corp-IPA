"""LLM address plausibility (F11, design D3): is the vendor address plausible for a supplier?

`run_validation` calls `assess_address` once per invoice, before the tool loop, so the verdict
always applies; `fraud_signals` and `fraud_score` read it from `ValidationContext`.
"""

import json
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from acme.llm import get_chat_model
from acme.models import Invoice

AGENT = "validation"
PROMPT_VERSION = "address_v1"
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_USER_SPLIT = "\n---- user ----\n"


class AddressAssessment(BaseModel):
    plausible: bool
    reason: str
    confidence: float = Field(ge=0, le=1)


def render_prompt(invoice: Invoice) -> list[BaseMessage]:
    from acme.validation.agent import untrusted  # agent imports this module

    system, user = (PROMPTS_DIR / f"{PROMPT_VERSION}.md").read_text(encoding="utf-8").split(_USER_SPLIT, 1)
    data = json.dumps({"vendor_name": invoice.vendor_name, "vendor_address": invoice.vendor_address}, indent=2)
    return [SystemMessage(system), HumanMessage(user.replace("{{address}}", untrusted(data)))]


def assess_address(invoice: Invoice) -> AddressAssessment | None:
    """The model's verdict on `invoice.vendor_address`; None (and no call) when there is no address."""
    if not (invoice.vendor_address or "").strip():
        return None
    model = get_chat_model(AGENT).with_structured_output(AddressAssessment)
    result = model.invoke(render_prompt(invoice), config={"metadata": {"prompt_version": PROMPT_VERSION}})
    return result if isinstance(result, AddressAssessment) else AddressAssessment.model_validate(result)
