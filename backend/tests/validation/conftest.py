import pytest

from acme.validation import ValidationContext
from golden_invoices import GOLDEN


@pytest.fixture
def ctx(seeded_db):
    return ValidationContext.load(seeded_db)


@pytest.fixture
def golden():
    """Canonical invoices for the golden files, hand-coded (no extraction, no LLM)."""
    return {name: invoice.model_copy(deep=True) for name, invoice in GOLDEN.items()}
