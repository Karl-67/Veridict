"""
Kira compliance corpus repository.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Generator

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.backend.db.models import ComplianceCorpusRecord
from app.backend.db.session import get_sync_session_factory


class MissingComplianceScopeError(Exception):
    blocked_reason = "needs_scope_review"


@contextmanager
def _session() -> Generator[Session, None, None]:
    factory = get_sync_session_factory()
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _record_to_dict(record: ComplianceCorpusRecord) -> dict:
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "corpus_type": record.corpus_type,
        "jurisdiction": record.jurisdiction,
        "regime": record.regime,
        "effective_from": record.effective_from.isoformat(),
        "effective_to": record.effective_to.isoformat() if record.effective_to else None,
        "rules_payload": record.rules_payload,
        "source_url": record.source_url,
        "corpus_name": record.corpus_name,
    }


def _load_corpora(tenant_id: str, corpus_type: str, jurisdiction: str, regime: str, effective_date: date | None) -> list[dict]:
    effective_date = effective_date or date.today()
    with _session() as session:
        stmt = (
            select(ComplianceCorpusRecord)
            .where(
                ComplianceCorpusRecord.tenant_id == tenant_id,
                ComplianceCorpusRecord.corpus_type == corpus_type,
                ComplianceCorpusRecord.jurisdiction == jurisdiction,
                ComplianceCorpusRecord.regime == regime,
                ComplianceCorpusRecord.effective_from <= effective_date,
                or_(ComplianceCorpusRecord.effective_to.is_(None), ComplianceCorpusRecord.effective_to >= effective_date),
            )
            .order_by(ComplianceCorpusRecord.effective_from.desc())
        )
        return [_record_to_dict(record) for record in session.scalars(stmt).all()]


def load_internal_playbook_rules(tenant_id: str, jurisdiction: str, regime: str, effective_date: date | None) -> list[dict]:
    return _load_corpora(tenant_id, "internal_playbook", jurisdiction, regime, effective_date)


def load_external_compliance_rules(tenant_id: str, jurisdiction: str, regime: str, effective_date: date | None) -> list[dict]:
    return _load_corpora(tenant_id, "external", jurisdiction, regime, effective_date)


def resolve_applicable_corpora(tenant_id: str, jurisdiction: str | None, regime: str | None, effective_date: date | None = None) -> dict:
    if not jurisdiction or not regime:
        raise MissingComplianceScopeError("Jurisdiction and regime are required to resolve Kira corpora.")
    internal = load_internal_playbook_rules(tenant_id, jurisdiction, regime, effective_date)
    external = load_external_compliance_rules(tenant_id, jurisdiction, regime, effective_date)
    return {
        "tenant_id": tenant_id,
        "jurisdiction": jurisdiction,
        "regime": regime,
        "effective_date": (effective_date or date.today()).isoformat(),
        "internal_rules": [record["rules_payload"] for record in internal],
        "external_rules": [record["rules_payload"] for record in external],
        "corpora_records": {"internal": internal, "external": external},
    }
