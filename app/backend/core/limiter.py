from __future__ import annotations

from fastapi import Request
from slowapi import Limiter

def _key_by_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def _key_by_user(request: Request) -> str:
    """Rate-limit by authenticated user ID when available, fall back to IP."""
    # The JWT sub claim is injected by require_auth into request.state by some
    # frameworks; here we read the Authorization header directly so the limiter
    # works without depending on the auth dependency completing first.
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        import jose.jwt as _jwt
        try:
            payload = _jwt.get_unverified_claims(auth[7:])
            if sub := payload.get("sub"):
                return f"user:{sub}"
        except Exception:
            pass
    return _key_by_ip(request)

limiter = Limiter(key_func=_key_by_ip, default_limits=[])
