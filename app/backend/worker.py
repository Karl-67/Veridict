"""
Worker process entrypoint.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.backend.core.config import get_settings
from app.backend.db.models import RagIngestionJob
from app.backend.db.session import get_sync_session_factory
from app.backend.orchestration.state_machine import claim_next_stage, execute_stage
from app.backend.services.metrics import queue_age_seconds, start_metrics_server
from app.backend.services.rag_ingestion import RagIngestionService

logger = logging.getLogger(__name__)


def _setup_logging(worker_id: str) -> None:
    """Configure root logger: stderr + rotating file at logs/worker.log."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s [%(worker_id)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove any handlers already added by other modules importing logging.
    root.handlers.clear()

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(fmt)
    root.addHandler(stderr_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "worker.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Inject worker_id into every log record via a filter.
    class _WorkerFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.worker_id = worker_id  # type: ignore[attr-defined]
            return True

    for handler in root.handlers:
        handler.addFilter(_WorkerFilter())


def claim_next_rag_ingestion(session) -> RagIngestionJob | None:
    job = session.scalars(
        select(RagIngestionJob)
        .where(RagIngestionJob.status == "pending")
        .order_by(RagIngestionJob.created_at.asc())
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    queue_age_seconds.observe(max(0.0, (datetime.utcnow() - job.created_at).total_seconds()))
    job.status = "running"
    job.started_at = datetime.utcnow()
    session.commit()
    session.refresh(job)
    return job


def run_worker_loop(poll_interval_seconds: float = 1.0) -> None:
    settings = get_settings()
    worker_id = os.getenv("VERDICT_WORKER_ID", f"worker-{uuid4().hex[:8]}")
    _setup_logging(worker_id)
    start_metrics_server(port=int(os.getenv("WORKER_METRICS_PORT", "9100")))
    session_factory = get_sync_session_factory()

    logger.info("Worker started. provider=%s poll_interval=%.1fs", settings.llm_provider, poll_interval_seconds)

    idle_ticks = 0
    while True:
        session = session_factory()
        try:
            stage = claim_next_stage(session, settings, worker_id)
            if stage is None:
                try:
                    rag_job = claim_next_rag_ingestion(session)
                    if rag_job is not None:
                        logger.info("Processing RAG ingestion job %s", rag_job.id)
                        RagIngestionService(session, settings).ingest_document(rag_job.id)
                        session.close()
                        idle_ticks = 0
                        continue
                except Exception:
                    logger.exception("RAG ingestion job failed")
                session.close()
                idle_ticks += 1
                if idle_ticks % 60 == 0:
                    logger.info("Worker idle (%d ticks)", idle_ticks)
                time.sleep(poll_interval_seconds)
                continue

            idle_ticks = 0
            logger.info("Executing stage run_id=%s stage=%s retry=%d", stage.run_id, stage.stage_name, stage.retry_count)
            try:
                execute_stage(session, stage, settings)
                logger.info("Stage done   run_id=%s stage=%s", stage.run_id, stage.stage_name)
            except Exception:
                # execute_stage has its own catch-all, but guard against any leak.
                logger.exception("Unhandled exception from execute_stage run_id=%s stage=%s", stage.run_id, stage.stage_name)
        except Exception:
            logger.exception("Worker loop error — continuing after 5s")
            time.sleep(5)
        finally:
            try:
                session.close()
            except Exception:
                pass


if __name__ == "__main__":
    run_worker_loop()
