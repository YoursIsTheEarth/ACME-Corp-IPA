"""`apply_policy`: the approval policy table as a pure function (F14).

No database or LLM calls; the same inputs always give the same result, rules in the same order.
"""

from dataclasses import dataclass

from acme.models import Finding, FindingCode, Invoice, Outcome, RevisionContext, Severity
from acme.settings import get_settings

STRICTNESS = {Outcome.APPROVE: 0, Outcome.NEEDS_REVIEW: 1, Outcome.REJECT: 2}

VP_SCRUTINY = "VP_SCRUTINY_OVER_THRESHOLD"
AUTO_APPROVE = "AUTO_APPROVE_AT_OR_UNDER_THRESHOLD"
REVISION_PAID_LOWER = "REVISION_OF_PAID_INVOICE_LOWER_TOTAL"
NO_INVOICE = "NO_CANONICAL_INVOICE"


@dataclass(frozen=True)
class PolicyResult:
    floor: Outcome
    rules: tuple[str, ...]
    fraud: bool
    vp_scrutiny: bool


def stricter(*outcomes: Outcome | None) -> Outcome:
    """The strictest outcome given (REJECT > NEEDS_REVIEW > APPROVE); None values are ignored."""
    return max((o for o in outcomes if o is not None), key=STRICTNESS.__getitem__)


def _codes(findings: list[Finding], severity: Severity) -> list[FindingCode]:
    present = {f.code for f in findings if f.severity == severity}
    return [code for code in FindingCode if code in present]  # enum order, so the output is stable


def apply_policy(
    invoice: Invoice | None,
    findings: list[Finding],
    revision_ctx: RevisionContext | None = None,
) -> PolicyResult:
    critical = _codes(findings, Severity.CRITICAL)
    fraud = FindingCode.FRAUD_SUSPECTED in critical
    if critical:
        return PolicyResult(Outcome.REJECT, tuple(f"CRITICAL_{code}" for code in critical), fraud, False)

    rules = [f"WARNING_{code}" for code in _codes(findings, Severity.WARNING)]
    if (invoice is not None and revision_ctx is not None and revision_ctx.paid
            and invoice.total < revision_ctx.paid_amount):
        rules.append(REVISION_PAID_LOWER)
    if invoice is None:
        rules.append(NO_INVOICE)
    if rules:
        return PolicyResult(Outcome.NEEDS_REVIEW, tuple(rules), False, False)

    if invoice.total > get_settings().vp_review_threshold_usd:
        return PolicyResult(Outcome.APPROVE, (VP_SCRUTINY,), False, True)
    return PolicyResult(Outcome.APPROVE, (AUTO_APPROVE,), False, False)
