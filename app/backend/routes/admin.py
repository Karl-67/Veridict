from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.backend.db.models import (
    OrgInviteRecord,
    OrganizationRecord,
    UserRecord,
    WorkspaceMemberRecord,
    WorkspaceRecord,
)
from app.backend.db.session import DbSession
from app.backend.services.auth_service import require_org_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

INVITE_EXPIRE_HOURS = 168  # 7 days


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    job_title: str | None
    department: str | None
    avatar_color: str
    org_role: str
    locked: bool
    created_at: str


class WorkspaceOut(BaseModel):
    workspace_id: str
    name: str
    description: str | None
    member_count: int
    created_at: str


class WorkspaceMemberOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    job_title: str | None
    department: str | None
    avatar_color: str
    role: str


class InviteOut(BaseModel):
    invite_id: str
    email: str
    org_role: str
    workspace_name: str | None
    workspace_role: str
    invited_by: str
    expires_at: str
    created_at: str


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str | None = None


class InviteRequest(BaseModel):
    email: str
    org_role: str = "member"
    workspace_id: str | None = None
    workspace_role: str = "reviewer"


class UpdateUserRoleRequest(BaseModel):
    org_role: str


class AddWorkspaceMemberRequest(BaseModel):
    user_id: str
    role: str = "reviewer"


class UpdateWorkspaceMemberRoleRequest(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_out(u: UserRecord) -> UserOut:
    return UserOut(
        user_id=u.id,
        email=u.email,
        display_name=u.display_name,
        job_title=u.job_title,
        department=u.department,
        avatar_color=u.avatar_color,
        org_role=u.org_role,
        locked=u.locked_at is not None,
        created_at=u.created_at.isoformat(),
    )


def _clean_workspace_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Workspace name is required")
    if len(cleaned) > 255:
        raise HTTPException(status_code=400, detail="Workspace name must be 255 characters or fewer")
    return cleaned


def _validate_workspace_role(role: str) -> None:
    if role not in {"workspace_admin", "reviewer", "viewer"}:
        raise HTTPException(status_code=400, detail="Invalid workspace role")


async def _get_org_workspace(db: DbSession, workspace_id: str, org_id: str) -> WorkspaceRecord:
    ws = await db.get(WorkspaceRecord, workspace_id)
    if not ws or ws.org_id != org_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


# ---------------------------------------------------------------------------
# Organisation info
# ---------------------------------------------------------------------------

@router.get("/org")
async def get_org(db: DbSession, token: dict = Depends(require_org_admin)) -> dict:
    org = await db.get(OrganizationRecord, token["org_id"])
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {"org_id": org.id, "name": org.name, "slug": org.slug, "created_at": org.created_at.isoformat()}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[UserOut])
async def list_users(db: DbSession, token: dict = Depends(require_org_admin)) -> list[UserOut]:
    result = await db.execute(select(UserRecord).where(UserRecord.org_id == token["org_id"]).order_by(UserRecord.created_at.asc()))
    return [_user_out(u) for u in result.scalars().all()]


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str, body: UpdateUserRoleRequest, db: DbSession, token: dict = Depends(require_org_admin)
) -> UserOut:
    user = await db.get(UserRecord, user_id)
    if not user or user.org_id != token["org_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    if body.org_role not in ("org_admin", "member"):
        raise HTTPException(status_code=400, detail="Invalid role")
    user.org_role = body.org_role
    await db.flush()
    return _user_out(user)


@router.post("/users/{user_id}/unlock")
async def unlock_user(user_id: str, db: DbSession, token: dict = Depends(require_org_admin)) -> UserOut:
    user = await db.get(UserRecord, user_id)
    if not user or user.org_id != token["org_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    user.locked_at = None
    user.failed_login_attempts = 0
    await db.flush()
    return _user_out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(user_id: str, db: DbSession, token: dict = Depends(require_org_admin)) -> None:
    user = await db.get(UserRecord, user_id)
    if not user or user.org_id != token["org_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == token["sub"]:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
    user.org_id = None
    await db.flush()


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

@router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(body: InviteRequest, db: DbSession, token: dict = Depends(require_org_admin)) -> InviteOut:
    _validate_workspace_role(body.workspace_role)
    if body.org_role not in {"org_admin", "member"}:
        raise HTTPException(status_code=400, detail="Invalid organisation role")
    ws_name: str | None = None
    if body.workspace_id:
        ws = await _get_org_workspace(db, body.workspace_id, token["org_id"])
        ws_name = ws.name

    # Check if user already in org
    existing = (await db.execute(
        select(UserRecord).where(UserRecord.email == body.email.lower().strip(), UserRecord.org_id == token["org_id"])
    )).scalar_one_or_none()
    if existing:
        # User exists — add directly to workspace if specified
        if body.workspace_id:
            already = (await db.execute(
                select(WorkspaceMemberRecord).where(
                    WorkspaceMemberRecord.workspace_id == body.workspace_id,
                    WorkspaceMemberRecord.user_id == existing.id,
                )
            )).scalar_one_or_none()
            if not already:
                db.add(WorkspaceMemberRecord(
                    id=str(uuid.uuid4()),
                    workspace_id=body.workspace_id,
                    user_id=existing.id,
                    role=body.workspace_role,
                ))
                await db.flush()
        raise HTTPException(status_code=409, detail=f"{body.email} already has an account. They have been added to the workspace.")

    invite_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=INVITE_EXPIRE_HOURS)

    invite = OrgInviteRecord(
        id=str(uuid.uuid4()),
        org_id=token["org_id"],
        email=body.email.lower().strip(),
        org_role=body.org_role,
        workspace_id=body.workspace_id,
        workspace_role=body.workspace_role,
        token=invite_token,
        created_by=token["sub"],
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()

    inviter = await db.get(UserRecord, token["sub"])
    return InviteOut(
        invite_id=invite.id,
        email=invite.email,
        org_role=invite.org_role,
        workspace_name=ws_name,
        workspace_role=invite.workspace_role,
        invited_by=inviter.display_name if inviter else "Admin",
        expires_at=expires_at.isoformat(),
        created_at=invite.created_at.isoformat(),
    )


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(db: DbSession, token: dict = Depends(require_org_admin)) -> list[InviteOut]:
    result = await db.execute(
        select(OrgInviteRecord).where(
            OrgInviteRecord.org_id == token["org_id"],
            OrgInviteRecord.used_at.is_(None),
        ).order_by(OrgInviteRecord.created_at.desc())
    )
    invites = result.scalars().all()
    out = []
    for inv in invites:
        if inv.expires_at and inv.expires_at < datetime.utcnow():
            continue
        ws_name = None
        if inv.workspace_id:
            ws = await db.get(WorkspaceRecord, inv.workspace_id)
            ws_name = ws.name if ws else None
        inviter = await db.get(UserRecord, inv.created_by)
        out.append(InviteOut(
            invite_id=inv.id,
            email=inv.email,
            org_role=inv.org_role,
            workspace_name=ws_name,
            workspace_role=inv.workspace_role,
            invited_by=inviter.display_name if inviter else "Admin",
            expires_at=inv.expires_at.isoformat() if inv.expires_at else "",
            created_at=inv.created_at.isoformat(),
        ))
    return out


@router.get("/invites/{invite_id}/link")
async def get_invite_link(invite_id: str, db: DbSession, token: dict = Depends(require_org_admin)) -> dict:
    invite = await db.get(OrgInviteRecord, invite_id)
    if not invite or invite.org_id != token["org_id"]:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"token": invite.token, "link": f"/register?invite={invite.token}"}


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: str, db: DbSession, token: dict = Depends(require_org_admin)) -> None:
    invite = await db.get(OrgInviteRecord, invite_id)
    if not invite or invite.org_id != token["org_id"]:
        raise HTTPException(status_code=404, detail="Invite not found")
    invite.used_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(db: DbSession, token: dict = Depends(require_org_admin)) -> list[WorkspaceOut]:
    result = await db.execute(
        select(WorkspaceRecord).where(WorkspaceRecord.org_id == token["org_id"]).order_by(WorkspaceRecord.created_at.asc())
    )
    workspaces = result.scalars().all()
    out = []
    for ws in workspaces:
        count_result = await db.execute(
            select(WorkspaceMemberRecord).where(WorkspaceMemberRecord.workspace_id == ws.id)
        )
        member_count = len(count_result.scalars().all())
        out.append(WorkspaceOut(
            workspace_id=ws.id,
            name=ws.name,
            description=ws.description,
            member_count=member_count,
            created_at=ws.created_at.isoformat(),
        ))
    return out


@router.post("/workspaces", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(body: CreateWorkspaceRequest, db: DbSession, token: dict = Depends(require_org_admin)) -> WorkspaceOut:
    name = _clean_workspace_name(body.name)
    existing = (await db.execute(
        select(WorkspaceRecord).where(
            WorkspaceRecord.org_id == token["org_id"],
            WorkspaceRecord.name == name,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A workspace with this name already exists")

    now = datetime.utcnow()
    ws = WorkspaceRecord(
        id=str(uuid.uuid4()),
        org_id=token["org_id"],
        name=name,
        description=body.description.strip() if body.description else None,
        created_at=now,
    )
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMemberRecord(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        user_id=token["sub"],
        role="workspace_admin",
    ))
    await db.flush()
    return WorkspaceOut(workspace_id=ws.id, name=ws.name, description=ws.description, member_count=1, created_at=now.isoformat())


@router.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
async def list_workspace_members(workspace_id: str, db: DbSession, token: dict = Depends(require_org_admin)) -> list[WorkspaceMemberOut]:
    await _get_org_workspace(db, workspace_id, token["org_id"])
    result = await db.execute(
        select(WorkspaceMemberRecord).where(WorkspaceMemberRecord.workspace_id == workspace_id)
    )
    members = result.scalars().all()
    out = []
    for m in members:
        user = await db.get(UserRecord, m.user_id)
        if user:
            out.append(WorkspaceMemberOut(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                job_title=user.job_title,
                department=user.department,
                avatar_color=user.avatar_color,
                role=m.role,
            ))
    return out


@router.post("/workspaces/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
async def add_workspace_member(
    workspace_id: str, body: AddWorkspaceMemberRequest, db: DbSession, token: dict = Depends(require_org_admin)
) -> WorkspaceMemberOut:
    _validate_workspace_role(body.role)
    await _get_org_workspace(db, workspace_id, token["org_id"])
    user = await db.get(UserRecord, body.user_id)
    if not user or user.org_id != token["org_id"]:
        raise HTTPException(status_code=404, detail="User not found in organisation")
    existing = (await db.execute(
        select(WorkspaceMemberRecord).where(
            WorkspaceMemberRecord.workspace_id == workspace_id,
            WorkspaceMemberRecord.user_id == body.user_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="User already in workspace")
    db.add(WorkspaceMemberRecord(id=str(uuid.uuid4()), workspace_id=workspace_id, user_id=body.user_id, role=body.role))
    await db.flush()
    return WorkspaceMemberOut(
        user_id=user.id, email=user.email, display_name=user.display_name,
        job_title=user.job_title, department=user.department, avatar_color=user.avatar_color, role=body.role,
    )


@router.patch("/workspaces/{workspace_id}/members/{user_id}")
async def update_workspace_member_role(
    workspace_id: str, user_id: str, body: UpdateWorkspaceMemberRoleRequest,
    db: DbSession, token: dict = Depends(require_org_admin)
) -> WorkspaceMemberOut:
    _validate_workspace_role(body.role)
    await _get_org_workspace(db, workspace_id, token["org_id"])
    member = (await db.execute(
        select(WorkspaceMemberRecord).where(
            WorkspaceMemberRecord.workspace_id == workspace_id,
            WorkspaceMemberRecord.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    member.role = body.role
    await db.flush()
    user = await db.get(UserRecord, user_id)
    if not user or user.org_id != token["org_id"]:
        raise HTTPException(status_code=404, detail="User not found in organisation")
    return WorkspaceMemberOut(
        user_id=user.id, email=user.email, display_name=user.display_name,
        job_title=user.job_title, department=user.department, avatar_color=user.avatar_color, role=member.role,
    )


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workspace_member(
    workspace_id: str, user_id: str, db: DbSession, token: dict = Depends(require_org_admin)
) -> None:
    await _get_org_workspace(db, workspace_id, token["org_id"])
    member = (await db.execute(
        select(WorkspaceMemberRecord).where(
            WorkspaceMemberRecord.workspace_id == workspace_id,
            WorkspaceMemberRecord.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.delete(member)
