from acme.models import FindingCode, Severity
from acme.validation.codes import SEVERITY, finding

EXPECTED = {
    Severity.CRITICAL: ["UNKNOWN_ITEM", "ZERO_STOCK", "STOCK_EXCEEDED", "INVALID_QUANTITY", "MATH_MISMATCH",
                        "MISSING_VENDOR", "DUPLICATE", "FRAUD_SUSPECTED", "PROMPT_INJECTION_SUSPECTED"],
    Severity.WARNING: ["UNKNOWN_VENDOR", "MISSING_DUE_DATE", "INVALID_DUE_DATE", "DUE_BEFORE_INVOICE_DATE",
                       "PRICE_VARIANCE", "SUSPICIOUS_ADDRESS", "REVISION_CREDIT_DUE", "INVOICE_NUMBER_REUSED",
                       "PAYEE_CUMULATIVE_THRESHOLD", "MATH_ROUNDING"],
    Severity.INFO: ["REVISION", "NEAR_THRESHOLD", "CURRENCY_CONVERTED"],
}


def test_every_test_plan_code_has_its_d3_severity():
    for severity, codes in EXPECTED.items():
        for code in codes:
            assert SEVERITY[FindingCode(code)] == severity, code
    assert len(SEVERITY) == sum(len(c) for c in EXPECTED.values())


def test_matches_the_shared_model_severities():
    for code, severity in SEVERITY.items():
        assert code.severity == severity


def test_finding_helper_uses_the_map():
    f = finding(FindingCode.MATH_MISMATCH, "off", expected="1.00")
    assert f.severity == Severity.CRITICAL and f.source == "rule" and f.evidence == {"expected": "1.00"}
