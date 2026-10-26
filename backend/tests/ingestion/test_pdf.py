from pathlib import Path

import pypdfium2 as pdfium
import pytest

from acme.ingestion.pdf import NoTextLayerError, pdf_to_text

INVOICES = Path(__file__).resolve().parents[3] / "data" / "invoices"


def test_text_layer_1011():
    assert "INV-1011" in pdf_to_text(INVOICES / "invoice_1011.pdf")


def test_text_layer_keeps_ocr_noise_1012():
    text = pdf_to_text(INVOICES / "invoice_1012.pdf")
    assert "2O26" in text and "$3,500.O0" in text


def test_blank_pdf_has_no_text_layer(tmp_path):
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(612, 792)
    pdf.save(tmp_path / "blank.pdf")
    with pytest.raises(NoTextLayerError):
        pdf_to_text(tmp_path / "blank.pdf")
