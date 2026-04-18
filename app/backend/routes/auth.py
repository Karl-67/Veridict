from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.backend.db.models import OrgInviteRecord, OrganizationRecord, UserRecord, WorkspaceMemberRecord
from app.backend.db.session import DbSession
from app.backend.services.auth_service import (
    check_account_lockout,
    create_access_token,
    create_refresh_token,
    hash_password,
    record_failed_login,
    record_successful_login,
    require_auth,
    revoke_refresh_token,
    rotate_refresh_token,
    validate_password_strength,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "veridict_refresh"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days in seconds

AVATAR_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
    "#10b981", "#3b82f6", "#ef4444", "#14b8a6",
]


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=False,   # set True in production with HTTPS
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE, path="/api/auth")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateOrgRequest(BaseModel):
    org_name: str
    display_name: str
    job_title: str | None = None
    department: str | None = None
    email: str
    password: str


class RegisterFromInviteRequest(BaseModel):
    token: str
    password: str
    display_name: str | None = None
    job_title: str | None = None
    department: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    user_id: str
    email: str
    display_name: str
    job_title: str | None
    department: str | None
    avatar_color: str
    org_id: str | None
    org_role: str
    org_name: str | None


class InvitePreviewResponse(BaseModel):
    email: str
    org_name: str
    invited_by: str
    workspace_name: str | None
    workspace_role: str
    account_exists: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_auth_response(user: UserRecord, access_token: str, org_name: str | None) -> AuthResponse:
    return AuthResponse(
        access_token=access_token,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        job_title=user.job_title,
        department=user.department,
        avatar_color=user.avatar_color,
        org_id=user.org_id,
        org_role=user.org_role,
        org_name=org_name,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/create-org", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def create_org(body: CreateOrgRequest, response: Response, db: DbSession) -> AuthResponse:
    """First user from a firm creates the organisation and becomes org_admin."""
    existing = (await db.execute(select(UserRecord).where(UserRecord.email == body.email.lower().strip()))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    validate_password_strength(body.password)

    slug = body.org_name.lower().replace(" ", "-").replace("'", "") + "-" + secrets.token_hex(3)
    org = OrganizationRecord(id=str(uuid.uuid4()), name=body.org_name.strip(), slug=slug)
    db.add(org)
    await db.flush()

    color = AVATAR_COLORS[len(body.display_name) % len(AVATAR_COLORS)]
    user = UserRecord(
        id=str(uuid.uuid4()),
        email=body.email.lower().strip(),
        display_name=body.display_name.strip(),
        hashed_password=hash_password(body.password),
        org_id=org.id,
        org_role="org_admin",
        job_title=body.job_title,
        department=body.department,
        avatar_color=color,
    )
    db.add(user)
    await db.flush()

    refresh = await create_refresh_token(db, user.id)
    _set_refresh_cookie(response, refresh)
    return _build_auth_response(user, create_access_token(user), org.name)


@router.get("/invite-preview/{token}", response_model=InvitePreviewResponse)
async def invite_preview(token: str, db: DbSession) -> InvitePreviewResponse:
    """Return invite metadata so the registration form can pre-fill org info."""
    invite = (await db.execute(select(OrgInviteRecord).where(OrgInviteRecord.token == token))).scalar_one_or_none()
    if not invite or invite.used_at or (invite.expires_at and invite.expires_at < datetime.utcnow()):
        raise HTTPException(status_code=404, detail="Invite not found or expired")
    await db.refresh(invite, ["org"])
    inviter = await db.get(UserRecord, invite.created_by)
    workspace_name: str | None = None
    if invite.workspace_id:
        from app.backend.db.models import WorkspaceRecord
        ws = await db.get(WorkspaceRecord, invite.workspace_id)
        workspace_name = ws.name if ws else None
    existing = (await db.execute(select(UserRecord).where(UserRecord.email == invite.email))).scalar_one_or_none()
    return InvitePreviewResponse(
        email=invite.email,
        org_name=invite.org.name,
        invited_by=inviter.display_name if inviter else "Admin",
        workspace_name=workspace_name,
        workspace_role=invite.workspace_role,
        account_exists=existing is not None,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_from_invite(body: RegisterFromInviteRequest, response: Response, db: DbSession) -> AuthResponse:
    """Complete registration using an invite token."""
    invite = (await db.execute(select(OrgInviteRecord).where(OrgInviteRecord.token == body.token))).scalar_one_or_none()
    if not invite or invite.used_at or (invite.expires_at and invite.expires_at < datetime.utcnow()):
        raise HTTPException(status_code=400, detail="Invite token is invalid or expired")

    existing = (await db.execute(select(UserRecord).where(UserRecord.email == invite.email))).scalar_one_or_none()
    await db.refresh(invite, ["org"])

    if existing:
        # Account exists — verify password and add to workspace
        await check_account_lockout(existing)
        verify_password = __import__("app.backend.services.auth_service", fromlist=["verify_password"]).verify_password
        if not verify_password(body.password, existing.hashed_password):
            await record_failed_login(db, existing)
            raise HTTPException(status_code=401, detail="Incorrect password")
        await record_successful_login(db, existing)
        if invite.workspace_id:
            already = (await db.execute(
                select(WorkspaceMemberRecord).where(
                    WorkspaceMemberRecord.workspace_id == invite.workspace_id,
                    WorkspaceMemberRecord.user_id == existing.id,
                )
            )).scalar_one_or_none()
            if not already:
                db.add(WorkspaceMemberRecord(
                    id=str(uuid.uuid4()),
                    workspace_id=invite.workspace_id,
                    user_id=existing.id,
                    role=invite.workspace_role,
                ))
        invite.used_at = datetime.utcnow()
        await db.flush()
        refresh = await create_refresh_token(db, existing.id)
        _set_refresh_cookie(response, refresh)
        return _build_auth_response(existing, create_access_token(existing), invite.org.name)

    if not body.display_name:
        raise HTTPException(status_code=422, detail="display_name is required for new accounts")
    validate_password_strength(body.password)

    color = AVATAR_COLORS[len(body.display_name) % len(AVATAR_COLORS)]
    user = UserRecord(
        id=str(uuid.uuid4()),
        email=invite.email,
        display_name=body.display_name.strip(),
        hashed_password=hash_password(body.password),
        org_id=invite.org_id,
        org_role=invite.org_role,
        job_title=body.job_title,
        department=body.department,
        avatar_color=color,
    )
    db.add(user)
    await db.flush()

    if invite.workspace_id:
        db.add(WorkspaceMemberRecord(
            id=str(uuid.uuid4()),
            workspace_id=invite.workspace_id,
            user_id=user.id,
            role=invite.workspace_role,
        ))

    invite.used_at = datetime.utcnow()
    await db.flush()

    refresh = await create_refresh_token(db, user.id)
    _set_refresh_cookie(response, refresh)
    return _build_auth_response(user, create_access_token(user), invite.org.name)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, response: Response, db: DbSession) -> AuthResponse:
    user = (await db.execute(select(UserRecord).where(UserRecord.email == body.email.lower().strip()))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await check_account_lockout(user)

    if not __import__("app.backend.services.auth_service", fromlist=["verify_password"]).verify_password(body.password, user.hashed_password):
        await record_failed_login(db, user)
        remaining = max(0, 5 - user.failed_login_attempts)
        raise HTTPException(
            status_code=401,
            detail=f"Invalid email or password.{f' {remaining} attempt(s) remaining before lockout.' if remaining > 0 else ' Account locked.'}",
        )

    await record_successful_login(db, user)
    org_name: str | None = None
    if user.org_id:
        org = await db.get(OrganizationRecord, user.org_id)
        org_name = org.name if org else None

    refresh = await create_refresh_token(db, user.id)
    _set_refresh_cookie(response, refresh)
    return _build_auth_response(user, create_access_token(user), org_name)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(response: Response, db: DbSession, veridict_refresh: str | None = Cookie(default=None)) -> AuthResponse:
    if not veridict_refresh:
        raise HTTPException(status_code=401, detail="No refresh token")
    new_raw, user = await rotate_refresh_token(db, veridict_refresh)
    _set_refresh_cookie(response, new_raw)
    org_name: str | None = None
    if user.org_id:
        org = await db.get(OrganizationRecord, user.org_id)
        org_name = org.name if org else None
    return _build_auth_response(user, create_access_token(user), org_name)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, db: DbSession, veridict_refresh: str | None = Cookie(default=None)) -> None:
    if veridict_refresh:
        await revoke_refresh_token(db, veridict_refresh)
    _clear_refresh_cookie(response)


@router.get("/me")
async def me(token: dict = Depends(require_auth)) -> dict:
    return {
        "user_id": token["sub"],
        "email": token["email"],
        "display_name": token["name"],
        "org_id": token.get("org_id"),
        "org_role": token.get("org_role"),
        "job_title": token.get("job_title"),
        "department": token.get("department"),
        "avatar_color": token.get("avatar_color"),
    }
