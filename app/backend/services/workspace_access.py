from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.db.models import (
    ContractRecord,
    ContractVersionRecord,
    RunRecord,
    WorkspaceMemberRecord,
)


async def assert_run_access(db: AsyncSession, run_id: str, token: dict) -> RunRecord:
    """Return the RunRecord if the caller is allowed to access it, else raise.

    404 is used for both missing and cross-tenant runs to avoid leaking existence.
    403 is raised when the run belongs to the caller's tenant but the caller is
    not a member of the contract's workspace.
    """
    run = await db.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    user_id = str(token.get("sub") or "")
    org_id = str(token.get("org_id") or "")
    allowed_tenants = {t for t in (org_id, user_id) if t}

    if run.tenant_id not in allowed_tenants:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # Resolve contract link: runs -> contract_versions -> contracts
    version_result = await db.execute(
        select(ContractVersionRecord).where(ContractVersionRecord.run_id == run_id)
    )
    version = version_result.scalar_one_or_none()

    if version is None:
        # Standalone/legacy run — tenant check above is sufficient
        return run

    contract = await db.get(ContractRecord, version.contract_id)
    if contract is None or contract.workspace_id is None:
        # Contract exists but has no workspace scope — tenant check is sufficient
        return run

    # Workspace-scoped run: org_admin bypass or explicit membership required
    if (
        token.get("org_role") == "org_admin"
        and org_id
        and contract.org_id == org_id
    ):
        return run

    member_result = await db.execute(
        select(WorkspaceMemberRecord).where(
            WorkspaceMemberRecord.workspace_id == contract.workspace_id,
            WorkspaceMemberRecord.user_id == user_id,
        )
    )
    if member_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return run
