"""Deterministic validation checks (F8-F12). Each is pure: `(invoice, ctx) -> list[Finding]`.

Money in evidence is a string ("1000.00") so evidence is JSON-stable.
"""

import re
from collections import defaultdict
from decimal import Decimal

from acme.models import Finding, FindingCode as C, FindingSource, Invoice, RevisionContext
from acme.normalization.cleaners import is_relative_date
from acme.settings import get_settings
from acme.validation.codes import finding
from acme.validation.context import ValidationContext, content_hash

TOLERANCE = Decimal("0.01")  # differences under one cent are rounding; a full cent is a mismatch


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


# --- F8 inventory -----------------------------------------------------------------

def check_items(invoice: Invoice, ctx: ValidationContext) -> list[Finding]:
    """UNKNOWN_ITEM for every line whose item is not in inventory."""
    return [
        finding(C.UNKNOWN_ITEM, f"Item {item.raw_name!r} is not in inventory", line=i, item=item.raw_name)
        for i, item in enumerate(invoice.line_items, 1)
        if item.sku is None or item.sku not in ctx.inventory
    ]


def check_stock(invoice: Invoice, ctx: ValidationContext) -> list[Finding]:
    """ZERO_STOCK / STOCK_EXCEEDED on the quantity billed per SKU, summed across lines."""
    billed: dict[str, int] = defaultdict(int)
    for item in invoice.line_items:
        if item.sku in ctx.inventory and item.quantity > 0:
            billed[item.sku] += item.quantity
    findings = []
    for sku, quantity in billed.items():
        stock = ctx.inventory[sku].stock
        if stock == 0:
            findings.append(finding(C.ZERO_STOCK, f"{sku} is out of stock (billed {quantity})",
                                    sku=sku, billed=quantity, stock=stock))
        elif quantity > stock:
            findings.append(finding(C.STOCK_EXCEEDED, f"{sku}: billed {quantity}, only {stock} in stock",
                                    sku=sku, billed=quantity, stock=stock))
    return findings


# --- F9 data integrity ------------------------------------------------------------

def check_integrity(invoice: Invoice, ctx: ValidationContext) -> list[Finding]:
    """MISSING_VENDOR, INVALID_QUANTITY, and due-date findings (compared with the invoice date)."""
    findings = []
    if not (invoice.vendor_name or "").strip():
        findings.append(finding(C.MISSING_VENDOR, "Vendor name is missing", vendor_name=invoice.vendor_name))
    for i, item in enumerate(invoice.line_items, 1):
        if item.quantity <= 0:
            findings.append(finding(C.INVALID_QUANTITY, f"Line {i} ({item.raw_name}) has quantity {item.quantity}",
                                    line=i, item=item.raw_name, quantity=item.quantity))
    if invoice.due_date is None:
        if invoice.due_date_raw:
            findings.append(finding(C.INVALID_DUE_DATE, f"Due date {invoice.due_date_raw!r} is not a date",
                                    due_date_raw=invoice.due_date_raw))
        else:
            findings.append(finding(C.MISSING_DUE_DATE, "Due date is missing"))
    elif invoice.invoice_date is not None and invoice.due_date < invoice.invoice_date:
        findings.append(finding(C.DUE_BEFORE_INVOICE_DATE,
                                f"Due date {invoice.due_date} is before invoice date {invoice.invoice_date}",
                                due_date=invoice.due_date.isoformat(),
                                invoice_date=invoice.invoice_date.isoformat()))
    return findings


def reconcile_math(invoice: Invoice, ctx: ValidationContext) -> list[Finding]:
    """MATH_MISMATCH for line amounts, line sum vs subtotal, and the total (sub-cent differences tolerated)."""
    findings = []
    line_sum = Decimal("0")
    for i, item in enumerate(invoice.line_items, 1):
        extended = None if item.unit_price is None else item.unit_price * item.quantity
        if extended is not None and item.amount is not None and abs(extended - item.amount) >= TOLERANCE:
            findings.append(finding(C.MATH_MISMATCH, f"Line {i}: {item.quantity} x {item.unit_price} != {item.amount}",
                                    check="line_amount", line=i, expected=_money(extended),
                                    actual=_money(item.amount)))
        amount = item.amount if item.amount is not None else extended
        if amount is None:
            findings.append(finding(C.MATH_MISMATCH, f"Line {i} has neither an amount nor a unit price",
                                    check="line_amount", line=i, expected=None, actual=None))
            continue
        line_sum += amount
    subtotal = invoice.subtotal if invoice.subtotal is not None else line_sum
    if invoice.subtotal is not None and abs(line_sum - invoice.subtotal) >= TOLERANCE:
        findings.append(finding(C.MATH_MISMATCH,
                                f"Line items sum to {_money(line_sum)} but the subtotal is {_money(invoice.subtotal)}",
                                check="subtotal", expected=_money(line_sum), actual=_money(invoice.subtotal)))
    expected_total = subtotal + invoice.tax + invoice.shipping
    if abs(expected_total - invoice.total) >= TOLERANCE:
        findings.append(finding(C.MATH_MISMATCH,
                                f"Subtotal + tax + shipping is {_money(expected_total)} "
                                f"but the total is {_money(invoice.total)}",
                                check="total", expected=_money(expected_total), actual=_money(invoice.total)))
    return findings


def check_vendor(invoice: Invoice, ctx: ValidationContext) -> list[Finding]:
    """UNKNOWN_VENDOR when a named vendor matches no approved vendor name or alias."""
    if not (invoice.vendor_name or "").strip() or ctx.approved_vendor(invoice.vendor_name):
        return []
    return [finding(C.UNKNOWN_VENDOR, f"Vendor {invoice.vendor_name!r} is not on the approved vendor list",
                    vendor_name=invoice.vendor_name)]


# --- F10 duplicates and revisions -----------------------------------------------------

def _paid_amount(ctx: ValidationContext, vendor: str, invoice_number: str, revision: int) -> Decimal | None:
    """Sum paid for the invoice up to and including `revision` (every earlier revision and delta row);
    None if never paid. Matches how payment processing reads the ledger."""
    paid = None
    for payment in ctx.payments:
        parts = payment.idempotency_key.split("|")
        if parts[-1] == "delta":
            parts = parts[:-1]
        if (len(parts) >= 3 and parts[-2] == invoice_number and parts[-1].isdigit()
                and int(parts[-1]) <= revision and ctx.vendor_key(payment.vendor) == vendor):
            paid = (paid or Decimal("0")) + payment.amount_usd
    return paid


def detect_duplicate(invoice: Invoice, ctx: ValidationContext) -> tuple[list[Finding], RevisionContext | None]:
    """DUPLICATE, REVISION (+ REVISION_CREDIT_DUE), or INVOICE_NUMBER_REUSED against `processed_invoices`."""
    vendor = ctx.vendor_key(invoice.vendor_name)
    matches = [p for p in ctx.processed if p.vendor == vendor and p.invoice_number == invoice.invoice_number]
    if not matches:
        return [], None
    same = next((p for p in matches if p.revision == invoice.revision), None)
    if same is not None:
        identical = (same.content_hash == content_hash(invoice) if same.content_hash is not None
                     else same.total is None or same.total == invoice.total)
        evidence = dict(original_run_id=same.run_id, original_outcome=same.outcome, revision=invoice.revision,
                        original_total=None if same.total is None else _money(same.total),
                        total=_money(invoice.total))
        if identical:
            return [finding(C.DUPLICATE, f"{invoice.invoice_number} was already processed (run {same.run_id})",
                            **evidence)], None
        return [finding(C.INVOICE_NUMBER_REUSED,
                        f"{invoice.invoice_number} was already processed with different content and no new revision",
                        **evidence)], None

    earlier = [p for p in matches if p.revision < invoice.revision]
    if not earlier:  # an older revision arriving after a newer one
        latest = max(matches, key=lambda p: p.revision)
        return [finding(C.INVOICE_NUMBER_REUSED,
                        f"{invoice.invoice_number} revision {invoice.revision} arrived after revision {latest.revision}",
                        original_run_id=latest.run_id, original_revision=latest.revision,
                        revision=invoice.revision)], None
    original = max(earlier, key=lambda p: p.revision)
    paid_amount = _paid_amount(ctx, vendor, original.invoice_number, original.revision)
    revision_ctx = RevisionContext(
        original_run_id=original.run_id, original_outcome=original.outcome, original_revision=original.revision,
        original_total=original.total, paid=paid_amount is not None, paid_amount=paid_amount or Decimal("0"),
    )
    findings = [finding(
        C.REVISION, f"Revision {invoice.revision} of {invoice.invoice_number} (original run {original.run_id})",
        original_run_id=original.run_id, original_outcome=original.outcome, original_revision=original.revision,
        original_total=None if original.total is None else _money(original.total), paid=revision_ctx.paid,
        paid_amount=_money(revision_ctx.paid_amount), total=_money(invoice.total),
    )]
    if revision_ctx.paid and invoice.total < revision_ctx.paid_amount:
        overpaid = revision_ctx.paid_amount - invoice.total
        findings.append(finding(C.REVISION_CREDIT_DUE,
                                f"Original already paid {_money(revision_ctx.paid_amount)}; revision totals "
                                f"{_money(invoice.total)}, so {_money(overpaid)} is due back",
                                original_run_id=original.run_id, paid_amount=_money(revision_ctx.paid_amount),
                                total=_money(invoice.total), overpaid=_money(overpaid)))
    return findings, revision_ctx


def check_duplicate(invoice: Invoice, ctx: ValidationContext) -> list[Finding]:
    return detect_duplicate(invoice, ctx)[0]


# --- F11 fraud signals (P1) -----------------------------------------------------------

_URGENCY = re.compile(r"\b(urgent\w*|immediately|asap|act now|penalt\w*|final notice)\b", re.IGNORECASE)
_WIRE = re.compile(r"\bwire\b", re.IGNORECASE)
_IMMEDIATE_TERMS = re.compile(r"\b(immediate\w*|due on receipt|upon receipt)\b", re.IGNORECASE)


def implausible_address(ctx: ValidationContext) -> bool:
    """The LLM judged the vendor address implausible (no assessment: no signal)."""
    return ctx.address_assessment is not None and not ctx.address_assessment.plausible


def near_threshold(invoice: Invoice) -> bool:
    settings = get_settings()
    return settings.near_threshold_floor_usd <= invoice.total < settings.vp_review_threshold_usd


def fraud_score(invoice: Invoice, ctx: ValidationContext) -> tuple[float, list[str]]:
    """Weighted sum of the signals present (design D5) and their names."""
    text = " ".join(filter(None, [invoice.notes, invoice.payment_terms]))
    due_relative = (invoice.due_date is None and bool(invoice.due_date_raw) and is_relative_date(invoice.due_date_raw)) \
        or (invoice.due_date is not None and invoice.invoice_date is not None
            and invoice.due_date < invoice.invoice_date)
    present = {
        "urgency_language": bool(_URGENCY.search(text)),
        "wire_transfer": bool(_WIRE.search(text)),
        "immediate_terms": bool(_IMMEDIATE_TERMS.search(invoice.payment_terms or "")),
        "relative_due_date": due_relative,
        "unknown_vendor": bool(check_vendor(invoice, ctx)),
        "suspicious_address": implausible_address(ctx),
        "near_threshold": near_threshold(invoice),
    }
    weights = get_settings().fraud_signal_weights
    signals = [name for name, hit in present.items() if hit]
    return round(sum(weights.get(name, 0.0) for name in signals), 4), signals


def fraud_signals(invoice: Invoice, ctx: ValidationContext) -> list[Finding]:
    """SUSPICIOUS_ADDRESS (from the LLM's address assessment, source `llm`), NEAR_THRESHOLD, and
    FRAUD_SUSPECTED when the score meets the threshold."""
    findings = []
    if implausible_address(ctx):
        verdict = ctx.address_assessment
        findings.append(Finding(code=C.SUSPICIOUS_ADDRESS, severity=C.SUSPICIOUS_ADDRESS.severity,
                                message=f"Vendor address is implausible for a business supplier: {verdict.reason}",
                                evidence={"address": invoice.vendor_address, "reason": verdict.reason,
                                          "confidence": verdict.confidence},
                                source=FindingSource.LLM))
    if near_threshold(invoice):
        findings.append(finding(C.NEAR_THRESHOLD, f"Total {_money(invoice.total)} is just under the VP threshold",
                                total=_money(invoice.total),
                                threshold=_money(get_settings().vp_review_threshold_usd)))
    score, signals = fraud_score(invoice, ctx)
    threshold = get_settings().fraud_threshold
    if score >= threshold:
        findings.append(finding(C.FRAUD_SUSPECTED, f"Fraud score {score:.2f} >= {threshold:.2f}: {', '.join(signals)}",
                                score=score, threshold=threshold, signals=signals))
    return findings


# --- F12 price variance (P1) ------------------------------------------------------------

def check_prices(invoice: Invoice, ctx: ValidationContext) -> list[Finding]:
    """PRICE_VARIANCE when a USD unit price is more than the configured % from the reference price.

    The invoice is already in USD (normalization converts at the configured FX rate).
    """
    limit = get_settings().price_variance_pct
    findings = []
    for i, item in enumerate(invoice.line_items, 1):
        stock_item = ctx.inventory.get(item.sku) if item.sku else None
        if stock_item is None or stock_item.unit_price is None or item.unit_price is None:
            continue
        pct = (item.unit_price - stock_item.unit_price) / stock_item.unit_price * 100
        if abs(pct) > limit:
            findings.append(finding(C.PRICE_VARIANCE,
                                    f"Line {i} {item.sku}: billed {_money(item.unit_price)} vs reference "
                                    f"{_money(stock_item.unit_price)} ({pct:+.1f}%)",
                                    line=i, sku=item.sku, billed=_money(item.unit_price),
                                    reference=_money(stock_item.unit_price), pct=f"{pct:+.1f}"))
    return findings


# Every check, in the order findings are reported. Tool names are the keys.
CHECKS = {
    "lookup_item": check_items,
    "check_stock": check_stock,
    "reconcile_math": reconcile_math,
    "check_integrity": check_integrity,
    "check_duplicate": check_duplicate,
    "check_vendor": check_vendor,
    "fraud_signals": fraud_signals,
    "check_prices": check_prices,
}


def run_checks(invoice: Invoice, ctx: ValidationContext) -> list[Finding]:
    """Every deterministic check, in `CHECKS` order (no LLM)."""
    return [f for check in CHECKS.values() for f in check(invoice, ctx)]
