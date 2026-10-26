"""Lenient extraction schema (design D4).

`ExtractedInvoice` is the `Invoice` as found in the source: dates and money may stay
raw strings (OCR noise and all), the invoice number is free text, and SKUs are unset.
The normalizer turns it into the strict canonical `Invoice`.
"""

import re
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator

from acme.models import Finding, Invoice, LineItem

Money = Decimal | str


class ExtractedLineItem(LineItem):
    unit_price: Money | None = None
    amount: Money | None = None

    @field_validator("quantity", mode="before")
    @classmethod
    def _strip_thousands_separators(cls, value):
        if isinstance(value, str) and re.fullmatch(r"-?\d{1,3}(,\d{3})+", value.strip()):
            return value.replace(",", "")
        return value


class ExtractedInvoice(Invoice):
    revision: int | str = 0
    invoice_date: date | str | None = None
    due_date: date | str | None = None
    currency: str | None = None  # None = not stated (treated as USD by the normalizer)
    line_items: list[ExtractedLineItem] = []
    subtotal: Money | None = None
    tax: Money | None = None
    shipping: Money | None = None
    total: Money


class IngestionResult(BaseModel):
    """What `ingest()` returns: `extracted` is None exactly when ingestion failed closed."""

    raw_text: str | None = None
    source_format: str | None = None
    extracted: ExtractedInvoice | None = None
    findings: list[Finding] = []
    attempts: int = 0

    @property
    def retries(self) -> int:
        return max(self.attempts - 1, 0)
