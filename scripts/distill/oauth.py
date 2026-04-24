"""
oauth.py — Load and refresh the OpenAI OAuth token from Codex's auth.json.

Reads:   ~/.codex/auth.json
Updates: ~/.codex/auth.json  (writes refreshed tokens back)

The access_token is a standard Bearer JWT accepted by https://api.openai.com/v1.
Pass it directly as api_key to the OpenAI SDK — no API billing account needed.
"""

import base64
import json
import sys
import time
from pathlib import Path

import httpx

AUTH_FILE = Path.home() / ".codex" / "auth.json"

def _auth_file(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    return AUTH_FILE
REFRESH_URL = "https://auth.openai.com/oauth/token"
# Buffer — refresh if token expires within 5 minutes
EXPIRY_BUFFER_SECS = 300


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without signature verification."""
    try:
        payload_b64 = token.split(".")[1]
        # Add padding if needed
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


def _is_expired(access_token: str) -> bool:
    payload = _decode_jwt_payload(access_token)
    exp = payload.get("exp", 0)
    return time.time() >= (exp - EXPIRY_BUFFER_SECS)


def _refresh(auth: dict) -> dict:
    """Exchange refresh_token for a new access_token. Updates auth dict in place."""
    refresh_token = auth.get("tokens", {}).get("refresh_token")
    if not refresh_token:
        sys.exit("No refresh_token in auth.json. Re-login to Codex and try again.")

    # Extract client_id from the current access_token JWT
    access_token = auth.get("tokens", {}).get("access_token", "")
    payload = _decode_jwt_payload(access_token)
    client_id = payload.get("client_id", "app_EMoamEEZ73f0CkXaXp7hrann")

    resp = httpx.post(
        REFRESH_URL,
        json={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        timeout=15,
    )

    if resp.status_code != 200:
        sys.exit(
            f"Token refresh failed ({resp.status_code}): {resp.text[:200]}\n"
            "Re-login to Codex: run `codex` and complete auth, then retry."
        )

    data = resp.json()
    auth["tokens"]["access_token"]  = data["access_token"]
    auth["tokens"]["id_token"]      = data.get("id_token", auth["tokens"].get("id_token"))
    if "refresh_token" in data:
        auth["tokens"]["refresh_token"] = data["refresh_token"]

    from datetime import datetime, timezone
    auth["last_refresh"] = datetime.now(timezone.utc).isoformat()
    return auth


def get_access_token(auth_file: str | None = None) -> str:
    """
    Return a valid access_token from ~/.codex/auth.json (or override path).
    Automatically refreshes if expired. Saves updated tokens back to disk.
    """
    path = _auth_file(auth_file)
    if not path.exists():
        sys.exit(
            f"Codex auth file not found at {path}.\n"
            "Run `codex` once to complete OAuth login, then retry."
        )

    with open(path) as f:
        auth = json.load(f)

    if auth.get("auth_mode") != "chatgpt":
        sys.exit(
            f"Unexpected auth_mode '{auth.get('auth_mode')}' in {path}. "
            "Expected 'chatgpt' OAuth mode."
        )

    access_token = auth.get("tokens", {}).get("access_token")
    if not access_token:
        sys.exit(f"No access_token in {path}. Re-login to Codex.")

    if _is_expired(access_token):
        print("  OAuth token expired — refreshing...")
        auth = _refresh(auth)
        with open(path, "w") as f:
            json.dump(auth, f, indent=2)
        print("  Token refreshed and saved.")
        access_token = auth["tokens"]["access_token"]

    return access_token


def make_openai_client():
    """Return an OpenAI client authenticated via Codex OAuth."""
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai package not installed. Run: pip install openai")

    token = get_access_token()
    return OpenAI(api_key=token)
