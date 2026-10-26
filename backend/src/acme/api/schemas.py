"""Request bodies. Names are trimmed before the 1-50 character check (F25, F40)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: Name
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=15)]


class ExecuteRequest(BaseModel):
    ids: list[int] | None = Field(None, min_length=1, description="Payment queue row ids; omit for Pay all")
    released_by: Name
