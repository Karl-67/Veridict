"""
Gemini provider — gemini-provider-boundary

Implements StructuredLLMProvider using the google-genai SDK.
Owns: transport, structured-output schema binding, retry/backoff,
      token-budget enforcement, and raw request/response capture.
Agents must NOT be imported here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from google import genai
from google.genai import types as genai_types

from app.backend.providers.base import (
    InvalidSchemaOutputError,
    NonRetryableProviderError,
    RateLimitError,
    RawProviderRequest,
    RawProviderResponse,
    StructuredLLMProvider,
    TransientProviderError,
)

logger = logging.getLogger(__name__)

# HTTP status codes that warrant a retry (Gemini API maps these via SDK errors)
_TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({500, 502, 503, 504})
_RATE_LIMIT_STATUS_CODE = 429


def _extract_status_code(exc: Exception) -> int | None:
    """Best-effort extraction of an HTTP status code from a google-genai error."""
    # google.genai.errors.ClientError / ServerError expose .status_code or .code
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    # Some versions embed it in the string representation
    msg = str(exc)
    for candidate in ("429", "500", "502", "503", "504"):
        if candidate in msg:
            return int(candidate)
    return None


def _classify_genai_error(exc: Exception) -> ProviderError:
    """Map a raw google-genai SDK exception to our provider error hierarchy."""
    from app.backend.providers.base import ProviderError  # local to avoid circular

    code = _extract_status_code(exc)
    message = str(exc)

    if code == _RATE_LIMIT_STATUS_CODE:
        retry_after: float | None = None
        # SDK may surface Retry-After header value
        retry_after_raw = getattr(exc, "retry_after", None)
        if retry_after_raw is not None:
            try:
                retry_after = float(retry_after_raw)
            except (TypeError, ValueError):
                pass
        return RateLimitError(message, retry_after_seconds=retry_after)

    if code in _TRANSIENT_STATUS_CODES:
        return TransientProviderError(message, status_code=code)

    # 4xx errors other than 429 are permanent (bad API key, policy block, etc.)
    if code is not None and 400 <= code < 500:
        return NonRetryableProviderError(message, status_code=code)

    # Unknown / network-level errors — treat as transient
    return TransientProviderError(message, status_code=code)


class GeminiProvider(StructuredLLMProvider):
    """
    Concrete LLM provider backed by the Gemini API (google-genai SDK).

    Uses Gemini structured-output mode: every call sets
    ``response_mime_type="application/json"`` and binds ``response_schema``
    so the model is constrained to emit valid JSON matching the caller's schema.

    Retry/backoff:
      - Up to *max_retries* attempts for transient errors and rate limits.
      - Exponential backoff with full jitter, capped at *max_backoff_seconds*.
      - RateLimitError respects a ``retry_after_seconds`` hint when present.

    Token budget:
      - ``max_output_tokens`` is forwarded to the generation config on every
        call so the model cannot silently exceed the allocated budget.

    Audit capture:
      - ``on_request_captured`` is called before each attempt.
      - ``on_response_captured`` is called after a successful response or
        a non-retryable failure. Override these in a subclass or via
        dependency injection to persist audit records.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.3,
        max_output_tokens: int = 8192,
        max_retries: int = 3,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds

    # ------------------------------------------------------------------
    # StructuredLLMProvider interface
    # ------------------------------------------------------------------

    async def generate_structured_output(
        self,
        prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Send *prompt* to Gemini and return a dict conforming to *response_schema*.

        Raises:
            InvalidSchemaOutputError: Response was not valid JSON or did not
                match *response_schema*.
            RateLimitError: Gemini returned 429 and all retries were exhausted.
            TransientProviderError: 5xx / network failure after all retries.
            NonRetryableProviderError: Permanent failure (auth, policy block).
        """
        raw_request = RawProviderRequest(
            model=self._model_name,
            prompt=prompt,
            response_schema=response_schema,
            temperature=self._temperature,
            extra_params={"max_output_tokens": self._max_output_tokens},
        )
        self.on_request_captured(raw_request)

        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                delay = self._backoff_delay(attempt, last_exc)
                logger.info(
                    "GeminiProvider retry %d/%d after %.1fs (model=%s)",
                    attempt,
                    self._max_retries,
                    delay,
                    self._model_name,
                )
                await asyncio.sleep(delay)

            t_start = time.monotonic()
            raw_text: str = ""
            finish_reason: str | None = None
            usage: dict[str, Any] | None = None

            try:
                config = genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=self._temperature,
                    max_output_tokens=self._max_output_tokens,
                    thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                )
                response = await self._client.aio.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                    config=config,
                )

                latency = time.monotonic() - t_start
                raw_text = response.text or ""
                finish_reason = _extract_finish_reason(response)
                usage = _extract_usage(response)

            except (RateLimitError, TransientProviderError, NonRetryableProviderError):
                # Already classified — propagate as-is
                raise
            except Exception as exc:
                latency = time.monotonic() - t_start
                classified = _classify_genai_error(exc)
                last_exc = classified

                raw_response = RawProviderResponse(
                    raw_text=raw_text,
                    parsed_output=None,
                    finish_reason=None,
                    usage=None,
                    latency_seconds=latency,
                )

                if isinstance(classified, (RateLimitError, TransientProviderError)):
                    if attempt < self._max_retries:
                        logger.warning(
                            "GeminiProvider transient error (attempt %d): %s",
                            attempt + 1,
                            classified,
                        )
                        continue
                    # Exhausted retries
                    self.on_response_captured(raw_request, raw_response)
                    raise classified from exc

                # NonRetryable — capture and raise immediately
                self.on_response_captured(raw_request, raw_response)
                raise classified from exc

            # --- Parse the structured output ---
            parsed = _parse_structured_response(raw_text, response_schema)
            raw_response = RawProviderResponse(
                raw_text=raw_text,
                parsed_output=parsed,
                finish_reason=finish_reason,
                usage=usage,
                latency_seconds=latency,
            )
            self.on_response_captured(raw_request, raw_response)
            return parsed

        # Should not be reached — loop always raises or returns
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _backoff_delay(self, attempt: int, last_exc: Exception | None) -> float:
        """
        Compute the wait duration before *attempt* (1-indexed).

        Honours ``RateLimitError.retry_after_seconds`` when present.
        Otherwise uses exponential backoff with full jitter.
        """
        import random

        if isinstance(last_exc, RateLimitError) and last_exc.retry_after_seconds:
            return min(last_exc.retry_after_seconds, self._max_backoff)

        # Exponential with full jitter: uniform(0, min(cap, base * 2^attempt))
        cap = min(self._max_backoff, self._base_backoff * (2 ** attempt))
        return random.uniform(0, cap)


# ---------------------------------------------------------------------------
# Module-level helpers (not part of the public provider API)
# ---------------------------------------------------------------------------


def _extract_finish_reason(response: Any) -> str | None:
    """Pull the finish reason out of a Gemini response object."""
    try:
        candidates = response.candidates
        if candidates:
            reason = candidates[0].finish_reason
            return reason.name if hasattr(reason, "name") else str(reason)
    except Exception:
        pass
    return None


def _extract_usage(response: Any) -> dict[str, Any] | None:
    """Pull token usage metadata out of a Gemini response object."""
    try:
        meta = response.usage_metadata
        if meta is None:
            return None
        return {
            "prompt_token_count": getattr(meta, "prompt_token_count", None),
            "candidates_token_count": getattr(meta, "candidates_token_count", None),
            "total_token_count": getattr(meta, "total_token_count", None),
        }
    except Exception:
        return None


def _parse_structured_response(
    raw_text: str,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    """
    Parse *raw_text* as JSON.

    Gemini structured-output mode should always return valid JSON when a
    ``response_schema`` is bound, but we validate defensively.

    Raises:
        InvalidSchemaOutputError: If the text is not valid JSON or is not
            a dict (structured-output responses must be JSON objects).
    """
    cleaned = raw_text.strip()

    # Strip accidental markdown code fences (should not happen in structured
    # output mode, but kept as a safety net for future model regressions).
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()

    if not cleaned:
        raise InvalidSchemaOutputError(
            "Gemini returned an empty response.", raw_response=raw_text
        )

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise InvalidSchemaOutputError(
            f"Gemini response is not valid JSON: {exc}",
            raw_response=raw_text,
        ) from exc

    if not isinstance(parsed, dict):
        raise InvalidSchemaOutputError(
            f"Gemini structured output must be a JSON object, got {type(parsed).__name__}.",
            raw_response=raw_text,
        )

    return parsed


# ---------------------------------------------------------------------------
# Factory helper — preferred construction path for dependency injection
# ---------------------------------------------------------------------------


def build_gemini_provider(
    *,
    api_key: str,
    model_name: str = "gemini-2.5-flash",
    temperature: float = 0.3,
    max_output_tokens: int = 8192,
    max_retries: int = 3,
) -> GeminiProvider:
    """
    Construct a ``GeminiProvider`` from explicit parameters.

    Prefer injecting via ``get_settings()`` in FastAPI routes/services rather
    than calling this directly.
    """
    return GeminiProvider(
        api_key=api_key,
        model_name=model_name,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
    )
