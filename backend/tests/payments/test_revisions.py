"""The five "Revisions and the queue" cases, from INV-1004 ($1,890.00) and edited totals."""

from decimal import Decimal

import pytest

from acme.payments import OriginalPayment, RevisionKind as K, resolve_revision

PAID_1004 = OriginalPayment("paid", Decimal("1890.00"))


@pytest.mark.parametrize("original, total, kind, amount", [
    (OriginalPayment("unpaid"), "5940.00", K.REPLACE, Decimal("5940.00")),
    (PAID_1004, "2390.00", K.DELTA, Decimal("500.00")),
    (PAID_1004, "1500.00", K.CREDIT_HOLD, Decimal("390.00")),
    (PAID_1004, "1890.00", K.REVISED_NO_PAYMENT, None),
    (PAID_1004, "1890", K.REVISED_NO_PAYMENT, None),  # compared as money, not as strings
    (OriginalPayment("paying"), "5940.00", K.WAIT_FOR_PAYMENT, None),
])
def test_resolve_revision(original, total, kind, amount):
    action = resolve_revision(original, Decimal(total))
    assert (action.kind, action.amount) == (kind, amount)


def test_amounts_are_quantized_to_cents():
    action = resolve_revision(OriginalPayment("paid", Decimal("1890.004")), Decimal("2390.0049"))
    assert action.amount == Decimal("500.00") and str(action.amount) == "500.00"
