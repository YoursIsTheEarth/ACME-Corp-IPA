import sqlite3
from decimal import Decimal

import pytest

import acme.db
import acme.llm
from acme.approval import apply_policy, stricter
from acme.approval.policy import AUTO_APPROVE, NO_INVOICE, REVISION_PAID_LOWER, VP_SCRUTINY
from acme.models import Finding, FindingCode as C, FindingSource, Outcome, RevisionContext, Severity

R, N, A = Outcome.REJECT, Outcome.NEEDS_REVIEW, Outcome.APPROVE


def f(code: C) -> Finding:
    return Finding(code=code, severity=code.severity, message=code.value)


def clean(golden, total):
    return golden["invoice_1001.txt"].model_copy(update={"total": Decimal(total)})


def summary(result):
    return result.floor, list(result.rules), result.fraud, result.vp_scrutiny


def test_critical_stock_exceeded_rejects(golden):
    assert summary(apply_policy(golden["invoice_1002.txt"], [f(C.STOCK_EXCEEDED)])) == (
        R, ["CRITICAL_STOCK_EXCEEDED"], False, False)


def test_duplicate_rejects(golden):
    assert apply_policy(golden["invoice_1011.txt"], [f(C.DUPLICATE)]).floor == R


def test_one_rule_per_critical_code_and_warnings_ignored(golden):
    findings = [f(C.MATH_MISMATCH), f(C.MISSING_VENDOR), f(C.MATH_MISMATCH), f(C.MISSING_DUE_DATE),
                f(C.INVALID_QUANTITY)]
    assert list(apply_policy(golden["invoice_1009.json"], findings).rules) == [
        "CRITICAL_INVALID_QUANTITY", "CRITICAL_MATH_MISMATCH", "CRITICAL_MISSING_VENDOR"]


def test_fraud_rejects_with_flag(golden):
    findings = [f(C.ZERO_STOCK), f(C.INVALID_DUE_DATE), f(C.UNKNOWN_VENDOR), f(C.FRAUD_SUSPECTED)]
    assert summary(apply_policy(golden["invoice_1003.txt"], findings)) == (
        R, ["CRITICAL_ZERO_STOCK", "CRITICAL_FRAUD_SUSPECTED"], True, False)


def test_extraction_failed_rejects_without_invoice():
    assert apply_policy(None, [f(C.EXTRACTION_FAILED)]).floor == R


def test_warning_needs_review(golden):
    assert summary(apply_policy(golden["invoice_1010.txt"], [f(C.PRICE_VARIANCE)])) == (
        N, ["WARNING_PRICE_VARIANCE"], False, False)


def test_llm_warning_needs_review(golden):
    llm = Finding(code=C.SUSPICIOUS_ADDRESS, severity=Severity.WARNING, message="x", source=FindingSource.LLM)
    assert apply_policy(golden["invoice_1001.txt"], [llm]).floor == N


def test_revision_credit_due_needs_review(golden):
    invoice = golden["invoice_1004_revised.json"].model_copy(update={"total": Decimal("1500.00")})
    paid = RevisionContext(original_run_id="r-1", paid=True, paid_amount=Decimal("1890.00"))
    result = apply_policy(invoice, [f(C.REVISION), f(C.REVISION_CREDIT_DUE)], paid)
    assert summary(result) == (N, ["WARNING_REVISION_CREDIT_DUE", REVISION_PAID_LOWER], False, False)


def test_paid_lower_revision_from_context_alone_needs_review(golden):
    invoice = golden["invoice_1004_revised.json"].model_copy(update={"total": Decimal("1500.00")})
    paid = RevisionContext(paid=True, paid_amount=Decimal("1890.00"))
    assert apply_policy(invoice, [f(C.REVISION)], paid).floor == N


def test_revision_of_unpaid_original_judged_as_new_invoice(golden):
    unpaid = RevisionContext(original_run_id="r-1", paid=False, original_total=Decimal("1890.00"))
    assert summary(apply_policy(golden["invoice_1004_revised.json"], [f(C.REVISION)], unpaid)) == (
        A, [AUTO_APPROVE], False, False)


def test_revision_of_paid_original_higher_total_approves(golden):
    paid = RevisionContext(paid=True, paid_amount=Decimal("1890.00"))
    assert apply_policy(golden["invoice_1004_revised.json"], [f(C.REVISION)], paid).floor == A


@pytest.mark.parametrize("name,code", [("invoice_1012.pdf", C.NEAR_THRESHOLD),
                                       ("invoice_1014.xml", C.CURRENCY_CONVERTED)])
def test_info_only_auto_approves(golden, name, code):
    assert summary(apply_policy(golden[name], [f(code)])) == (A, [AUTO_APPROVE], False, False)


@pytest.mark.parametrize("total,vp", [("9999.99", False), ("10000.00", False), ("10000.01", True),
                                      ("12000.00", True)])
def test_threshold_routing(golden, total, vp):
    assert summary(apply_policy(clean(golden, total), [])) == (A, [VP_SCRUTINY if vp else AUTO_APPROVE], False, vp)


def test_no_invoice_without_findings_needs_review():
    assert summary(apply_policy(None, [])) == (N, [NO_INVOICE], False, False)


def test_stricter():
    assert stricter(A, None, N) == N and stricter(R, A) == R and stricter(A) == A


# --- 4.2 ---------------------------------------------------------------------------------

def test_pure_and_deterministic(golden, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("apply_policy must not touch the database or an LLM")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(acme.db, "connect", forbidden)
    monkeypatch.setattr(acme.llm, "get_chat_model", forbidden)
    findings = [f(C.MISSING_DUE_DATE), f(C.PRICE_VARIANCE), f(C.NEAR_THRESHOLD)]
    first = apply_policy(golden["invoice_1010.txt"], findings)
    second = apply_policy(golden["invoice_1010.txt"], list(findings))
    assert first == second and first.rules == ("WARNING_MISSING_DUE_DATE", "WARNING_PRICE_VARIANCE")
    assert apply_policy(golden["invoice_1010.txt"], findings[::-1]) == first
