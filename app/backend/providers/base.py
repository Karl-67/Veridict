"""
Provider base classes and error hierarchy.

All concrete LLM provider implementations (openrouter, vllm, gemini, ollama)
must subclass StructuredLLMProvider and raise from this error hierarchy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base class for all provider errors."""


class TransientProviderError(ProviderError):
    """Retriable error (5xx, network timeout). Caller should back off and retry."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NonRetryableProviderError(ProviderError):
    """Permanent failure (bad API key, policy block, malformed request). Do not retry."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(ProviderError):
    """Provider rate-limit (429). Retry after the indicated delay."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class InvalidSchemaOutputError(ProviderError):
    """Model returned a response that could not be parsed or did not match the schema."""

    def __init__(self, message: str, *, raw_response: str = "") -> None:
        super().__init__(message)
        self.raw_response = raw_response


# ---------------------------------------------------------------------------
# Audit data-transfer objects
# ---------------------------------------------------------------------------


@dataclass
class RawProviderRequest:
    model: str
    prompt: str
    response_schema: dict[str, Any]
    temperature: float
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawProviderResponse:
    raw_text: str
    parsed_output: dict[str, Any] | None
    finish_reason: str | None
    usage: dict[str, Any] | None
    latency_seconds: float


# ---------------------------------------------------------------------------
# Abstract provider interface
# ---------------------------------------------------------------------------


class StructuredLLMProvider(ABC):
    """
    Contract that every LLM provider adapter must satisfy.

    Implementations are responsible for:
    - Transport (HTTP, SDK, etc.)
    - Structured-output mode or schema-in-prompt
    - Retry / back-off
    - Mapping SDK errors to the provider error hierarchy above
    - Calling on_request_captured / on_response_captured for audit
    """

    @abstractmethod
    async def generate_structured_output(
        self,
        prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Send *prompt* to the model and return a dict conforming to *response_schema*.

        Raises:
            InvalidSchemaOutputError: Response was not valid JSON or did not match schema.
            RateLimitError: Rate-limited and all retries exhausted.
            TransientProviderError: 5xx / network failure after all retries.
            NonRetryableProviderError: Permanent failure.
        """

    def on_request_captured(self, request: RawProviderRequest) -> None:
        """Called before each LLM call. Override to persist audit records."""

    def on_response_captured(
        self, request: RawProviderRequest, response: RawProviderResponse
    ) -> None:
        """Called after each LLM call (success or non-retryable failure). Override to persist."""
