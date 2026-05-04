"""
Kira compliance corpus repository.

Resolves the applicable internal and external rule sets for a given
(tenant, jurisdiction, regime, effective_date) tuple.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.backend.db.models import ComplianceCorpusRecord

logger = logging.getLogger(__name__)


class MissingComplianceScopeError(Exception):
    """Raised when no corpora can be resolved for the requested scope."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.blocked_reason = message


def resolve_applicable_corpora(
    tenant_id: str,
    jurisdiction: str | None,
    regime: str | None,
    effective_date: date | None,
) -> dict:
    """
    Return a dict with keys: jurisdiction, regime, internal_rules, external_rules.

    Queries the compliance_corpora table for records that cover the given
    (tenant, jurisdiction, regime) and are effective on *effective_date*.
    If effective_date is None, rows with no effective_to bound are preferred.

    Does NOT raise MissingComplianceScopeError when no rows are found —
    the caller (state_machine) catches that separately and falls back to an
    empty context so that runs without corpora can still proceed.
    """
    # Lazy import to avoid circular deps at module load time
    from app.backend.db.session import get_sync_session_factory

    jur = jurisdiction or ""
    reg = regime or ""
    eff = effective_date or date.today()

    session_factory = get_sync_session_factory()
    with session_factory() as session:
        rows: list[ComplianceCorpusRecord] = session.scalars(
            select(ComplianceCorpusRecord)
            .where(
                ComplianceCorpusRecord.tenant_id == tenant_id,
                ComplianceCorpusRecord.jurisdiction == jur,
                ComplianceCorpusRecord.regime == reg,
                ComplianceCorpusRecord.effective_from <= eff,
                or_(
                    ComplianceCorpusRecord.effective_to.is_(None),
                    ComplianceCorpusRecord.effective_to >= eff,
                ),
            )
            .order_by(ComplianceCorpusRecord.effective_from.desc())
        ).all()

    internal_rules: list[dict] = []
    external_rules: list[dict] = []

    for row in rows:
        rules = row.rules_payload
        if not isinstance(rules, list):
            rules = [rules] if rules else []
        if row.corpus_type == "internal_playbook":
            internal_rules.extend(rules)
        else:
            external_rules.extend(rules)

    return {
        "jurisdiction": jur,
        "regime": reg,
        "internal_rules": internal_rules,
        "external_rules": external_rules,
    }
