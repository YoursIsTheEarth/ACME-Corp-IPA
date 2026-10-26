import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from acme.models import (
    Critique, Decision, Finding, FindingCode, FindingSource, Invoice, InvoiceState, LineItem,
    Outcome, Severity,
)


def _invoice(**overrides) -> Invoice:
    data = dict(
        invoice_number="INV-1001",
        vendor_name="Widgets Inc.",
        invoice_date="2026-01-15",
        due_date="2026-02-01",
        line_items=[
            {"sku": "WidgetA", "raw_name": "WidgetA", "quantity": 10, "unit_price": "250.00", "amount": "2500.00"},
            {"sku": "WidgetB", "raw_name": "WidgetB", "quantity": 5, "unit_price": "500.00", "amount": "2500.00"},
        ],
        subtotal="5000.00",
        total="5000.00",
        payment_terms="Net 15",
    )
    data.update(overrides)
    return Invoice(**data)


def test_codes_serialize_verbatim_and_severities():
    f = Finding(code=FindingCode.STOCK_EXCEEDED, severity=Severity.CRITICAL, message="too many")
    assert json.loads(f.model_dump_json())["code"] == "STOCK_EXCEEDED"
    assert all(code.value == code.name for code in FindingCode)
    assert FindingCode.CURRENCY_UNSUPPORTED.severity is Severity.WARNING
    assert FindingCode.DUPLICATE.severity is Severity.CRITICAL
    assert FindingCode.NEAR_THRESHOLD.severity is Severity.INFO
    assert FindingCode.PROMPT_INJECTION_SUSPECTED.severity is Severity.CRITICAL
    assert FindingCode.PAYEE_CUMULATIVE_THRESHOLD.severity is Severity.WARNING
    critical = {c.value for c in FindingCode if c.severity is Severity.CRITICAL}
    assert critical == {"EXTRACTION_FAILED", "UNKNOWN_ITEM", "ZERO_STOCK", "STOCK_EXCEEDED",
                        "INVALID_QUANTITY", "MATH_MISMATCH", "MISSING_VENDOR", "DUPLICATE",
                        "FRAUD_SUSPECTED", "PROMPT_INJECTION_SUSPECTED"}
    warning = {c.value for c in FindingCode if c.severity is Severity.WARNING}
    assert warning == {"UNKNOWN_VENDOR", "MISSING_DUE_DATE", "INVALID_DUE_DATE",
                       "DUE_BEFORE_INVOICE_DATE", "PRICE_VARIANCE", "SUSPICIOUS_ADDRESS",
                       "REVISION_CREDIT_DUE", "INVOICE_NUMBER_REUSED", "CURRENCY_UNSUPPORTED",
                       "PAYEE_CUMULATIVE_THRESHOLD"}
    info = {c.value for c in FindingCode if c.severity is Severity.INFO}
    assert info == {"REVISION", "SUPERSEDED_BY_REVISION", "NEAR_THRESHOLD", "CURRENCY_CONVERTED"}


def test_valid_invoice_has_exact_decimals():
    inv = _invoice()
    assert inv.total == Decimal("5000.00") and isinstance(inv.total, Decimal)
    assert inv.line_items[0].unit_price == Decimal("250.00")
    assert inv.due_date == date(2026, 2, 1)
    assert inv.revision == 0 and inv.currency == "USD"
    assert json.loads(inv.model_dump_json())["total"] == "5000.00"


def test_revision_label_parsed():
    assert _invoice(revision="R1").revision == 1


def test_bad_total_names_field():
    with pytest.raises(ValidationError) as err:
        _invoice(total="five thousand")
    assert "total" in str(err.value)


def test_missing_optional_fields_allowed():
    inv = _invoice(vendor_name=None, due_date=None, due_date_raw="yesterday", subtotal=None)
    assert inv.vendor_name is None and inv.due_date is None
    assert inv.due_date_raw == "yesterday"


def test_converted_invoice_keeps_source_amounts():
    inv = _invoice(currency="USD", original_currency="EUR", original_total="4125.00", total="4455.00")
    assert (inv.currency, inv.original_currency, inv.original_total) == ("USD", "EUR", Decimal("4125.00"))


def test_bad_severity_rejected():
    with pytest.raises(ValidationError):
        Finding(code="DUPLICATE", severity="HIGH", message="x")


def test_decision_and_critique():
    d = Decision(outcome="NEEDS_REVIEW", rationale="over threshold", rules_applied=["VP_THRESHOLD"])
    assert json.loads(d.model_dump_json())["outcome"] == "NEEDS_REVIEW"
    with pytest.raises(ValidationError):
        Decision(outcome="MAYBE", rationale="x")
    c = Critique(passes=False, issues=["missed stock check"], suggested_outcome=Outcome.REJECT)
    assert c.suggested_outcome is Outcome.REJECT


def test_invoice_state_round_trip():
    state = InvoiceState(
        run_id="r-123",
        file_path="data/invoices/invoice_1001.txt",
        raw_text="INVOICE\nVendor: Widgets Inc.",
        invoice=_invoice(),
        findings=[
            Finding(code="NEAR_THRESHOLD", severity="INFO", message="close to 10k", evidence={"total": "9800.00"}),
            Finding(code="PRICE_VARIANCE", severity="WARNING", message="odd price",
                    evidence={"sku": "WidgetA", "pct": 12.5}, source=FindingSource.LLM),
        ],
        decision=Decision(outcome="APPROVE", rationale="clean", confidence=0.9),
        trace=[{"agent": "ingestion", "event": "extracted"}],
        retries=1,
    )
    loaded = InvoiceState.model_validate_json(state.model_dump_json())
    assert loaded == state
