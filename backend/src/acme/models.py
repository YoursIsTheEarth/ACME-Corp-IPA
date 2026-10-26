"""Shared Pydantic models and enums exchanged by every agent.

Money is `Decimal` everywhere (serialized as strings in JSON).
"""

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class Outcome(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class FindingSource(StrEnum):
    RULE = "rule"
    LLM = "llm"


class FindingCode(StrEnum):
    # CRITICAL
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    UNKNOWN_ITEM = "UNKNOWN_ITEM"
    ZERO_STOCK = "ZERO_STOCK"
    STOCK_EXCEEDED = "STOCK_EXCEEDED"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    MATH_MISMATCH = "MATH_MISMATCH"
    MISSING_VENDOR = "MISSING_VENDOR"
    DUPLICATE = "DUPLICATE"
    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    # WARNING
    UNKNOWN_VENDOR = "UNKNOWN_VENDOR"
    MISSING_DUE_DATE = "MISSING_DUE_DATE"
    INVALID_DUE_DATE = "INVALID_DUE_DATE"
    DUE_BEFORE_INVOICE_DATE = "DUE_BEFORE_INVOICE_DATE"
    PRICE_VARIANCE = "PRICE_VARIANCE"
    SUSPICIOUS_ADDRESS = "SUSPICIOUS_ADDRESS"
    REVISION_CREDIT_DUE = "REVISION_CREDIT_DUE"
    INVOICE_NUMBER_REUSED = "INVOICE_NUMBER_REUSED"
    CURRENCY_UNSUPPORTED = "CURRENCY_UNSUPPORTED"
    # INFO
    REVISION = "REVISION"
    SUPERSEDED_BY_REVISION = "SUPERSEDED_BY_REVISION"
    NEAR_THRESHOLD = "NEAR_THRESHOLD"
    CURRENCY_CONVERTED = "CURRENCY_CONVERTED"

    @property
    def severity(self) -> Severity:
        """Canonical severity; rule-sourced findings must use it."""
        return FINDING_SEVERITY[self]


_C, _W, _I = Severity.CRITICAL, Severity.WARNING, Severity.INFO
FINDING_SEVERITY: dict[FindingCode, Severity] = {
    FindingCode.EXTRACTION_FAILED: _C,
    FindingCode.UNKNOWN_ITEM: _C,
    FindingCode.ZERO_STOCK: _C,
    FindingCode.STOCK_EXCEEDED: _C,
    FindingCode.INVALID_QUANTITY: _C,
    FindingCode.MATH_MISMATCH: _C,
    FindingCode.MISSING_VENDOR: _C,
    FindingCode.DUPLICATE: _C,
    FindingCode.FRAUD_SUSPECTED: _C,
    FindingCode.UNKNOWN_VENDOR: _W,
    FindingCode.MISSING_DUE_DATE: _W,
    FindingCode.INVALID_DUE_DATE: _W,
    FindingCode.DUE_BEFORE_INVOICE_DATE: _W,
    FindingCode.PRICE_VARIANCE: _W,
    FindingCode.SUSPICIOUS_ADDRESS: _W,
    FindingCode.REVISION_CREDIT_DUE: _W,
    FindingCode.INVOICE_NUMBER_REUSED: _W,
    FindingCode.CURRENCY_UNSUPPORTED: _W,
    FindingCode.REVISION: _I,
    FindingCode.SUPERSEDED_BY_REVISION: _I,
    FindingCode.NEAR_THRESHOLD: _I,
    FindingCode.CURRENCY_CONVERTED: _I,
}


class LineItem(BaseModel):
    sku: str | None = None  # canonical inventory item, set by normalization
    raw_name: str
    quantity: int
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    note: str | None = None


class Invoice(BaseModel):
    invoice_number: str
    revision: int = Field(0, ge=0)  # 0 = original; "R1" in source data -> 1
    vendor_name: str | None = None
    vendor_address: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    due_date_raw: str | None = None  # source text, kept when it can't be parsed
    currency: str = "USD"
    original_currency: str | None = None  # set when converted to USD
    original_total: Decimal | None = None
    line_items: list[LineItem] = []
    subtotal: Decimal | None = None
    tax: Decimal = Decimal("0")
    shipping: Decimal = Decimal("0")
    total: Decimal
    payment_terms: str | None = None
    notes: str | None = None
    extraction_confidence: float | None = Field(None, ge=0, le=1)

    @field_validator("revision", mode="before")
    @classmethod
    def _parse_revision(cls, value):
        if value is None or value == "":
            return 0
        if isinstance(value, str) and re.fullmatch(r"[Rr]\d+", value.strip()):
            return int(value.strip()[1:])
        return value


class Finding(BaseModel):
    code: FindingCode
    severity: Severity
    message: str
    evidence: dict[str, Any] = {}
    source: FindingSource = FindingSource.RULE


class Decision(BaseModel):
    outcome: Outcome
    rationale: str
    rules_applied: list[str] = []
    confidence: float = Field(1.0, ge=0, le=1)
    decided_by: str | None = None  # "Auto (rules)", "AI VP (provider/model)", or a reviewer's name


class Critique(BaseModel):
    passes: bool
    issues: list[str] = []
    suggested_outcome: Outcome | None = None


class RevisionContext(BaseModel):
    """The processed invoice that a new invoice revises (computed once by validation)."""

    original_run_id: str | None = None
    original_outcome: str | None = None
    original_revision: int = 0
    original_total: Decimal | None = None
    paid: bool = False
    paid_amount: Decimal = Decimal("0")


class InvoiceState(BaseModel):
    run_id: str
    file_path: str
    raw_text: str | None = None
    extracted: dict[str, Any] | None = None  # lenient extraction output, pre-normalization
    invoice: Invoice | None = None
    findings: list[Finding] = []
    revision_context: RevisionContext | None = None
    decision_draft: Decision | None = None
    critique: Critique | None = None
    decision: Decision | None = None
    payment_result: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = []
    retries: int = 0
