"""PDF text-layer extraction (design D12). No OCR: an image-only PDF fails closed."""

from pathlib import Path

import pdfplumber

MIN_TEXT_CHARS = 20
PAGE_SEPARATOR = "\n\f\n"


class NoTextLayerError(ValueError):
    pass


def pdf_to_text(path: str | Path) -> str:
    """Return the text of every page; raise NoTextLayerError under 20 non-whitespace chars."""
    with pdfplumber.open(path) as pdf:
        text = PAGE_SEPARATOR.join(page.extract_text() or "" for page in pdf.pages)
    if sum(not ch.isspace() for ch in text) < MIN_TEXT_CHARS:
        raise NoTextLayerError("no text layer (image-only or blank PDF); OCR is not attempted")
    return text
