from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI, Response

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
except ImportError:
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _Metric:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def labels(self, **kwargs):
            return self

        def inc(self, *args, **kwargs) -> None:
            pass

        def observe(self, *args, **kwargs) -> None:
            pass

    Counter = Histogram = _Metric  # type: ignore

    def generate_latest() -> bytes:
        return b""


runs_total = Counter("runs_total", "Runs by status.", ["status"])
stage_duration_seconds = Histogram("stage_duration_seconds", "Stage duration.", ["stage"])
provider_latency_seconds = Histogram("provider_latency_seconds", "LLM provider latency.", ["provider", "model"])
provider_failures_total = Counter("provider_failures_total", "LLM provider failures.", ["provider", "model"])
json_repair_total = Counter("json_repair_total", "JSON repairs attempted.")
retrieval_hits_total = Counter("retrieval_hits_total", "Retrieved RAG hits.")
citation_validation_failures_total = Counter("citation_validation_failures_total", "Citation validation failures.", ["code"])
queue_age_seconds = Histogram("queue_age_seconds", "Queue age at dequeue.")
retry_total = Counter("retry_total", "Stage retry count.", ["stage"])
worker_lease_expiry_total = Counter("worker_lease_expiry_total", "Expired worker leases.")


@contextmanager
def record_provider_call(provider: str, model: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    except Exception:
        provider_failures_total.labels(provider=provider, model=model).inc()
        raise
    finally:
        provider_latency_seconds.labels(provider=provider, model=model).observe(time.perf_counter() - start)


def setup_metrics(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
