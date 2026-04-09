"""
Persisted run event stream and SSE adapter.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.backend.db.models import RunEventRecord
from app.backend.models.schemas import RunEvent


def append_run_event(session: Session, run_id: str, event_type: str, payload: dict) -> RunEventRecord:
    """Sync version — used by the worker via a psycopg2 Session."""
    current_sequence = session.scalar(
        select(func.max(RunEventRecord.sequence_number)).where(RunEventRecord.run_id == run_id)
    )
    event = RunEventRecord(
        run_id=run_id,
        event_type=event_type,
        payload=payload,
        sequence_number=(current_sequence or 0) + 1,
    )
    session.add(event)
    session.flush()
    return event


async def async_append_run_event(session: AsyncSession, run_id: str, event_type: str, payload: dict) -> RunEventRecord:
    """Async version — used by FastAPI request handlers via an asyncpg AsyncSession."""
    current_sequence = await session.scalar(
        select(func.max(RunEventRecord.sequence_number)).where(RunEventRecord.run_id == run_id)
    )
    event = RunEventRecord(
        run_id=run_id,
        event_type=event_type,
        payload=payload,
        sequence_number=(current_sequence or 0) + 1,
    )
    session.add(event)
    await session.flush()
    return event


def _to_schema(record: RunEventRecord) -> RunEvent:
    return RunEvent(
        event_id=str(record.id),
        run_id=record.run_id,
        event_type=record.event_type,  # type: ignore[arg-type]
        payload=record.payload,
        emitted_at=record.created_at or datetime.utcnow(),
        sequence=record.sequence_number,
    )


async def list_run_events(session_factory: async_sessionmaker, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
    async with session_factory() as session:
        result = await session.execute(
            select(RunEventRecord)
            .where(RunEventRecord.run_id == run_id, RunEventRecord.sequence_number > after_sequence)
            .order_by(RunEventRecord.sequence_number.asc())
        )
        return [_to_schema(record) for record in result.scalars().all()]


async def stream_run_events(session_factory: async_sessionmaker, run_id: str, after_sequence: int = 0):
    cursor = after_sequence
    terminal_event_types = {"run_finalized", "human_rejected", "stage_failed"}

    while True:
        events = await list_run_events(session_factory, run_id, after_sequence=cursor)
        if events:
            for event in events:
                cursor = event.sequence
                yield {
                    "id": str(event.sequence),
                    "event": event.event_type,
                    "data": event.model_dump_json(),
                }
                if event.event_type in terminal_event_types:
                    return
        await asyncio.sleep(1.0)
