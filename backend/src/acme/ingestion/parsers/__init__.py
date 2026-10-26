"""Deterministic parsers for the structured formats; none of them calls an LLM."""

from acme.ingestion.parsers.csv_ import parse_csv
from acme.ingestion.parsers.json_ import parse_json
from acme.ingestion.parsers.xml_ import parse_xml

__all__ = ["parse_csv", "parse_json", "parse_xml"]
