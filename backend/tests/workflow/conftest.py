import pytest

from acme.payments import mock_bank
from workflow_helpers import restore_offline


@pytest.fixture(autouse=True)
def _offline_defaults():
    restore_offline()
    yield
    restore_offline()


@pytest.fixture
def wdb(seeded_db):
    """Seeded `acme.db` in tmp_path, the default path the workflow connects to."""
    return seeded_db


@pytest.fixture(autouse=True)
def bank(monkeypatch):
    """Records every `mock_payment` call (the real function still runs)."""
    calls = []
    real = mock_bank.mock_payment

    def recording(vendor, amount):
        calls.append((vendor, amount))
        return real(vendor, amount)

    mock_bank.reset()
    monkeypatch.setattr(mock_bank, "mock_payment", recording)
    yield calls
    mock_bank.reset()
