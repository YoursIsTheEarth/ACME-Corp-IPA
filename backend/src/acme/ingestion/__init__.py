"""Invoice ingestion: any supported file -> raw text, source format, and an `ExtractedInvoice`.

    result = ingest("data/invoices/invoice_1002.txt", run_id="r-1")
    result.extracted        # ExtractedInvoice, or None when it failed closed
    result.findings         # [] or [CRITICAL EXTRACTION_FAILED]
"""

from acme.ingestion.schema import ExtractedInvoice, ExtractedLineItem, IngestionResult
from acme.ingestion.service import ingest

__all__ = ["ExtractedInvoice", "ExtractedLineItem", "IngestionResult", "ingest"]
