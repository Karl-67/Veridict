"""
Worker process entrypoint.
"""

from __future__ import annotations

import os
import time
from uuid import uuid4

from app.backend.core.config import get_settings
from app.backend.db.session import get_sync_session_factory
from app.backend.orchestration.state_machine import claim_next_stage, execute_stage


def run_worker_loop(poll_interval_seconds: float = 1.0) -> None:
    settings = get_settings()
    worker_id = os.getenv("VERDICT_WORKER_ID", f"worker-{uuid4().hex[:8]}")
    session_factory = get_sync_session_factory()

    while True:
        session = session_factory()
        try:
            stage = claim_next_stage(session, settings, worker_id)
            if stage is None:
                session.close()
                time.sleep(poll_interval_seconds)
                continue
            execute_stage(session, stage, settings)
        finally:
            session.close()


if __name__ == "__main__":
    run_worker_loop()
