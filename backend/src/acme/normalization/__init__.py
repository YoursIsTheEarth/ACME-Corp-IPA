"""Normalization: `ExtractedInvoice` -> canonical `Invoice` (SKUs, dates, money, numbers, USD).

    invoice, findings = normalize(result.extracted, run_id="r-1")
"""

from acme.normalization.service import normalize

__all__ = ["normalize"]
