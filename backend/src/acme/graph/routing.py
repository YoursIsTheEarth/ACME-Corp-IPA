"""Conditional edges (handoff rules 1 and 5)."""

from langgraph.graph import END

from acme.graph.state import WorkflowState


def after_ingest(state: WorkflowState) -> str:
    """Rule 1: hand off only an accepted extraction; a failed one goes straight to disposition."""
    return "normalize" if state.extracted is not None else "disposition"


def after_normalize(state: WorkflowState) -> str:
    return "validate" if state.invoice is not None else "disposition"


def after_disposition(state: WorkflowState) -> str:
    """A hold pauses the run in `review_hold`; every other outcome ends it."""
    return "review_hold" if (state.payment_result or {}).get("held") else END
