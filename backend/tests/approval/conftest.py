import pytest

from acme.approval.offline import register_offline as register_approval_offline
from acme.validation import ValidationContext
from acme.validation.agent import register_offline as register_validation_offline
from golden_invoices import GOLDEN


@pytest.fixture(autouse=True)
def _offline_behaviors():
    """Other suites replace the global offline handlers/tool plan; restore this change's."""
    register_validation_offline()
    register_approval_offline()


@pytest.fixture
def ctx(seeded_db):
    return ValidationContext.load(seeded_db)


@pytest.fixture
def golden():
    """Canonical invoices for the golden files, hand-coded (no extraction, no LLM)."""
    return {name: invoice.model_copy(deep=True) for name, invoice in GOLDEN.items()}
