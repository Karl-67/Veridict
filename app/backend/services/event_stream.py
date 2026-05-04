"""
Append-only SSE event stream for pipeline runs.

Sync path (append_run_event):      used by the worker's state_machine
Async path (async_append_run_event): used by FastAPI route handlers in run_service
Read path (list_run_events, stream_run_events): used by the /runs/{id}/events routes
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.backend.db.models import RunEventRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sync write (worker / state_machine)
# ---------------------------------------------------------------------------


def append_run_event(
    session: Session,
    run_id: str,
    event_type: str,
    data: dict,
) -> None:
    """Append one event to run_events inside the caller's sync transaction."""
    try:
        next_seq = (
            session.execute(
                select(RunEventRecord.sequence_number)
                .where(RunEventRecord.run_id == run_id)
                .order_by(RunEventRecord.sequence_number.desc())
                .limit(1)
            ).scalar()
            or 0
        ) + 1
        record = RunEventRecord(
            run_id=run_id,
            event_type=event_type,
            payload=data,
            sequence_number=next_seq,
        )
        session.add(record)
        # flush so the row is visible within the same transaction; caller commits
        session.flush()
    except Exception as exc:
        logger.warning("append_run_event failed (run=%s, type=%s): %s", run_id, event_type, exc)


# ---------------------------------------------------------------------------
# Async write (FastAPI route handlers)
# ---------------------------------------------------------------------------


async def async_append_run_event(
    session: AsyncSession,
    run_id: str,
    event_type: str,
    data: dict,
) -> None:
    """Append one event to run_events inside the caller's async transaction."""
    try:
        result = await session.execute(
            select(RunEventRecord.sequence_number)
            .where(RunEventRecord.run_id == run_id)
            .order_by(RunEventRecord.sequence_number.desc())
            .limit(1)
        )
        last_seq = result.scalar() or 0
        record = RunEventRecord(
            run_id=run_id,
            event_type=event_type,
            payload=data,
            sequence_number=last_seq + 1,
        )
        session.add(record)
        await session.flush()
    except Exception as exc:
        logger.warning("async_append_run_event failed (run=%s, type=%s): %s", run_id, event_type, exc)


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------


async def list_run_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    *,
    after_sequence: int = 0,
) -> list[dict]:
    """Return all events for *run_id* with sequence_number > *after_sequence*."""
    async with session_factory() as session:
        result = await session.execute(
            select(RunEventRecord)
            .where(
                RunEventRecord.run_id == run_id,
                RunEventRecord.sequence_number > after_sequence,
            )
            .order_by(RunEventRecord.sequence_number.asc())
        )
        records = result.scalars().all()
    return [
        {
            "id": r.id,
            "run_id": r.run_id,
            "event_type": r.event_type,
            "payload": r.payload,
            "sequence_number": r.sequence_number,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


async def _poll_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    after_sequence: int,
    poll_interval: float = 1.5,
    max_polls: int = 400,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted lines by polling the DB for new events."""
    seq = after_sequence
    polls = 0
    while polls < max_polls:
        events = await list_run_events(session_factory, run_id, after_sequence=seq)
        for ev in events:
            seq = ev["sequence_number"]
            yield f"data: {json.dumps(ev)}\n\n"
            if ev["event_type"] in ("run_finalized", "stage_failed"):
                return
        polls += 1
        await asyncio.sleep(poll_interval)


def stream_run_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    *,
    after_sequence: int = 0,
) -> AsyncGenerator[str, None]:
    """Return an async generator of SSE-formatted event strings for use with EventSourceResponse."""
    return _poll_events(session_factory, run_id, after_sequence)
