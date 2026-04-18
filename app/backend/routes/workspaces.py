from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.backend.db.models import WorkspaceMemberRecord, WorkspaceRecord
from app.backend.db.session import DbSession
from app.backend.services.auth_service import require_auth

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceOut(BaseModel):
    workspace_id: str
    name: str
    description: str | None
    role: str | None  # None for org_admins viewing all


@router.get("", response_model=list[WorkspaceOut])
async def list_my_workspaces(
    db: DbSession,
    token: dict = Depends(require_auth),
) -> list[WorkspaceOut]:
    """
    For org_admins: all workspaces in the org.
    For members: only workspaces they belong to.
    """
    org_id = token.get("org_id")
    is_admin = token.get("org_role") == "org_admin"

    if is_admin:
        result = await db.execute(
            select(WorkspaceRecord).where(WorkspaceRecord.org_id == org_id).order_by(WorkspaceRecord.name)
        )
        workspaces = result.scalars().all()
        return [WorkspaceOut(workspace_id=ws.id, name=ws.name, description=ws.description, role="org_admin") for ws in workspaces]
    else:
        result = await db.execute(
            select(WorkspaceMemberRecord, WorkspaceRecord)
            .join(WorkspaceRecord, WorkspaceMemberRecord.workspace_id == WorkspaceRecord.id)
            .where(WorkspaceMemberRecord.user_id == token["sub"])
            .order_by(WorkspaceRecord.name)
        )
        rows = result.all()
        return [WorkspaceOut(workspace_id=ws.id, name=ws.name, description=ws.description, role=mem.role) for mem, ws in rows]
