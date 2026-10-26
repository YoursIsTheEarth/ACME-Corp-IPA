"""LangChain tools over the checks, bound to one invoice and context (design D1).

The tools take no arguments: the invoice under validation is fixed when they are built,
so the LLM chooses *which* checks to run, never what data they run on. `report_finding`
lets the LLM add a judgment finding, which is always stored as `source=llm`, never CRITICAL.
"""

import json
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from acme.logging import dumps
from acme.models import Finding, FindingCode, FindingSource, Invoice, RevisionContext, Severity
from acme.validation import checks
from acme.validation.codes import for_prompt
from acme.validation.context import ValidationContext

DESCRIPTIONS = {
    "lookup_item": "Look up every line item in inventory; flags items that are not in inventory (UNKNOWN_ITEM).",
    "check_stock": "Compare the quantity billed per SKU, summed across lines, with stock "
                   "(ZERO_STOCK, STOCK_EXCEEDED).",
    "reconcile_math": "Check line amounts, line sum vs subtotal, and subtotal + tax + shipping vs total "
                      "within $0.01 (MATH_MISMATCH).",
    "check_integrity": "Check vendor presence, line quantities, and the due date against the invoice date "
                       "(MISSING_VENDOR, INVALID_QUANTITY, MISSING_DUE_DATE, INVALID_DUE_DATE, "
                       "DUE_BEFORE_INVOICE_DATE).",
    "check_duplicate": "Compare with previously processed invoices (DUPLICATE, REVISION, REVISION_CREDIT_DUE, "
                       "INVOICE_NUMBER_REUSED).",
    "check_payee_threshold": "Total the payee's invoices (by vendor name, alias, or remit-to address) over a "
                             "rolling window; over the limit is PAYEE_CUMULATIVE_THRESHOLD.",
    "check_vendor": "Check the vendor against the approved vendor list by name and alias (UNKNOWN_VENDOR).",
    "detect_prompt_injection": "Scan the document text for instructions aimed at the agents "
                               "(PROMPT_INJECTION_SUSPECTED).",
    "fraud_signals": "Score fraud signals: urgency, wire transfer, immediate terms, relative due date, unknown "
                     "vendor, suspicious address, near threshold, payee cumulative total, prompt injection "
                     "(SUSPICIOUS_ADDRESS, NEAR_THRESHOLD, FRAUD_SUSPECTED).",
    "check_prices": "Compare each USD unit price with the reference price; more than 10% off is PRICE_VARIANCE.",
}
REPORT_FINDING = "report_finding"
TOOL_NAMES = [*checks.CHECKS, REPORT_FINDING]


class NoArgs(BaseModel):
    """This tool takes no arguments; it always checks the invoice under validation."""


class ReportFindingArgs(BaseModel):
    code: FindingCode = Field(description="Finding code")
    severity: Severity = Field(description="WARNING or INFO; CRITICAL is stored as WARNING")
    message: str = Field(description="One-sentence explanation")
    evidence: dict[str, Any] = Field(default_factory=dict, description="Values that support the finding")


class ToolRun:
    """Records what the tools produced, so the sweep knows which checks already ran."""

    def __init__(self) -> None:
        self.results: dict[str, list[Finding]] = {}
        self.revision_context: RevisionContext | None = None
        self.llm_findings: list[Finding] = []


def llm_finding(code: FindingCode, severity: Severity, message: str, evidence: dict[str, Any]) -> Finding:
    """An LLM judgment finding, capped at WARNING."""
    if severity == Severity.CRITICAL:
        severity = Severity.WARNING
    return Finding(code=code, severity=severity, message=message, evidence=evidence, source=FindingSource.LLM)


def run_check(name: str, invoice: Invoice, ctx: ValidationContext, run: ToolRun) -> list[Finding]:
    if name == "check_duplicate":
        findings, run.revision_context = checks.detect_duplicate(invoice, ctx)
    else:
        findings = checks.CHECKS[name](invoice, ctx)
    run.results[name] = findings
    return findings


def _result(findings: list[Finding]) -> str:
    return dumps([for_prompt(f).model_dump(mode="json", include={"code", "severity", "message", "evidence"})
                  for f in findings])


def build_tools(invoice: Invoice, ctx: ValidationContext, run: ToolRun) -> list[BaseTool]:
    tools: list[BaseTool] = [
        StructuredTool.from_function(
            func=lambda _name=name: _result(run_check(_name, invoice, ctx, run)),
            name=name, description=DESCRIPTIONS[name], args_schema=NoArgs,
        )
        for name in checks.CHECKS
    ]

    def report_finding(code: FindingCode, severity: Severity, message: str,
                       evidence: dict[str, Any] | None = None) -> str:
        stored = llm_finding(code, severity, message, evidence or {})
        run.llm_findings.append(stored)
        return json.dumps({"recorded": stored.code.value, "severity": stored.severity.value})

    tools.append(StructuredTool.from_function(
        func=report_finding, name=REPORT_FINDING, args_schema=ReportFindingArgs,
        description="Record a judgment finding that no check covers. Severity is capped at WARNING.",
        handle_validation_error=True,
    ))
    return tools
