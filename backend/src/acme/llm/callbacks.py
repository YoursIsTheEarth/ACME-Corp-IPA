"""LangChain callback that records every chat-model call in `llm_calls`.

Pass the prompt version as invocation metadata:
    model.invoke(messages, config={"metadata": {"prompt_version": "extraction.v3"}})
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from acme.db import connect
from acme.logging import agent_var, run_id_var

log = logging.getLogger(__name__)


class LLMCallRecorder(BaseCallbackHandler):
    run_inline = True  # keep the caller's context vars (run_id, agent)

    def __init__(self, provider: str, model: str, role: str) -> None:
        self.provider = provider
        self.model = model
        self.role = role
        self._starts: dict[UUID, tuple[float, str | None]] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id: UUID, metadata=None, **kwargs: Any):
        self._starts[run_id] = (time.perf_counter(), (metadata or {}).get("prompt_version"))

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        tokens_in = tokens_out = retries = 0
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) or {}
                tokens_in += usage.get("input_tokens", 0)
                tokens_out += usage.get("output_tokens", 0)
                retries = max(retries, (getattr(message, "response_metadata", None) or {}).get("retries", 0))
        self._record(run_id, tokens_in, tokens_out, retries, failed=False, error=None)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._record(run_id, 0, 0, getattr(error, "acme_retries", 0), failed=True,
                     error=f"{type(error).__name__}: {error}")

    def _record(self, call_id, tokens_in, tokens_out, retries, failed, error) -> None:
        started, prompt_version = self._starts.pop(call_id, (time.perf_counter(), None))
        row = {
            "run_id": run_id_var.get(),
            "agent": agent_var.get() or self.role,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": prompt_version,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "retries": retries,
            "failed": int(failed),
            "error": error,
            "ts": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        }
        log.info("llm_call", extra={"data": row})
        conn = connect()
        try:
            conn.execute(
                f"INSERT INTO llm_calls ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                tuple(row.values()),
            )
            conn.commit()
        finally:
            conn.close()
