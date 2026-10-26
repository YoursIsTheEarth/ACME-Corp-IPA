"""The case README's mock payment function, plus a test-only failure hook.

    mock_payment(vendor, amount)     # verbatim from the README
    fail_next(2, "bank timeout")     # tests: the next 2 calls raise PaymentError
"""

_forced_failures: list[str] = []


class PaymentError(RuntimeError):
    """Raised by `mock_payment` when a test forced a failure."""


def fail_next(times: int = 1, error: str = "forced failure") -> None:
    """Test hook: make the next `times` calls to `mock_payment` raise `PaymentError(error)`."""
    _forced_failures.extend([error] * times)


def reset() -> None:
    """Test hook: clear any forced failures."""
    _forced_failures.clear()


def mock_payment(vendor, amount):
    if _forced_failures:
        raise PaymentError(_forced_failures.pop(0))
    print(f"Paid {amount} to {vendor}")
    return {"status": "success"}
