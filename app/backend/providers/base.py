"""
Provider base — gemini-provider-boundary

Defines the interface that all LLM providers must implement.
Agents depend only on StructuredLLMProvider; the concrete provider
(GeminiProvider, or a future local model) is injected at runtime.

Boundary invariant:
  - Providers own: transport, structured-output schema binding,
    retry/backoff, and raw request/response capture.
  - Agents own: prompt construction and schema interpretation.
  This boundary must not be crossed.
"""

from __future__ import annotations

import abc
import datetime
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base class for all provider-level errors."""


class InvalidSchemaOutputError(ProviderError):
    """
    The provider returned a response that does not conform to the
    requested response_schema (missing fields, wrong types, JSON parse
    failure, etc.).

    This is non-retryable by default — the same prompt with the same
    schema will likely produce the same bad output.
    """

    def __init__(self, message: str, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class TransientProviderError(ProviderError):
    """
    A transient infrastructure failure (network timeout, 5xx from the
    provider API, etc.). The caller should retry with backoff.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(TransientProviderError):
    """
    The provider returned a rate-limit / quota-exhausted response (429).
    Inherits from TransientProviderError so callers that catch transient
    errors handle rate limits automatically, but callers that need to
    distinguish can catch this subclass specifically.
    """

    def __init__(
        self,
        message: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class NonRetryableProviderError(ProviderError):
    """
    A permanent provider error that should NOT be retried — for example,
    an invalid API key, a model that no longer exists, or a request that
    was explicitly rejected for policy reasons.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Raw capture dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RawProviderRequest:
    """Snapshot of the outgoing request sent to the provider."""

    model: str
    prompt: str
    response_schema: dict[str, Any]
    temperature: float
    extra_params: dict[str, Any] = field(default_factory=dict)
    captured_at: datetime.datetime = field(
        default_factory=datetime.datetime.utcnow
    )


@dataclass
class RawProviderResponse:
    """Snapshot of the raw response received from the provider."""

    raw_text: str
    parsed_output: dict[str, Any] | None
    finish_reason: str | None
    usage: dict[str, Any] | None          # token counts, etc.
    latency_seconds: float | None
    captured_at: datetime.datetime = field(
        default_factory=datetime.datetime.utcnow
    )


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class StructuredLLMProvider(abc.ABC):
    """
    Abstract base class for all LLM providers used by role agents.

    Implementors (e.g. GeminiProvider) are responsible for:
      - Sending the prompt to the underlying model.
      - Binding response_schema to enforce structured output.
      - Applying retry/backoff for transient errors.
      - Capturing the raw request and response for audit purposes.

    Agents call only `generate_structured_output`. They must NOT
    instantiate concrete providers directly — inject via dependency.
    """

    # ------------------------------------------------------------------
    # Core interface (must implement)
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def generate_structured_output(
        self,
        prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Send *prompt* to the underlying model and return a dict that
        conforms to *response_schema*.

        Args:
            prompt: The fully-constructed prompt string. The agent is
                responsible for building this — the provider must not
                modify it.
            response_schema: A JSON-Schema-compatible dict describing the
                expected response structure. The provider must use this
                to request structured output from the model (e.g. via
                Gemini's `response_schema` config field).

        Returns:
            A dict whose shape matches *response_schema*.

        Raises:
            InvalidSchemaOutputError: Response could not be parsed or
                does not conform to the schema.
            RateLimitError: Provider returned a 429 / quota response.
            TransientProviderError: Recoverable infrastructure failure.
            NonRetryableProviderError: Permanent failure (auth, policy).
        """

    # ------------------------------------------------------------------
    # Capture hooks (optional override)
    # ------------------------------------------------------------------

    def on_request_captured(self, request: RawProviderRequest) -> None:
        """
        Called immediately before the HTTP request is sent.

        Override to persist the raw request for audit/debugging.
        Default implementation is a no-op.
        """

    def on_response_captured(
        self,
        request: RawProviderRequest,
        response: RawProviderResponse,
    ) -> None:
        """
        Called immediately after a response is received (success or
        non-retryable failure).

        Override to persist the raw request/response pair.
        Default implementation is a no-op.
        """
