from decimal import Decimal

import pytest

from acme.payments import mock_bank
from golden_invoices import GOLDEN


@pytest.fixture(autouse=True)
def bank(monkeypatch):
    """Records every `mock_payment` call (the real function still runs, failure hook included)."""
    calls: list[tuple[str, Decimal]] = []
    real = mock_bank.mock_payment

    def recording(vendor, amount):
        calls.append((vendor, amount))
        return real(vendor, amount)

    mock_bank.reset()
    monkeypatch.setattr(mock_bank, "mock_payment", recording)
    yield calls
    mock_bank.reset()


@pytest.fixture
def golden():
    return {name: invoice.model_copy(deep=True) for name, invoice in GOLDEN.items()}


@pytest.fixture
def pdb(seeded_db):
    """Seeded `acme.db` in tmp_path (the default DB path the payment functions connect to)."""
    return seeded_db
