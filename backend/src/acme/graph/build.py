"""`build_graph(checkpointer)`: the compiled invoice `StateGraph`, plus the SQLite checkpointer.

    with compiled_graph() as graph:          # checkpointer on acme.db, thread_id = run_id
        graph.invoke(WorkflowState(run_id=..., file_path=...), {"configurable": {"thread_id": run_id}})

ingest -> normalize -> validate -> approve -> disposition [-> review_hold -> disposition] -> END.
A failed ingest or normalize routes straight to disposition.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from acme.graph import nodes, routing
from acme.graph.state import WorkflowState
from acme.settings import get_settings

# Types the checkpointer may deserialize (everything stored in WorkflowState).
CHECKPOINT_TYPES = [
    ("acme.models", name) for name in (
        "Invoice", "LineItem", "Finding", "FindingCode", "Severity", "FindingSource", "Decision", "Outcome",
        "Critique", "RevisionContext", "InvoiceState",
    )
] + [("acme.graph.state", "WorkflowState")]


def build_graph(checkpointer=None) -> CompiledStateGraph:
    graph = StateGraph(WorkflowState)
    graph.add_node("ingest", nodes.ingest_node)
    graph.add_node("normalize", nodes.normalize_node)
    graph.add_node("validate", nodes.validate_node)
    graph.add_node("approve", nodes.approve_node)
    graph.add_node("disposition", nodes.disposition_node)
    graph.add_node("review_hold", nodes.review_hold_node)
    graph.add_edge(START, "ingest")
    graph.add_conditional_edges("ingest", routing.after_ingest, ["normalize", "disposition"])
    graph.add_conditional_edges("normalize", routing.after_normalize, ["validate", "disposition"])
    graph.add_edge("validate", "approve")
    graph.add_edge("approve", "disposition")
    graph.add_conditional_edges("disposition", routing.after_disposition, ["review_hold", END])
    graph.add_edge("review_hold", "disposition")
    return graph.compile(checkpointer=checkpointer)


def open_checkpointer(path: str | Path | None = None) -> SqliteSaver:
    """A `SqliteSaver` on `acme.db` (its own tables, WAL mode). Close with `saver.conn.close()`."""
    conn = sqlite3.connect(Path(path) if path is not None else get_settings().db_path,
                           check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    saver = SqliteSaver(conn, serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES))
    saver.setup()
    return saver


@contextmanager
def compiled_graph(path: str | Path | None = None) -> Iterator[CompiledStateGraph]:
    saver = open_checkpointer(path)
    try:
        yield build_graph(saver)
    finally:
        saver.conn.close()
