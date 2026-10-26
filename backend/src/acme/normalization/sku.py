"""SKU resolution (F5, design D7): exact key -> alias key -> `fuzz.ratio` >= 90; else unknown."""

import re
import sqlite3
from dataclasses import dataclass
from typing import NamedTuple

from rapidfuzz import fuzz, process

from acme.db import connect

FUZZY_CUTOFF = 90


def key(name: str) -> str:
    """Casefold and drop whitespace/punctuation: "Widget-A " -> "widgeta". Non-Latin letters stay."""
    return re.sub(r"[\W_]+", "", name.casefold())


@dataclass(frozen=True)
class SkuCatalog:
    skus: frozenset[str]
    aliases: dict[str, str]  # alias -> sku

    @classmethod
    def load(cls, conn: sqlite3.Connection | None = None) -> "SkuCatalog":
        own = conn is None
        conn = conn or connect()
        try:
            skus = frozenset(row[0] for row in conn.execute("SELECT item FROM inventory"))
            aliases = dict(conn.execute("SELECT alias, sku FROM item_aliases").fetchall())
        finally:
            if own:
                conn.close()
        return cls(skus, aliases)


class SkuMatch(NamedTuple):
    sku: str | None
    method: str  # exact | alias | fuzzy:<score> | llm | none


def match_sku(raw_name: str, catalog: SkuCatalog | None = None) -> SkuMatch:
    """Resolve a raw item name to an inventory SKU without the LLM."""
    catalog = catalog or SkuCatalog.load()
    name = key(raw_name)
    by_sku = {key(sku): sku for sku in catalog.skus}
    if name in by_sku:
        return SkuMatch(by_sku[name], "exact")
    by_alias = {key(alias): sku for alias, sku in catalog.aliases.items() if sku in catalog.skus}
    if name in by_alias:
        return SkuMatch(by_alias[name], "alias")
    candidates = {**by_alias, **by_sku}
    best = process.extractOne(name, list(candidates), scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF)
    if best is not None:
        return SkuMatch(candidates[best[0]], f"fuzzy:{best[1]:.1f}")
    return SkuMatch(None, "none")
