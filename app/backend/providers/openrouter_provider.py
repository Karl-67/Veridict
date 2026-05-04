"""
OpenRouter provider — implements StructuredLLMProvider via the OpenAI-compatible API.

Uses JSON-object mode + schema-in-prompt so it works with any instruction-tuned
model on OpenRouter, including free-tier models that don't support native
json_schema enforcement.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError

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

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_SYSTEM_JSON_PREAMBLE = (
    "You are a legal contract analysis AI assistant. "
    "You MUST respond with a single valid JSON object only. "
    "Do not include markdown fences, commentary, or any text outside the JSON object."
)


def _schema_hint(schema: dict[str, Any]) -> str:
    """Convert a JSON schema to a compact inline description for the prompt."""
    props = schema.get("properties", {})
    if not props:
        return ""
    lines = ["Required JSON structure:"]
    for key, val in props.items():
        typ = val.get("type", "any")
        enum = val.get("enum")
        items = val.get("items", {})
        if typ == "array":
            item_enum = items.get("enum")
            item_type = items.get("type", "object")
            if item_enum:
                lines.append(f'  "{key}": array of ({" | ".join(item_enum)})')
            elif item_type == "object":
                sub_props = items.get("properties", {})
                sub_keys = list(sub_props.keys())
                lines.append(f'  "{key}": array of objects with keys: {sub_keys}')
                for sk, sv in sub_props.items():
                    se = sv.get("enum")
                    if se:
                        lines.append(f'    "{sk}": {" | ".join(se)}')
            else:
                lines.append(f'  "{key}": array of {item_type}')
        elif enum:
            lines.append(f'  "{key}": {" | ".join(str(e) for e in enum)}')
        else:
            lines.append(f'  "{key}": {typ}')
    return "\n".join(lines)


def _parse_retry_after(exc: APIStatusError) -> float | None:
    """Extract retry-after seconds from OpenRouter's X-RateLimit-Reset header (ms UTC epoch)."""
    try:
        import time
        meta = exc.body.get("error", {}).get("metadata", {}) if isinstance(exc.body, dict) else {}
        reset_ms_str = (meta.get("headers") or {}).get("X-RateLimit-Reset")
        if reset_ms_str:
            reset_at = int(reset_ms_str) / 1000.0
            delay = reset_at - time.time() + 1.5   # 1.5s safety margin
            return max(1.0, delay)
    except Exception:
        pass
    return None


def _classify_openai_error(exc: Exception) -> ProviderError:
    from app.backend.providers.base import ProviderError  # local to avoid circular

    if isinstance(exc, APIStatusError):
        code = exc.status_code
        msg = str(exc)
        if code == 429:
            retry_after = _parse_retry_after(exc)
            # If reset is more than 10 minutes away it's a daily quota — fail immediately
            if retry_after is not None and retry_after > 600:
                return NonRetryableProviderError(
                    f"Daily quota exhausted (resets in {retry_after / 3600:.1f}h): {msg}",
                    status_code=429,
                )
            return RateLimitError(msg, retry_after_seconds=retry_after)
        if code in (405, 500, 502, 503, 504):
            # 405 from llama.cpp/RunPod proxy indicates the server crashed and is restarting.
            # Treat as transient so the retry loop can wait for recovery.
            return TransientProviderError(msg, status_code=code)
        if 400 <= code < 500:
            return NonRetryableProviderError(msg, status_code=code)
        return TransientProviderError(msg, status_code=code)

    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return TransientProviderError(str(exc))

    return TransientProviderError(str(exc))


class OpenRouterProvider(StructuredLLMProvider):
    """
    LLM provider backed by OpenRouter's OpenAI-compatible API.

    Works with any instruction-tuned model available on OpenRouter,
    including free-tier models. Structured output is achieved via
    response_format=json_object plus an explicit schema hint in the prompt.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "google/gemma-4-31b-it:free",
        base_url: str = _OPENROUTER_BASE_URL,
        temperature: float = 0.3,
        max_output_tokens: int = 8192,
        max_retries: int = 3,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 90.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        extra_headers = (
            {"HTTP-Referer": "https://verdict.app", "X-Title": "Verdict Legal AI"}
            if "openrouter.ai" in base_url
            else {}
        )
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=extra_headers,
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0),
        )
        self._model_name = model_name
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._extra_body = extra_body or {}

    async def generate_structured_output(
        self,
        prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        schema_hint = _schema_hint(response_schema)
        system_msg = _SYSTEM_JSON_PREAMBLE
        if schema_hint:
            system_msg += f"\n\n{schema_hint}"

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
                    "OpenRouterProvider retry %d/%d after %.1fs (model=%s)",
                    attempt, self._max_retries, delay, self._model_name,
                )
                await asyncio.sleep(delay)

            t_start = time.monotonic()
            raw_text = ""
            finish_reason = None
            usage = None

            try:
                response = await self._client.chat.completions.create(
                    model=self._model_name,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=self._temperature,
                    max_tokens=self._max_output_tokens,
                    response_format={"type": "json_object"},
                    extra_body=self._extra_body if self._extra_body else None,
                )
                latency = time.monotonic() - t_start
                msg = response.choices[0].message
                raw_text = msg.content or ""
                # vLLM thinking models may return reasoning tokens in a separate
                # reasoning_content field. Log it so we can confirm thinking is
                # disabled; if content is empty and only reasoning arrived the
                # model burned its full token budget on thinking.
                reasoning_content = (
                    getattr(msg, "reasoning_content", None)
                    or (msg.model_extra or {}).get("reasoning_content")
                )
                if reasoning_content:
                    logger.warning(
                        "Model returned reasoning_content (%d chars) — "
                        "enable_thinking=False is NOT being respected by vLLM. "
                        "Fix: restart vLLM with a no-think chat template "
                        "(--chat-template /workspace/no_think.jinja).",
                        len(reasoning_content),
                    )
                finish_reason = response.choices[0].finish_reason
                if response.usage:
                    usage = {
                        "prompt_token_count": response.usage.prompt_tokens,
                        "candidates_token_count": response.usage.completion_tokens,
                        "total_token_count": response.usage.total_tokens,
                    }

            except (RateLimitError, TransientProviderError, NonRetryableProviderError):
                raise
            except Exception as exc:
                latency = time.monotonic() - t_start
                classified = _classify_openai_error(exc)
                last_exc = classified
                raw_response = RawProviderResponse(
                    raw_text=raw_text,
                    parsed_output=None,
                    finish_reason=None,
                    usage=None,
                    latency_seconds=latency,
                )
                if isinstance(classified, NonRetryableProviderError):
                    self.on_response_captured(raw_request, raw_response)
                    raise classified from exc
                if isinstance(classified, (RateLimitError, TransientProviderError)):
                    if attempt < self._max_retries:
                        delay_preview = self._backoff_delay(attempt + 1, classified)
                        logger.warning(
                            "OpenRouterProvider rate-limited (attempt %d/%d), retry in %.1fs",
                            attempt + 1, self._max_retries + 1, delay_preview,
                        )
                        last_exc = classified
                        continue
                    self.on_response_captured(raw_request, raw_response)
                    raise classified from exc
                self.on_response_captured(raw_request, raw_response)
                raise classified from exc

            parsed = _parse_json_response(raw_text)
            raw_response = RawProviderResponse(
                raw_text=raw_text,
                parsed_output=parsed,
                finish_reason=finish_reason,
                usage=usage,
                latency_seconds=latency,
            )
            self.on_response_captured(raw_request, raw_response)
            return parsed

        assert last_exc is not None
        raise last_exc

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Call this before the event loop tears down."""
        await self._client.close()

    def _backoff_delay(self, attempt: int, last_exc: Exception | None) -> float:
        import random
        if isinstance(last_exc, RateLimitError):
            if last_exc.retry_after_seconds:
                return min(last_exc.retry_after_seconds, self._max_backoff)
            return self._max_backoff
        # 405/502/503 = llama.cpp / vLLM crashed and is reloading weights.
        # Recovery takes 2-5 minutes — always wait the full max_backoff rather than
        # a short random delay that would burn retries before the server is back.
        crash_codes = (405, 502, 503)
        if isinstance(last_exc, TransientProviderError) and getattr(last_exc, "status_code", None) in crash_codes:
            return self._max_backoff
        cap = min(self._max_backoff, self._base_backoff * (2 ** attempt))
        return random.uniform(cap / 2, cap)


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    """Parse JSON from the model response, stripping markdown fences and repairing if needed."""
    cleaned = raw_text.strip()
    # Strip Gemma-4 chain-of-thought thinking block (<think>...</think>) before parsing.
    # When enable_thinking=True the model prepends a reasoning trace; we only want the JSON part.
    if cleaned.startswith("<think>"):
        import re as _re
        cleaned = _re.sub(r"<think>.*?</think>", "", cleaned, flags=_re.DOTALL).strip()
    # Detect an HTML error page (e.g. nginx 405 when a POST hits the wrong backend).
    # Raise immediately with a human-readable message instead of storing raw HTML as failure text.
    if cleaned.startswith("<"):
        import re as _re
        title_match = _re.search(r"<title>([^<]{1,80})</title>", cleaned, _re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "HTML response"
        # 405/502/503 HTML pages from RunPod proxy mean llama.cpp crashed and is restarting.
        # Raise TransientProviderError so the retry loop waits and tries again.
        is_server_error = bool(_re.search(r"405|502|503|Not Allowed|Bad Gateway|unavailable", title, _re.I))
        if is_server_error:
            raise TransientProviderError(
                f"Model server temporarily unavailable ({title}) — will retry.",
            )
        raise NonRetryableProviderError(
            f"Model endpoint returned an HTML error page ({title}). "
            "Check that VLLM_BASE_URL / KIRA_MODEL_URL point to the OpenAI-compatible "
            "/v1 API base, not a browser UI or root URL.",
        )
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()
    if not cleaned:
        raise InvalidSchemaOutputError("Model returned an empty response.", raw_response=raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try json-repair for truncated/malformed model output (common with small local models)
        try:
            from json_repair import repair_json
            repaired = repair_json(cleaned, return_objects=True)
            if isinstance(repaired, dict):
                logger.debug("json_repair recovered malformed model output")
                return repaired
            parsed = repaired
        except Exception:
            parsed = None
        if not isinstance(parsed, dict):
            raise InvalidSchemaOutputError(
                f"Model response is not valid JSON and could not be repaired.", raw_response=raw_text
            )
    if not isinstance(parsed, dict):
        raise InvalidSchemaOutputError(
            f"Expected a JSON object, got {type(parsed).__name__}.", raw_response=raw_text
        )
    return parsed


def build_openrouter_provider(
    *,
    api_key: str,
    model_name: str = "google/gemma-4-31b-it:free",
    temperature: float = 0.3,
    max_output_tokens: int = 8192,
    max_retries: int = 3,
) -> OpenRouterProvider:
    return OpenRouterProvider(
        api_key=api_key,
        model_name=model_name,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )


def build_ollama_provider(
    *,
    base_url: str = "http://localhost:11434/v1",
    model_name: str = "llama3.2:latest",
    temperature: float = 0.3,
    max_output_tokens: int = 8192,
    max_retries: int = 2,
) -> OpenRouterProvider:
    """Build a provider pointing at a local Ollama instance (OpenAI-compatible API)."""
    return OpenRouterProvider(
        api_key="ollama",          # Ollama ignores the key but the client requires one
        base_url=base_url,
        model_name=model_name,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        base_backoff_seconds=1.0,
        max_backoff_seconds=10.0,  # Local — no real rate limits
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )


def build_vllm_provider(
    *,
    base_url: str,
    model_name: str = "google/gemma-4-26B-A4B-it",
    temperature: float = 0.3,
    max_output_tokens: int = 8192,
    max_retries: int = 8,
    extra_body: dict[str, Any] | None = None,
) -> OpenRouterProvider:
    """Build a provider pointing at a cluster-internal vLLM/llama.cpp server (OpenAI-compatible API).

    max_retries defaults to 8 — higher than stage-level retries because llama.cpp on RunPod
    can take 2-5 minutes to reload weights after a crash, and we want to absorb that
    within a single stage attempt rather than failing the whole run.

    thinking is disabled via chat_template_kwargs — llama.cpp serves Gemma-4 with the jinja
    thinking template enabled by default, which causes reasoning_content to consume the entire
    completion token budget leaving content empty on any non-trivial prompt.
    """
    # Disable thinking via every mechanism vLLM exposes.
    # chat_template_kwargs is the documented approach but vLLM does not always
    # honour it (depends on model template).  reasoning_effort="none" is
    # accepted by vLLM 0.17+ for thinking-capable models as an alternative.
    body: dict[str, Any] = {
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
    }
    if extra_body:
        body.update(extra_body)
    return OpenRouterProvider(
        api_key="vllm",
        base_url=base_url,
        model_name=model_name,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        base_backoff_seconds=5.0,
        max_backoff_seconds=120.0,
        extra_body=body,
    )
