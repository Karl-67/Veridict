"""
Harvey policy lineage service.

Implements the `policy-lineage-and-corpora` shared dependency for the Harvey branch.
Keyed by `tenant_id + policy_family_id + version_number`.

Blocked-state behaviour
-----------------------
When the requested authoritative lineage record is absent from the database
``resolve_policy_lineage`` raises ``MissingLineageError`` with
``blocked_reason = "blocked_missing_lineage"``.  The caller (state_machine.py)
is responsible for persisting that reason on the run and emitting the
corresponding event.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.db.models import PolicyVersionRecord
from app.backend.db.session import get_sync_session_factory


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MissingLineageError(Exception):
    """Raised when no authoritative lineage record exists for the given keys.

    The ``blocked_reason`` attribute contains the canonical string that the
    state machine must write to ``RunRecord.blocked_reason``.
    """

    blocked_reason: str = "blocked_missing_lineage"

    def __init__(
        self,
        tenant_id: str,
        policy_family_id: str,
        version_number: int,
    ) -> None:
        self.tenant_id = tenant_id
        self.policy_family_id = policy_family_id
        self.version_number = version_number
        super().__init__(
            f"No policy lineage found for tenant={tenant_id!r}, "
            f"family={policy_family_id!r}, version={version_number}. "
            f"Run will be blocked ({self.blocked_reason})."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@contextmanager
def _session() -> Generator[Session, None, None]:
    factory = get_sync_session_factory()
    session: Session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _record_to_dict(record: PolicyVersionRecord) -> dict:
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "policy_family_id": record.policy_family_id,
        "version_number": record.version_number,
        "policy_name": record.policy_name,
        "effective_from": record.effective_from.isoformat() if record.effective_from else None,
        "effective_to": record.effective_to.isoformat() if record.effective_to else None,
        "rules_payload": record.rules_payload,
        "parent_version_number": record.parent_version_number,
        "change_summary": record.change_summary,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_policy_lineage(
    tenant_id: str,
    policy_family_id: str,
    version_number: int,
) -> dict:
    """Return the authoritative Harvey lineage record for a specific version.

    The return dict mirrors the structure of ``PolicyVersionRecord`` including
    the full ``rules_payload``.

    Raises
    ------
    MissingLineageError
        When no matching record exists.  The caller must catch this, write
        ``blocked_reason = "blocked_missing_lineage"`` to the run, and emit a
        ``blocked_missing_lineage`` event before surfacing the error upstream.
    """
    with _session() as session:
        stmt = (
            select(PolicyVersionRecord)
            .where(
                PolicyVersionRecord.tenant_id == tenant_id,
                PolicyVersionRecord.policy_family_id == policy_family_id,
                PolicyVersionRecord.version_number == version_number,
            )
            .limit(1)
        )
        record: PolicyVersionRecord | None = session.scalars(stmt).first()

    if record is None:
        raise MissingLineageError(tenant_id, policy_family_id, version_number)

    return _record_to_dict(record)


def load_prior_policy_versions(
    tenant_id: str,
    policy_family_id: str,
    version_number: int,
) -> list[dict]:
    """Return all policy versions for the same family that predate ``version_number``.

    Results are ordered ascending by ``version_number`` so callers can walk the
    lineage chain chronologically.  An empty list is returned (not an error) when
    there are no prior versions — version 1 of a new policy family is valid.

    Parameters
    ----------
    tenant_id:
        Tenant owning the policy family.
    policy_family_id:
        Harvey policy family identifier.
    version_number:
        The *current* version.  Only versions strictly less than this are returned.
    """
    with _session() as session:
        stmt = (
            select(PolicyVersionRecord)
            .where(
                PolicyVersionRecord.tenant_id == tenant_id,
                PolicyVersionRecord.policy_family_id == policy_family_id,
                PolicyVersionRecord.version_number < version_number,
            )
            .order_by(PolicyVersionRecord.version_number.asc())
        )
        records = session.scalars(stmt).all()

    return [_record_to_dict(r) for r in records]
