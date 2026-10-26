"""Badge and tile counts, plus the active LLM provider and model (F21, F31)."""

from typing import Any

from fastapi import APIRouter

from acme.api import queries
from acme.api.deps import db

router = APIRouter(tags=["stats"])


@router.get("/api/stats")
def get_stats() -> dict[str, Any]:
    with db() as conn:
        return queries.stats(conn)
