import pytest

from acme.payments import mock_bank


def test_mock_payment_is_the_readme_function(capsys):
    assert mock_bank.mock_payment("Widgets Inc.", 5000) == {"status": "success"}
    assert capsys.readouterr().out == "Paid 5000 to Widgets Inc.\n"


def test_failure_hook_forces_failures_then_recovers():
    mock_bank.fail_next(2, "bank timeout")
    for _ in range(2):
        with pytest.raises(mock_bank.PaymentError, match="bank timeout"):
            mock_bank.mock_payment("Widgets Inc.", 1)
    assert mock_bank.mock_payment("Widgets Inc.", 1) == {"status": "success"}
