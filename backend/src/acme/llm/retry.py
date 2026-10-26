"""Retry with exponential backoff on rate-limit (429) and server (5xx) errors.

Real provider SDKs are built with `max_retries=0` and wrapped by `RetryingChatMixin`,
so the retry count is known and recorded in `llm_calls`.
"""

import time
from typing import Any

BASE_DELAY_S = 0.5
MAX_DELAY_S = 8.0
sleep = time.sleep  # replaced in tests


def is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return isinstance(status, int) and (status == 429 or 500 <= status < 600)


def backoff_delay(attempt: int) -> float:
    return min(BASE_DELAY_S * 2**attempt, MAX_DELAY_S)


class RetryingChatMixin:
    """Put before a `BaseChatModel` subclass; reads `self.acme_max_retries`."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        attempt = 0
        while True:
            try:
                result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as exc:
                if not is_retryable(exc) or attempt >= self.acme_max_retries:
                    exc.acme_retries = attempt
                    raise
                sleep(backoff_delay(attempt))
                attempt += 1
                continue
            for generation in result.generations:
                generation.message.response_metadata["retries"] = attempt
            return result
