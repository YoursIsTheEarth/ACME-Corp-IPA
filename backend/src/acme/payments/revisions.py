"""`resolve_revision`: the "Revisions and the queue" table as a pure function (F39).

    action = resolve_revision(OriginalPayment("paid", Decimal("1890.00")), Decimal("2390.00"))
    action.kind is RevisionKind.DELTA and action.amount == Decimal("500.00")
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal

CENTS = Decimal("0.01")


def money(value: Decimal | str | int) -> Decimal:
    """Quantize to cents; every stored or compared amount goes through this."""
    return Decimal(value).quantize(CENTS)


class RevisionKind(StrEnum):
    REPLACE = "REPLACE"
    DELTA = "DELTA"
    CREDIT_HOLD = "CREDIT_HOLD"
    REVISED_NO_PAYMENT = "REVISED_NO_PAYMENT"
    WAIT_FOR_PAYMENT = "WAIT_FOR_PAYMENT"


@dataclass(frozen=True)
class OriginalPayment:
    """Payment state of the invoice a revision revises, as read under the batch lock."""

    status: Literal["unpaid", "paying", "paid"]
    paid_amount: Decimal = Decimal("0")  # sum already paid across earlier revisions (delta rows included)


@dataclass(frozen=True)
class RevisionAction:
    kind: RevisionKind
    amount: Decimal | None = None  # DELTA: amount to queue; CREDIT_HOLD: amount overpaid; REPLACE: full total


def resolve_revision(original: OriginalPayment, revision_total: Decimal) -> RevisionAction:
    total = money(revision_total)
    if original.status == "paying":
        return RevisionAction(RevisionKind.WAIT_FOR_PAYMENT)
    if original.status == "unpaid":
        return RevisionAction(RevisionKind.REPLACE, total)
    paid = money(original.paid_amount)
    if total > paid:
        return RevisionAction(RevisionKind.DELTA, total - paid)
    if total < paid:
        return RevisionAction(RevisionKind.CREDIT_HOLD, paid - total)
    return RevisionAction(RevisionKind.REVISED_NO_PAYMENT)
