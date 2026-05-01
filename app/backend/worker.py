"""
Worker process entrypoint.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from app.backend.core.config import get_settings
from app.backend.db.models import RagIngestionJob
from app.backend.db.session import get_sync_session_factory
from app.backend.orchestration.state_machine import claim_next_stage, execute_stage
from app.backend.services.metrics import queue_age_seconds
from app.backend.services.rag_ingestion import RagIngestionService


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
    session_factory = get_sync_session_factory()

    while True:
        session = session_factory()
        try:
            stage = claim_next_stage(session, settings, worker_id)
            if stage is None:
                rag_job = claim_next_rag_ingestion(session)
                if rag_job is not None:
                    RagIngestionService(session, settings).ingest_document(rag_job.id)
                    session.close()
                    continue
                session.close()
                time.sleep(poll_interval_seconds)
                continue
            execute_stage(session, stage, settings)
        finally:
            session.close()


if __name__ == "__main__":
    run_worker_loop()
