from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.db.models import RefreshTokenRecord, UserRecord
from app.backend.db.session import DbSession

SECRET_KEY = "veridict-jwt-secret-change-in-prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30
MAX_FAILED_ATTEMPTS = 5

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)

PASSWORD_REQUIREMENTS = "At least 8 characters, one uppercase letter, and one number."


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail=f"Password too short. {PASSWORD_REQUIREMENTS}")
    if not any(c.isupper() for c in password):
        raise HTTPException(status_code=400, detail=f"Password must contain an uppercase letter. {PASSWORD_REQUIREMENTS}")
    if not any(c.isdigit() for c in password):
        raise HTTPException(status_code=400, detail=f"Password must contain a number. {PASSWORD_REQUIREMENTS}")


def create_access_token(user: UserRecord) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {
            "sub": user.id,
            "email": user.email,
            "name": user.display_name,
            "org_id": user.org_id,
            "org_role": user.org_role,
            "job_title": user.job_title,
            "department": user.department,
            "avatar_color": user.avatar_color,
            "exp": expire,
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_refresh_token(session: AsyncSession, user_id: str) -> str:
    raw = secrets.token_urlsafe(48)
    record = RefreshTokenRecord(
        user_id=user_id,
        token_hash=_hash_token(raw),
        expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    session.add(record)
    await session.flush()
    return raw


async def rotate_refresh_token(session: AsyncSession, raw_token: str) -> tuple[str, UserRecord]:
    """Validate an existing refresh token, revoke it, issue a new one."""
    token_hash = _hash_token(raw_token)
    result = await session.execute(
        select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == token_hash)
    )
    record = result.scalar_one_or_none()
    if not record or record.revoked or record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    record.revoked = True
    user = await session.get(UserRecord, record.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    new_raw = await create_refresh_token(session, user.id)
    return new_raw, user


async def revoke_refresh_token(session: AsyncSession, raw_token: str) -> None:
    token_hash = _hash_token(raw_token)
    result = await session.execute(
        select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == token_hash)
    )
    record = result.scalar_one_or_none()
    if record:
        record.revoked = True


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return decode_access_token(credentials.credentials)


async def require_org_admin(token: dict = Depends(require_auth)) -> dict:
    if token.get("org_role") != "org_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation admin access required")
    return token


async def check_account_lockout(user: UserRecord) -> None:
    if user.locked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account locked due to too many failed login attempts. Contact your admin.",
        )


async def record_failed_login(session: AsyncSession, user: UserRecord) -> None:
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_at = datetime.utcnow()
    await session.flush()


async def record_successful_login(session: AsyncSession, user: UserRecord) -> None:
    user.failed_login_attempts = 0
    user.locked_at = None
    await session.flush()
