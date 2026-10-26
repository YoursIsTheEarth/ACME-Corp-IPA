"""Format detection (F1, design D2): content sniffing wins over the extension."""

from pathlib import Path

FORMATS = ("json", "csv", "xml", "txt", "pdf", "email")
SNIFF_BYTES = 4096
_BY_EXTENSION = {".json": "json", ".csv": "csv", ".xml": "xml", ".txt": "txt", ".pdf": "pdf", ".eml": "email"}


def sniff(head: bytes, suffix: str) -> str | None:
    """Classify a file from its first bytes and extension; None means unsupported."""
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if text.startswith(b"%PDF"):
        return "pdf"
    if text[:1] in (b"{", b"["):
        return "json"
    if text.startswith(b"<?xml") or text.startswith(b"<invoice"):
        return "xml"
    lines = head.decode("utf-8", errors="replace").splitlines()[:10]
    starts = {line.split(":", 1)[0].strip().lower() for line in lines if ":" in line}
    if {"from", "subject"} <= starts:
        return "email"
    return _BY_EXTENSION.get(suffix.lower())


def detect_format(path: str | Path) -> str | None:
    """Return one of FORMATS for the file at `path`, or None for an unsupported type."""
    path = Path(path)
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    return sniff(head, path.suffix)
