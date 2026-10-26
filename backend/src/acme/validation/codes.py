"""Finding code -> severity for validation (design D3), and the rule-finding constructor."""

from typing import Any

from acme.models import Finding, FindingCode, FindingSource, Severity

C = FindingCode
SEVERITY: dict[FindingCode, Severity] = {
    **dict.fromkeys(
        (C.UNKNOWN_ITEM, C.ZERO_STOCK, C.STOCK_EXCEEDED, C.INVALID_QUANTITY, C.MATH_MISMATCH,
         C.MISSING_VENDOR, C.DUPLICATE, C.FRAUD_SUSPECTED, C.PROMPT_INJECTION_SUSPECTED),
        Severity.CRITICAL,
    ),
    **dict.fromkeys(
        (C.UNKNOWN_VENDOR, C.MISSING_DUE_DATE, C.INVALID_DUE_DATE, C.DUE_BEFORE_INVOICE_DATE,
         C.PRICE_VARIANCE, C.SUSPICIOUS_ADDRESS, C.REVISION_CREDIT_DUE, C.INVOICE_NUMBER_REUSED,
         C.PAYEE_CUMULATIVE_THRESHOLD),
        Severity.WARNING,
    ),
    **dict.fromkeys((C.REVISION, C.NEAR_THRESHOLD, C.CURRENCY_CONVERTED), Severity.INFO),
}


def for_prompt(f: Finding) -> Finding:
    """`f` as LLM prompts show it: a prompt-injection finding keeps only the pattern names as evidence, so the
    attack text reaches a model only inside the invoice's untrusted-data delimiters."""
    if f.code != C.PROMPT_INJECTION_SUSPECTED:
        return f
    return f.model_copy(update={"evidence": {k: v for k, v in f.evidence.items() if k == "patterns"}})


def finding(code: FindingCode, message: str, **evidence: Any) -> Finding:
    """A rule-sourced finding with the canonical severity for `code`."""
    return Finding(code=code, severity=SEVERITY[code], message=message, evidence=evidence,
                   source=FindingSource.RULE)
