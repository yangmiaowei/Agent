import logging
import os
import random
import time
from typing import List, Dict

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OverloadedError,
    RateLimitError,
)
from dotenv import load_dotenv

from src.model.usage import Usage
from src.prompts.system_prompt import build_system_prompt

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("MODEL")

logger = logging.getLogger(__name__)

RETRYABLE_EXCEPTIONS = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
    OverloadedError,
)
RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})

# Provider-specific "out of quota / balance" messages that arrive as 429
# RateLimitError but must not be retried — retries only burn wall time.
NON_RETRYABLE_MARKERS = (
    "余额不足",
    "无可用资源包",
    "insufficient",
    "quota",
    "billing",
    "payment",
    "credit",
)


def _is_retryable(exc: Exception) -> bool:
    message = str(exc).lower()
    if any(marker.lower() in message for marker in NON_RETRYABLE_MARKERS):
        return False
    if isinstance(exc, RETRYABLE_EXCEPTIONS):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in RETRYABLE_STATUS_CODES
    return False


class AnthropicClient:
    def __init__(
        self,
        api_key: str = ANTHROPIC_API_KEY,
        base_url: str = ANTHROPIC_BASE_URL,
        model: str = MODEL,
        *,
        max_retries: int = 5,
        retry_base_delay: float = 2.0,
        retry_max_delay: float = 60.0,
    ):
        self.client = Anthropic(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        # Cumulative token accounting across every call made by this client.
        self.usage = Usage()
        self.last_usage = Usage()

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 8000,
        tools=None,
        system: str = None,
    ):
        if tools is None:
            raise ValueError("tools (ToolView or ToolManager) is required")
        tool_schemas = tools.list_tools()

        response = self._create_with_retry(
            system=system or build_system_prompt(),
            messages=messages,
            tool_schemas=tool_schemas,
            max_tokens=max_tokens,
        )

        self.last_usage = Usage.from_response(response)
        self.usage.add(self.last_usage)
        return response

    def complete(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 2000,
        system: str = None,
    ):
        """Tool-free completion, used for summarization-style calls."""
        response = self._create_with_retry(
            system=system or "You are a helpful assistant.",
            messages=messages,
            tool_schemas=[],
            max_tokens=max_tokens,
        )
        self.last_usage = Usage.from_response(response)
        self.usage.add(self.last_usage)
        return response

    def _create_with_retry(self, *, system, messages, tool_schemas, max_tokens):
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self.client.messages.create(
                    model=self.model,
                    system=system,
                    messages=messages,
                    tools=tool_schemas,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries or not _is_retryable(exc):
                    raise
                delay = min(
                    self.retry_max_delay,
                    self.retry_base_delay * 2 ** (attempt - 1),
                )
                delay += random.uniform(0, delay * 0.25)
                logger.warning(
                    "LLM call failed (%s: %s), retrying in %.1fs [%d/%d]",
                    type(exc).__name__,
                    exc,
                    delay,
                    attempt,
                    self.max_retries,
                )
                time.sleep(delay)
        raise last_exc  # pragma: no cover - loop always returns or raises
