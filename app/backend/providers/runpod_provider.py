"""
RunPod Serverless job-queue provider for llama.cpp (Harvey and Kira).

Submits jobs via POST /v2/{endpoint_id}/run and polls /status/{job_id}
instead of using the unreliable /openai/v1 OpenAI proxy endpoint.
The worker handler.py returns a standard OpenAI chat completion response
as the job output, so we parse it the same way as OpenRouterProvider.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import httpx

from app.backend.providers.base import (
    InvalidSchemaOutputError,
    NonRetryableProviderError,
    RawProviderRequest,
    RawProviderResponse,
    StructuredLLMProvider,
    TransientProviderError,
)
from app.backend.services.metrics import record_provider_call

logger = logging.getLogger(__name__)

_RUNPOD_API_BASE = "https://api.runpod.ai/v2"

_SYSTEM_JSON_PREAMBLE = (
    "You are a legal contract analysis AI assistant. "
    "You MUST respond with a single valid JSON object only. "
    "Do not include markdown fences, commentary, or any text outside the JSON object."
)

_RUNPOD_URL_RE = re.compile(r"https://api\.runpod\.ai/v2/([^/]+)")


def extract_endpoint_id(url: str) -> str | None:
    """Extract RunPod endpoint ID from a URL like .../v2/{id}/openai/v1"""
    m = _RUNPOD_URL_RE.search(url)
    return m.group(1) if m else None


class RunPodJobProvider(StructuredLLMProvider):
    """
    StructuredLLMProvider backed by RunPod's async job queue.

    Uses POST /run to submit, then polls GET /status/{job_id} until
    COMPLETED or FAILED. Works reliably on both cold and warm workers
    because the job queue handles worker assignment.
    """

    def __init__(
        self,
        *,
        endpoint_id: str,
        api_key: str,
        model_name: str,
        temperature: float = 0.3,
        max_output_tokens: int = 8192,
        max_retries: int = 5,
        job_timeout_seconds: float = 600.0,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self._endpoint_id = endpoint_id
        self._model_name = model_name
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._job_timeout = job_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._client = httpx.AsyncClient(
            base_url=_RUNPOD_API_BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(connect=15.0, read=60.0, write=30.0, pool=15.0),
        )

    async def generate_structured_output(
        self,
        prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        from app.backend.providers.openrouter_provider import _schema_hint, _parse_json_response

        schema_hint = _schema_hint(response_schema)
        system_msg = _SYSTEM_JSON_PREAMBLE
        if schema_hint:
            system_msg += f"\n\n{schema_hint}"

        job_input = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "response_format": {"type": "json_object"},
            "thinking_budget": 0,
        }

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
                delay = min(120.0, 10.0 * (2 ** (attempt - 1)))
                logger.info(
                    "RunPodJobProvider retry %d/%d after %.0fs (model=%s)",
                    attempt, self._max_retries, delay, self._model_name,
                )
                await asyncio.sleep(delay)

            t_start = time.monotonic()
            raw_text = ""
            finish_reason = None
            usage = None

            try:
                with record_provider_call("runpod", self._model_name):
                    job_id = await self._submit_job(job_input)
                    logger.debug("RunPod job submitted: endpoint=%s job=%s", self._endpoint_id, job_id)
                    deadline = time.monotonic() + self._job_timeout
                    output = await self._poll_until_done(job_id, deadline)

                if "error" in output:
                    err = output["error"]
                    detail = output.get("detail", "")
                    raise TransientProviderError(
                        f"RunPod worker error: {err}" + (f" — {detail[:300]}" if detail else "")
                    )

                choices = output.get("choices") or []
                if not choices:
                    raise TransientProviderError(
                        f"RunPod job {job_id} returned no choices (output keys: {list(output.keys())})"
                    )

                msg = choices[0].get("message", {})
                raw_text = msg.get("content") or ""
                finish_reason = choices[0].get("finish_reason")
                raw_usage = output.get("usage")
                if raw_usage:
                    usage = {
                        "prompt_token_count": raw_usage.get("prompt_tokens"),
                        "candidates_token_count": raw_usage.get("completion_tokens"),
                        "total_token_count": raw_usage.get("total_tokens"),
                    }

                if finish_reason == "length":
                    raw_response = RawProviderResponse(
                        raw_text=raw_text, parsed_output=None,
                        finish_reason=finish_reason, usage=usage,
                        latency_seconds=time.monotonic() - t_start,
                    )
                    self.on_response_captured(raw_request, raw_response)
                    raise NonRetryableProviderError(
                        f"Output truncated (finish_reason='length', max_tokens={self._max_output_tokens}). "
                        "Increase max_output_tokens or reduce prompt size."
                    )

            except NonRetryableProviderError:
                raise
            except (TransientProviderError, Exception) as exc:
                latency = time.monotonic() - t_start
                raw_response = RawProviderResponse(
                    raw_text=raw_text, parsed_output=None,
                    finish_reason=None, usage=None, latency_seconds=latency,
                )
                last_exc = exc if isinstance(exc, TransientProviderError) else TransientProviderError(str(exc))
                if attempt < self._max_retries:
                    logger.warning(
                        "RunPodJobProvider error (attempt %d/%d, model=%s): %s",
                        attempt + 1, self._max_retries + 1, self._model_name, exc,
                    )
                    continue
                self.on_response_captured(raw_request, raw_response)
                raise last_exc from exc

            try:
                parsed = _parse_json_response(raw_text)
            except InvalidSchemaOutputError as parse_exc:
                latency = time.monotonic() - t_start
                raw_response = RawProviderResponse(
                    raw_text=raw_text, parsed_output=None,
                    finish_reason=finish_reason, usage=usage,
                    latency_seconds=latency,
                )
                self.on_response_captured(raw_request, raw_response)
                if attempt < self._max_retries:
                    logger.warning(
                        "Invalid JSON from RunPod model (attempt %d/%d): %s",
                        attempt + 1, self._max_retries + 1, parse_exc,
                    )
                    last_exc = parse_exc
                    continue
                raise

            raw_response = RawProviderResponse(
                raw_text=raw_text, parsed_output=parsed,
                finish_reason=finish_reason, usage=usage,
                latency_seconds=time.monotonic() - t_start,
            )
            self.on_response_captured(raw_request, raw_response)
            return parsed

        assert last_exc is not None
        raise last_exc

    async def _submit_job(self, job_input: dict) -> str:
        resp = await self._client.post(f"/{self._endpoint_id}/run", json={"input": job_input})
        resp.raise_for_status()
        return resp.json()["id"]

    async def _poll_until_done(self, job_id: str, deadline: float) -> dict:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransientProviderError(
                    f"RunPod job {job_id} on endpoint {self._endpoint_id} timed out "
                    f"after {self._job_timeout:.0f}s"
                )

            resp = await self._client.get(f"/{self._endpoint_id}/status/{job_id}")
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")

            if status == "COMPLETED":
                return data.get("output") or {}
            if status in ("FAILED", "CANCELLED"):
                error = data.get("error") or status
                raise TransientProviderError(f"RunPod job {job_id} {status}: {error}")

            await asyncio.sleep(self._poll_interval)

    async def aclose(self) -> None:
        await self._client.aclose()


async def warmup_endpoint(endpoint_id: str, api_key: str, model_name: str) -> None:
    """
    Fire a minimal 1-token job to wake a cold RunPod worker.
    Called as a background task on user login so the worker is warm
    by the time they upload a contract.
    """
    client = httpx.AsyncClient(
        base_url=_RUNPOD_API_BASE,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0),
    )
    try:
        warmup_input = {
            "model": model_name,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        }
        resp = await client.post(f"/{endpoint_id}/run", json={"input": warmup_input})
        if resp.is_success:
            job_id = resp.json().get("id", "?")
            logger.info("RunPod warmup submitted: endpoint=%s job=%s model=%s", endpoint_id, job_id, model_name)
        else:
            logger.warning("RunPod warmup submit failed: endpoint=%s status=%d", endpoint_id, resp.status_code)
    except Exception as exc:
        logger.warning("RunPod warmup error: endpoint=%s %s", endpoint_id, exc)
    finally:
        await client.aclose()


def build_runpod_provider(
    *,
    endpoint_url: str,
    api_key: str,
    model_name: str,
    temperature: float = 0.3,
    max_output_tokens: int = 16384,
    max_retries: int = 5,
    job_timeout_seconds: float = 600.0,
) -> RunPodJobProvider:
    """Build a RunPodJobProvider from a full RunPod endpoint URL."""
    endpoint_id = extract_endpoint_id(endpoint_url)
    if not endpoint_id:
        raise ValueError(
            f"Cannot extract RunPod endpoint ID from URL: {endpoint_url!r}. "
            "Expected format: https://api.runpod.ai/v2/<endpoint_id>/..."
        )
    return RunPodJobProvider(
        endpoint_id=endpoint_id,
        api_key=api_key,
        model_name=model_name,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        job_timeout_seconds=job_timeout_seconds,
    )
