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

from app.backend.services.metrics import record_provider_call
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
        if "openrouter" in base_url:
            self._provider_name = "openrouter"
        elif "ollama" in base_url or "11434" in base_url:
            self._provider_name = "ollama"
        else:
            self._provider_name = "vllm"
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
                with record_provider_call(self._provider_name, self._model_name):
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

            try:
                parsed = _parse_json_response(raw_text)
            except InvalidSchemaOutputError as parse_exc:
                # Bad JSON from the model is transient — a retry almost always returns
                # a valid response. Treat it like a transient error so the retry loop
                # runs again rather than immediately failing the stage.
                latency = time.monotonic() - t_start
                raw_response = RawProviderResponse(
                    raw_text=raw_text,
                    parsed_output=None,
                    finish_reason=finish_reason,
                    usage=usage,
                    latency_seconds=latency,
                )
                self.on_response_captured(raw_request, raw_response)
                if attempt < self._max_retries:
                    logger.warning(
                        "Invalid JSON from model (attempt %d/%d), retrying — %s",
                        attempt + 1, self._max_retries + 1, parse_exc,
                    )
                    last_exc = parse_exc
                    continue
                raise
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
    import re as _re
    cleaned = raw_text.strip()
    # Strip Gemma-4 built-in thinking block (<think>...</think>).
    if "<think>" in cleaned:
        cleaned = _re.sub(r"<think>.*?</think>", "", cleaned, flags=_re.DOTALL).strip()
    # Strip Harvey fine-tune reasoning tokens.
    # Harvey emits several variants before the JSON answer:
    #   <thought>...</thought>          — closed reasoning block
    #   <|channel>_thought\n<channel|>  — tokeniser artifact + answer marker
    #   <|channel>thought\n<channel|>   — same without underscore
    #   <channel|>                      — bare answer-start marker
    # Strategy: strip everything up to and including the last <channel|> occurrence,
    # then fall back to <thought>...</thought> removal for any remaining blocks.
    if "<channel|>" in cleaned:
        last_marker = cleaned.rfind("<channel|>")
        cleaned = cleaned[last_marker + len("<channel|>"):].strip()
    if "<thought>" in cleaned:
        cleaned = _re.sub(r"<thought>.*?</thought>", "", cleaned, flags=_re.DOTALL).strip()
    # Strip any residual <|channel>... tokens (Harvey tokeniser artifacts).
    if cleaned.startswith("<|"):
        cleaned = _re.sub(r"^<\|[^>]*>\s*", "", cleaned).strip()
    # If response still starts with "<" after stripping, Harvey may have emitted an unclosed
    # <thought> block or other tag. Try to rescue by finding where the JSON object starts.
    if cleaned.startswith("<") and not _re.match(r"<(html|!DOCTYPE|head|body)", cleaned, _re.I):
        json_start = next((i for i, c in enumerate(cleaned) if c in "{["), -1)
        if json_start != -1:
            logger.warning("Stripping unexpected leading tokens before JSON (offset %d): %.120s", json_start, cleaned[:json_start])
            cleaned = cleaned[json_start:].strip()
    # Detect an HTML error page (e.g. nginx 405 when a POST hits the wrong backend).
    # Raise immediately with a human-readable message instead of storing raw HTML as failure text.
    if cleaned.startswith("<"):
        title_match = _re.search(r"<title>([^<]{1,80})</title>", cleaned, _re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "HTML response"
        # 405/502/503 HTML pages from RunPod proxy mean llama.cpp crashed and is restarting.
        # Raise TransientProviderError so the retry loop waits and tries again.
        is_server_error = bool(_re.search(r"405|502|503|Not Allowed|Bad Gateway|unavailable", title, _re.I))
        if is_server_error:
            raise TransientProviderError(
                f"Model server temporarily unavailable ({title}) — will retry.",
            )
        # Unknown < prefix — treat as transient so the retry loop tries again rather than
        # permanently failing the stage. Log the raw content for diagnosis.
        preview = cleaned[:300].replace("\n", "\\n")
        logger.error("Unexpected non-JSON response starting with '<' (len=%d): %s", len(cleaned), preview)
        raise TransientProviderError(
            f"Model returned unexpected non-JSON content starting with '<' ({title}) — will retry.",
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
    except json.JSONDecodeError as first_exc:
        parsed = _repair_json(cleaned, raw_text, first_exc)
    if not isinstance(parsed, dict):
        raise InvalidSchemaOutputError(
            f"Expected a JSON object, got {type(parsed).__name__}.", raw_response=raw_text
        )
    return parsed


def _repair_json(cleaned: str, raw_text: str, first_exc: Exception) -> dict:
    """Multi-strategy JSON repair for malformed model output."""
    import re as _re

    # Strategy 1: json_repair in string mode — more reliable than return_objects=True
    # because it always returns a string we can inspect before loading.
    try:
        from json_repair import repair_json
        repaired_str = repair_json(cleaned)
        if repaired_str and repaired_str.strip() not in ("", "null", "[]", "{}"):
            try:
                repaired = json.loads(repaired_str)
                if isinstance(repaired, dict):
                    logger.info("json_repair (string mode) recovered malformed model output")
                    return repaired
            except json.JSONDecodeError:
                pass
    except Exception as repair_exc:
        logger.debug("json_repair raised: %s", repair_exc)

    # Strategy 2: strip unescaped quotes inside string values.
    # Kira's fine-tune sometimes writes  "key": "value with "quotes" inside"
    # which breaks standard parsers. Replace inner double-quotes with single quotes.
    try:
        def _fix_inner_quotes(m: "_re.Match") -> str:
            key, val = m.group(1), m.group(2)
            # Replace any unescaped " inside the value with '
            fixed = _re.sub(r'(?<!\\)"', "'", val)
            return f'"{key}": "{fixed}"'
        fixed = _re.sub(r'"(\w+)":\s*"(.*?)"(?=\s*[,}\]])', _fix_inner_quotes, cleaned, flags=_re.DOTALL)
        if fixed != cleaned:
            repaired = json.loads(fixed)
            if isinstance(repaired, dict):
                logger.info("Inner-quote sanitizer recovered malformed model output")
                return repaired
    except Exception:
        pass

    # Strategy 3: extract the findings array via regex and rebuild the envelope.
    # Handles cases where the outer structure is broken but individual objects are intact.
    try:
        obj_pattern = _re.compile(r'\{[^{}]*"clause_uid"\s*:\s*"[^"]*"[^{}]*\}', _re.DOTALL)
        objects = obj_pattern.findall(cleaned)
        valid = []
        for obj in objects:
            try:
                valid.append(json.loads(obj))
            except json.JSONDecodeError:
                pass
        if valid:
            logger.warning("Regex extractor rescued %d/%d findings from malformed JSON", len(valid), len(objects))
            return {"findings": valid}
    except Exception:
        pass

    # All strategies failed — log head and tail for diagnosis.
    head = raw_text[:400].replace("\n", "\\n")
    tail = raw_text[-200:].replace("\n", "\\n")
    logger.error(
        "All JSON repair strategies failed (len=%d, err=%s)\n  HEAD: %s\n  TAIL: %s",
        len(raw_text), first_exc, head, tail,
    )
    raise InvalidSchemaOutputError(
        "Model response is not valid JSON and could not be repaired.", raw_response=raw_text
    )


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
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning_effort": "none",
            "thinking_budget": 0,
        },
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
    # Disable thinking via every mechanism vLLM/llama.cpp expose.
    # chat_template_kwargs is the vLLM approach; reasoning_effort="none" is
    # accepted by vLLM 0.17+; thinking_budget=0 is the llama.cpp per-request
    # control for Gemma-4 thinking models (ignored silently by other servers).
    body: dict[str, Any] = {
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
        "thinking_budget": 0,
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
