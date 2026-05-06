"""
Contract management routes — workspace-scoped.

POST /api/contracts                   — create a contract in a workspace
GET  /api/contracts                   — list contracts visible to the caller
GET  /api/contracts/{contract_id}     — get contract + versions
POST /api/contracts/{id}/versions     — upload a new version
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.backend.core.config import SettingsDep
from app.backend.db.models import ContractRecord, ContractVersionRecord, FindingRecord, RunRecord, WorkspaceMemberRecord, WorkspaceRecord
from app.backend.db.session import DbSession
from app.backend.services.auth_service import require_auth
from app.backend.services.run_service import create_run

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contracts", tags=["contracts"])
history_router = APIRouter(prefix="/api/history", tags=["history"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ContractCreateRequest(BaseModel):
    name: str
    workspace_id: str


class HistoryEntry(BaseModel):
    run_id: str
    contract_id: int
    contract_name: str
    workspace_id: str | None
    workspace_name: str | None
    version_label: str
    filename: str | None
    state: str
    risk_level: str | None
    human_action: str | None
    created_at: str
    updated_at: str


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
    workspace_id: str | None
    workspace_name: str | None
    latest_label: str | None
    latest_risk: str | None
    latest_run_state: str | None
    latest_run_id: str | None
    version_count: int
    created_at: str
    updated_at: str


class ContractDetail(BaseModel):
    id: int
    name: str
    workspace_id: str | None
    workspace_name: str | None
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


def _risk_from_findings(findings: list) -> str | None:
    if not findings:
        return None
    severity_order = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    top = max((f.severity for f in findings), key=lambda s: severity_order.get(s, 0))
    return "high" if top in ("critical", "high") else top


def _version_info(cv: ContractVersionRecord, precomputed_risk: str | None = None) -> VersionInfo:
    run: RunRecord | None = cv.run
    risk = _risk_from_verdict(run.verdict_payload if run else None) or precomputed_risk
    return VersionInfo(
        id=cv.id,
        label=cv.label,
        branch_name=cv.branch_name,
        run_id=cv.run_id,
        run_state=run.status if run else None,
        risk_level=risk,
        filename=run.original_filename if run else None,
        created_at=cv.created_at.isoformat(),
    )


async def _assert_workspace_access(db: DbSession, workspace_id: str, token: dict) -> WorkspaceRecord:
    """Raise 403 if the caller is not an org_admin and not a member of the workspace."""
    ws = await db.get(WorkspaceRecord, workspace_id)
    if not ws:
        log.warning("workspace_not_found user=%s org=%s workspace_id=%s", token.get("sub"), token.get("org_id"), workspace_id)
        raise HTTPException(status_code=404, detail="Workspace not found")
    if token.get("org_role") == "org_admin":
        return ws
    member = (await db.execute(
        select(WorkspaceMemberRecord).where(
            WorkspaceMemberRecord.workspace_id == workspace_id,
            WorkspaceMemberRecord.user_id == token["sub"],
        )
    )).scalar_one_or_none()
    if not member:
        log.warning("workspace_access_denied user=%s org=%s workspace_id=%s", token.get("sub"), token.get("org_id"), workspace_id)
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    return ws


async def _build_summary(db: DbSession, c: ContractRecord) -> ContractSummary:
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
    ws_name: str | None = None
    if c.workspace_id:
        ws = await db.get(WorkspaceRecord, c.workspace_id)
        ws_name = ws.name if ws else None
    risk = _risk_from_verdict(latest_run.verdict_payload if latest_run else None)
    if not risk and latest_run and latest_run.status in ("awaiting_human_review", "under_review"):
        findings_result = await db.execute(
            select(FindingRecord).where(FindingRecord.run_id == latest_run.id)
        )
        risk = _risk_from_findings(findings_result.scalars().all())

    return ContractSummary(
        id=c.id,
        name=c.name,
        workspace_id=c.workspace_id,
        workspace_name=ws_name,
        latest_label=latest.label if latest else None,
        latest_risk=risk,
        latest_run_state=latest_run.status if latest_run else None,
        latest_run_id=latest_run.id if latest_run else None,
        version_count=len(versions),
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, response_model=ContractSummary)
async def create_contract(
    payload: ContractCreateRequest,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> ContractSummary:
    ws = await _assert_workspace_access(db, payload.workspace_id, token)
    now = datetime.utcnow()
    contract = ContractRecord(
        name=payload.name,
        tenant_id=str(token.get("org_id") or token.get("sub")),
        org_id=token.get("org_id"),
        workspace_id=payload.workspace_id,
        created_at=now,
        updated_at=now,
    )
    db.add(contract)
    await db.flush()
    await db.refresh(contract)
    return ContractSummary(
        id=contract.id,
        name=contract.name,
        workspace_id=contract.workspace_id,
        workspace_name=ws.name,
        latest_label=None,
        latest_risk=None,
        latest_run_state=None,
        latest_run_id=None,
        version_count=0,
        created_at=contract.created_at.isoformat(),
        updated_at=contract.updated_at.isoformat(),
    )


@router.get("", response_model=list[ContractSummary])
async def list_contracts(
    db: DbSession,
    workspace_id: str | None = None,
    token: dict = Depends(require_auth),
) -> list[ContractSummary]:
    org_id = token.get("org_id")
    is_admin = token.get("org_role") == "org_admin"

    if workspace_id:
        await _assert_workspace_access(db, workspace_id, token)
        q = select(ContractRecord).where(ContractRecord.workspace_id == workspace_id)
    elif is_admin:
        # Org admin sees all contracts in the org
        q = select(ContractRecord).where(ContractRecord.org_id == org_id)
    else:
        # Member sees only contracts in their workspaces
        member_ws = (await db.execute(
            select(WorkspaceMemberRecord.workspace_id).where(WorkspaceMemberRecord.user_id == token["sub"])
        )).scalars().all()
        q = select(ContractRecord).where(ContractRecord.workspace_id.in_(member_ws))

    result = await db.execute(q.order_by(ContractRecord.updated_at.desc()))
    contracts = result.scalars().all()
    return [await _build_summary(db, c) for c in contracts]


@router.get("/{contract_id}", response_model=ContractDetail)
async def get_contract(
    contract_id: int,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> ContractDetail:
    result = await db.execute(select(ContractRecord).where(ContractRecord.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        log.warning(
            "contract_not_found route=GET user=%s org=%s contract_id=%s",
            token.get("sub"), token.get("org_id"), contract_id,
        )
        raise HTTPException(status_code=404, detail="Contract not found")

    if contract.workspace_id:
        ws = await _assert_workspace_access(db, contract.workspace_id, token)
        ws_name = ws.name
    else:
        ws_name = None

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
        precomputed_risk = None
        if run and not run.verdict_payload and run.status in ("awaiting_human_review", "under_review"):
            findings_result = await db.execute(
                select(FindingRecord).where(FindingRecord.run_id == run.id)
            )
            precomputed_risk = _risk_from_findings(findings_result.scalars().all())
        version_infos.append(_version_info(cv, precomputed_risk))

    return ContractDetail(
        id=contract.id,
        name=contract.name,
        workspace_id=contract.workspace_id,
        workspace_name=ws_name,
        versions=version_infos,
        created_at=contract.created_at.isoformat(),
        updated_at=contract.updated_at.isoformat(),
    )


@router.post("/{contract_id}/versions", status_code=status.HTTP_202_ACCEPTED)
async def add_version(
    contract_id: int,
    db: DbSession,
    settings: SettingsDep,
    token: dict = Depends(require_auth),
    file: UploadFile = File(...),
    branch_from: int | None = Form(None),
    branch_name: str | None = Form(None),
    policy_family_id: str = Form("default"),
    policy_version: int = Form(1),
    jurisdiction: str = Form("US"),
    regime: str = Form("general"),
    effective_date: str | None = Form(None),
) -> dict:
    result = await db.execute(select(ContractRecord).where(ContractRecord.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        log.warning(
            "contract_not_found route=POST_version user=%s org=%s contract_id=%s file=%s",
            token.get("sub"), token.get("org_id"), contract_id, file.filename,
        )
        raise HTTPException(status_code=404, detail="Contract not found")

    if contract.workspace_id:
        await _assert_workspace_access(db, contract.workspace_id, token)

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
        main_version = branch_from
        label = f"v{branch_from}{branch_letter}"
    else:
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

    run_response = await create_run(
        db, settings,
        file=file,
        tenant_id=str(token.get("org_id") or token.get("sub")),
        policy_family_id=policy_family_id,
        policy_version=policy_version,
        jurisdiction=jurisdiction,
        regime=regime,
        effective_date=effective_date,
    )

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
    contract.updated_at = now
    await db.flush()

    return {"run_id": run_response.run_id, "label": label, "contract_id": contract_id, "version_id": cv.id}


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@history_router.get("", response_model=list[HistoryEntry])
async def list_history(
    db: DbSession,
    limit: int = 100,
    token: dict = Depends(require_auth),
) -> list[HistoryEntry]:
    """Return a flat chronological list of all runs visible to the caller."""
    org_id = token.get("org_id")
    is_admin = token.get("org_role") == "org_admin"

    if is_admin:
        ws_ids_result = await db.execute(
            select(WorkspaceRecord.id).where(WorkspaceRecord.org_id == org_id)
        )
        visible_ws_ids = ws_ids_result.scalars().all()
    else:
        member_ws_result = await db.execute(
            select(WorkspaceMemberRecord.workspace_id).where(
                WorkspaceMemberRecord.user_id == token["sub"]
            )
        )
        visible_ws_ids = member_ws_result.scalars().all()

    if not visible_ws_ids:
        return []

    contracts_result = await db.execute(
        select(ContractRecord).where(ContractRecord.workspace_id.in_(visible_ws_ids))
    )
    contract_map = {c.id: c for c in contracts_result.scalars().all()}
    if not contract_map:
        return []

    ws_ids_needed = {c.workspace_id for c in contract_map.values() if c.workspace_id}
    ws_map: dict[str, WorkspaceRecord] = {}
    if ws_ids_needed:
        ws_result = await db.execute(
            select(WorkspaceRecord).where(WorkspaceRecord.id.in_(ws_ids_needed))
        )
        ws_map = {ws.id: ws for ws in ws_result.scalars().all()}

    versions_result = await db.execute(
        select(ContractVersionRecord)
        .where(
            ContractVersionRecord.contract_id.in_(list(contract_map.keys())),
            ContractVersionRecord.run_id.isnot(None),
        )
    )
    versions = versions_result.scalars().all()
    if not versions:
        return []

    run_ids = [cv.run_id for cv in versions]
    runs_result = await db.execute(
        select(RunRecord).where(RunRecord.id.in_(run_ids))
    )
    run_map = {r.id: r for r in runs_result.scalars().all()}

    entries: list[HistoryEntry] = []
    for cv in versions:
        run = run_map.get(cv.run_id)
        if not run:
            continue
        contract = contract_map.get(cv.contract_id)
        if not contract:
            continue
        ws = ws_map.get(contract.workspace_id) if contract.workspace_id else None

        risk = _risk_from_verdict(run.verdict_payload)
        human_action: str | None = None
        if run.verdict_payload:
            human_action = run.verdict_payload.get("human_action")

        entries.append(HistoryEntry(
            run_id=run.id,
            contract_id=contract.id,
            contract_name=contract.name,
            workspace_id=contract.workspace_id,
            workspace_name=ws.name if ws else None,
            version_label=cv.label,
            filename=run.original_filename,
            state=run.status,
            risk_level=risk,
            human_action=human_action,
            created_at=run.created_at.isoformat(),
            updated_at=run.updated_at.isoformat(),
        ))

    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries[:limit]
