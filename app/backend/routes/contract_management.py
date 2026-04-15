"""
Contract management routes.

POST /api/contracts                   — create a named contract
GET  /api/contracts                   — list all contracts for a tenant
GET  /api/contracts/{contract_id}     — get contract with all versions + run state
POST /api/contracts/{id}/versions     — upload a new version (main or branch)
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.backend.core.config import SettingsDep
from app.backend.db.models import ContractRecord, ContractVersionRecord, RunRecord
from app.backend.db.session import DbSession
from app.backend.services.run_service import create_run

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ContractCreateRequest(BaseModel):
    name: str
    tenant_id: str = "demo-tenant"


class VersionInfo(BaseModel):
    id: int
    label: str
    branch_name: str | None
    run_id: str | None
    run_state: str | None
    risk_level: str | None
    filename: str | None
    created_at: str


class ContractSummary(BaseModel):
    id: int
    name: str
    tenant_id: str
    latest_label: str | None
    latest_risk: str | None
    latest_run_state: str | None
    version_count: int
    created_at: str
    updated_at: str


class ContractDetail(BaseModel):
    id: int
    name: str
    tenant_id: str
    versions: list[VersionInfo]
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _risk_from_verdict(verdict_payload: dict | None) -> str | None:
    if not verdict_payload:
        return None
    return verdict_payload.get("overall_risk_level")


def _version_info(cv: ContractVersionRecord) -> VersionInfo:
    run: RunRecord | None = cv.run
    return VersionInfo(
        id=cv.id,
        label=cv.label,
        branch_name=cv.branch_name,
        run_id=cv.run_id,
        run_state=run.status if run else None,
        risk_level=_risk_from_verdict(run.verdict_payload if run else None),
        filename=run.original_filename if run else None,
        created_at=cv.created_at.isoformat(),
    )


def _next_main_version(session, contract_id: int) -> int:
    result = session.execute(
        select(func.max(ContractVersionRecord.main_version)).where(
            ContractVersionRecord.contract_id == contract_id,
            ContractVersionRecord.branch_letter.is_(None),
        )
    ).scalar()
    return (result or 0) + 1


def _next_branch_letter(session, contract_id: int, main_version: int) -> str:
    count = session.execute(
        select(func.count(ContractVersionRecord.id)).where(
            ContractVersionRecord.contract_id == contract_id,
            ContractVersionRecord.main_version == main_version,
            ContractVersionRecord.branch_letter.isnot(None),
        )
    ).scalar()
    return chr(ord("a") + (count or 0))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ContractSummary)
async def create_contract(payload: ContractCreateRequest, db: DbSession) -> ContractSummary:
    now = datetime.utcnow()
    contract = ContractRecord(name=payload.name, tenant_id=payload.tenant_id, created_at=now, updated_at=now)
    db.add(contract)
    await db.flush()
    await db.refresh(contract)
    return ContractSummary(
        id=contract.id,
        name=contract.name,
        tenant_id=contract.tenant_id,
        latest_label=None,
        latest_risk=None,
        latest_run_state=None,
        version_count=0,
        created_at=contract.created_at.isoformat(),
        updated_at=contract.updated_at.isoformat(),
    )


@router.get("", response_model=list[ContractSummary])
async def list_contracts(db: DbSession, tenant_id: str = "demo-tenant") -> list[ContractSummary]:
    result = await db.execute(
        select(ContractRecord)
        .where(ContractRecord.tenant_id == tenant_id)
        .order_by(ContractRecord.updated_at.desc())
    )
    contracts = result.scalars().all()

    summaries = []
    for c in contracts:
        versions_result = await db.execute(
            select(ContractVersionRecord)
            .where(ContractVersionRecord.contract_id == c.id)
            .order_by(ContractVersionRecord.id.desc())
        )
        versions = versions_result.scalars().all()

        latest = versions[0] if versions else None
        latest_run = None
        if latest and latest.run_id:
            run_result = await db.execute(select(RunRecord).where(RunRecord.id == latest.run_id))
            latest_run = run_result.scalar_one_or_none()

        summaries.append(
            ContractSummary(
                id=c.id,
                name=c.name,
                tenant_id=c.tenant_id,
                latest_label=latest.label if latest else None,
                latest_risk=_risk_from_verdict(latest_run.verdict_payload if latest_run else None),
                latest_run_state=latest_run.status if latest_run else None,
                version_count=len(versions),
                created_at=c.created_at.isoformat(),
                updated_at=c.updated_at.isoformat(),
            )
        )
    return summaries


@router.get("/{contract_id}", response_model=ContractDetail)
async def get_contract(contract_id: int, db: DbSession) -> ContractDetail:
    result = await db.execute(select(ContractRecord).where(ContractRecord.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    versions_result = await db.execute(
        select(ContractVersionRecord)
        .where(ContractVersionRecord.contract_id == contract_id)
        .order_by(ContractVersionRecord.id.asc())
    )
    versions = versions_result.scalars().all()

    version_infos = []
    for cv in versions:
        run = None
        if cv.run_id:
            run_result = await db.execute(select(RunRecord).where(RunRecord.id == cv.run_id))
            run = run_result.scalar_one_or_none()
        cv.run = run
        version_infos.append(_version_info(cv))

    return ContractDetail(
        id=contract.id,
        name=contract.name,
        tenant_id=contract.tenant_id,
        versions=version_infos,
        created_at=contract.created_at.isoformat(),
        updated_at=contract.updated_at.isoformat(),
    )


@router.post("/{contract_id}/versions", status_code=status.HTTP_202_ACCEPTED)
async def add_version(
    contract_id: int,
    db: DbSession,
    settings: SettingsDep,
    file: UploadFile = File(...),
    branch_from: int | None = Form(None),
    branch_name: str | None = Form(None),
    tenant_id: str = Form("demo-tenant"),
    policy_family_id: str = Form("default"),
    policy_version: int = Form(1),
    jurisdiction: str = Form("US"),
    regime: str = Form("general"),
    effective_date: str | None = Form(None),
) -> dict:
    result = await db.execute(select(ContractRecord).where(ContractRecord.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Compute version label
    from sqlalchemy import func as sa_func
    from sqlalchemy.orm import Session

    if branch_from is not None:
        # Branch off an existing main version
        branch_letter = _next_branch_letter(db.sync_session if hasattr(db, 'sync_session') else db, contract_id, branch_from)
        main_version = branch_from
        label = f"v{main_version}{branch_letter}"
    else:
        # New main version
        main_version_result = await db.execute(
            select(func.max(ContractVersionRecord.main_version)).where(
                ContractVersionRecord.contract_id == contract_id,
                ContractVersionRecord.branch_letter.is_(None),
            )
        )
        max_v = main_version_result.scalar()
        main_version = (max_v or 0) + 1
        branch_letter = None
        label = f"v{main_version}"

    # If branching, get branch_letter properly via async query
    if branch_from is not None:
        count_result = await db.execute(
            select(func.count(ContractVersionRecord.id)).where(
                ContractVersionRecord.contract_id == contract_id,
                ContractVersionRecord.main_version == branch_from,
                ContractVersionRecord.branch_letter.isnot(None),
            )
        )
        count = count_result.scalar() or 0
        branch_letter = chr(ord("a") + count)
        label = f"v{branch_from}{branch_letter}"

    # Create run first
    run_response = await create_run(
        db,
        settings,
        file=file,
        tenant_id=tenant_id,
        policy_family_id=policy_family_id,
        policy_version=policy_version,
        jurisdiction=jurisdiction,
        regime=regime,
        effective_date=effective_date,
    )

    # Create contract version record
    now = datetime.utcnow()
    cv = ContractVersionRecord(
        contract_id=contract_id,
        run_id=run_response.run_id,
        main_version=main_version,
        branch_letter=branch_letter,
        branch_name=branch_name or None,
        label=label,
        created_at=now,
    )
    db.add(cv)

    # Update contract updated_at
    contract.updated_at = now

    await db.flush()

    return {
        "run_id": run_response.run_id,
        "label": label,
        "contract_id": contract_id,
        "version_id": cv.id,
    }
