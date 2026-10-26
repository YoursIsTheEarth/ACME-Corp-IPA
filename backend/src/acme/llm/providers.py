"""Real provider classes. Imported only when a real provider is selected."""

from langchain_anthropic import ChatAnthropic
from langchain_xai import ChatXAI

from acme.llm.retry import RetryingChatMixin


class RetryingChatXAI(RetryingChatMixin, ChatXAI):
    acme_max_retries: int = 3


class RetryingChatAnthropic(RetryingChatMixin, ChatAnthropic):
    acme_max_retries: int = 3
