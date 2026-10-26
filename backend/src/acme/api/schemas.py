"""Request bodies. Names are trimmed before the 1-50 character check (F25, F40, F41)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from acme.admin import PaymentTiming

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: Name
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=15)]


class ExecuteRequest(BaseModel):
    ids: list[int] | None = Field(None, min_length=1, description="Payment queue row ids; omit for Pay all")
    released_by: Name


class AdminSettingsRequest(PaymentTiming):
    """All five payment timing settings (validated as in `acme.admin`) and who is saving them."""

    delay_payments: bool
    pay_at_end_of_day: bool
    end_of_day_time: str = Field(description="24-hour HH:MM, e.g. 17:00")
    end_of_day_timezone: str = Field(description="IANA timezone, e.g. America/Chicago")
    pay_when_queue_empty: bool
    updated_by: Name
