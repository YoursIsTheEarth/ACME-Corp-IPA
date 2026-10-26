"""The graph's shared per-run state: `InvoiceState` plus the few fields only the workflow needs."""

from acme.models import InvoiceState


class WorkflowState(InvoiceState):
    source_format: str | None = None  # written by ingest
    hold_kind: str | None = None  # warning | credit, set when a reviewer decision resumes the run
