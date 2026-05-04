"""
Harvey policy lineage repository.

Resolves the active policy version and its lineage for a given
(tenant, policy_family_id, policy_version_number) tuple.
"""

from __future__ import annotations

import logging

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.backend.db.models import PolicyVersionRecord

logger = logging.getLogger(__name__)


class MissingLineageError(Exception):
    """Raised when no policy version can be resolved for the requested lineage key."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.blocked_reason = message


def resolve_policy_lineage(
    tenant_id: str,
    policy_family_id: str,
    policy_version_number: int,
) -> dict:
    """
    Return the policy version record as a dict (including rules_payload).

    Looks up the exact (tenant, family, version) row. If not found and
    policy_family_id is empty / version is 0, returns an empty dict rather
    than raising — the caller decides whether to block the run.

    Raises:
        MissingLineageError: When a non-empty policy_family_id was requested
            but no matching row exists.
    """
    if not policy_family_id or policy_version_number == 0:
        return {}

    from app.backend.db.session import get_sync_session_factory

    session_factory = get_sync_session_factory()
    with session_factory() as session:
        row: PolicyVersionRecord | None = session.scalars(
            select(PolicyVersionRecord).where(
                PolicyVersionRecord.tenant_id == tenant_id,
                PolicyVersionRecord.policy_family_id == policy_family_id,
                PolicyVersionRecord.version_number == policy_version_number,
            )
        ).first()

    if row is None:
        raise MissingLineageError(
            f"No policy version found for family='{policy_family_id}' "
            f"version={policy_version_number} tenant='{tenant_id}'"
        )

    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "policy_family_id": row.policy_family_id,
        "version_number": row.version_number,
        "policy_name": row.policy_name,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "rules_payload": row.rules_payload or {},
        "parent_version_number": row.parent_version_number,
        "change_summary": row.change_summary,
    }


def load_prior_policy_versions(
    tenant_id: str,
    policy_family_id: str,
    policy_version_number: int,
) -> list[dict]:
    """
    Return all policy versions in the same family with version_number < *policy_version_number*.

    Used by Harvey to compare the current contract against what changed across versions.
    Returns an empty list when policy_family_id is empty or no prior versions exist.
    """
    if not policy_family_id or policy_version_number <= 1:
        return []

    from app.backend.db.session import get_sync_session_factory

    session_factory = get_sync_session_factory()
    with session_factory() as session:
        rows: list[PolicyVersionRecord] = session.scalars(
            select(PolicyVersionRecord)
            .where(
                PolicyVersionRecord.tenant_id == tenant_id,
                PolicyVersionRecord.policy_family_id == policy_family_id,
                PolicyVersionRecord.version_number < policy_version_number,
            )
            .order_by(PolicyVersionRecord.version_number.desc())
        ).all()

    return [
        {
            "id": row.id,
            "version_number": row.version_number,
            "policy_name": row.policy_name,
            "effective_from": row.effective_from.isoformat() if row.effective_from else None,
            "effective_to": row.effective_to.isoformat() if row.effective_to else None,
            "rules_payload": row.rules_payload or {},
            "change_summary": row.change_summary,
        }
        for row in rows
    ]
