"""
fine_tune.py — Admin API for the Kira fine-tuning pipeline.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.services.auth_service import require_org_admin

router = APIRouter(prefix="/api/fine-tune", tags=["fine-tune"])

ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUTPUT_DIR = ROOT / "scripts" / "fine_tune" / "output"
STATUS_FILE = OUTPUT_DIR / "training_status.json"
LOG_FILE = OUTPUT_DIR / "training_log.txt"
ENV_FILE = ROOT / "app" / "backend" / ".env"

# In-memory cache of config values set via /config in this process lifetime.
# launch.py reads these via os.getenv(), so we inject them into the subprocess env.
_live_config: dict[str, str] = {}

_training_process: subprocess.Popen | None = None  # type: ignore[type-arg]


class FineTuneConfig(BaseModel):
    runpod_host: str
    runpod_ssh_key_path: str
    runpod_port: int = 22
    runpod_user: str = "root"
    hf_token: str = ""


class FineTuneStartRequest(BaseModel):
    skip_gdrive: bool = False
    skip_eval: bool = False


def _read_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except Exception:
            pass
    return {"status": "idle"}


def _is_running() -> bool:
    global _training_process
    if _training_process is None:
        return False
    return _training_process.poll() is None


def _update_env(key: str, value: str) -> None:
    """Write or update a key=value line in the backend .env file."""
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            lines[i] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _drain_stdout(proc: subprocess.Popen, log_path: Path) -> None:  # type: ignore[type-arg]
    """Drain subprocess stdout into the log file to prevent OS pipe-buffer deadlock."""
    assert proc.stdout is not None
    with log_path.open("a", encoding="utf-8") as f:
        for line in proc.stdout:
            f.write(line)
            f.flush()


@router.post("/config")
def save_config(cfg: FineTuneConfig, _token: dict = Depends(require_org_admin)):
    """Persist RunPod SSH credentials to .env and keep them in memory for the current process."""
    mapping = {
        "RUNPOD_HOST": cfg.runpod_host,
        "RUNPOD_SSH_KEY_PATH": cfg.runpod_ssh_key_path,
        "RUNPOD_PORT": str(cfg.runpod_port),
        "RUNPOD_USER": cfg.runpod_user,
    }
    if cfg.hf_token:
        mapping["HF_TOKEN"] = cfg.hf_token

    for key, value in mapping.items():
        _update_env(key, value)
        _live_config[key] = value  # makes the value immediately visible to /start

    return {"ok": True}


@router.post("/start")
def start_training(req: FineTuneStartRequest, _token: dict = Depends(require_org_admin)):
    """Launch the fine-tuning pipeline as a background process."""
    global _training_process

    if _is_running():
        raise HTTPException(status_code=409, detail="Training already in progress")

    # Prefer in-memory config (set via /config this session) over process environment.
    runpod_host = _live_config.get("RUNPOD_HOST") or os.getenv("RUNPOD_HOST", "")
    if not runpod_host:
        raise HTTPException(
            status_code=400,
            detail="RUNPOD_HOST not configured. Use POST /api/fine-tune/config first.",
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps({
        "status": "starting",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }))
    LOG_FILE.write_text("")

    # Inject freshly-saved config values so the subprocess sees them even if the
    # API process was started before /config was called.
    env = {**os.environ, **_live_config}

    cmd = [sys.executable, "-m", "scripts.fine_tune.launch"]
    if req.skip_gdrive:
        cmd.append("--skip-gdrive")
    if req.skip_eval:
        cmd.append("--skip-eval")

    _training_process = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Drain stdout in a background thread so the OS pipe buffer never fills and
    # blocks the child process.
    threading.Thread(
        target=_drain_stdout,
        args=(_training_process, LOG_FILE),
        daemon=True,
    ).start()

    return {"ok": True, "pid": _training_process.pid}


@router.get("/status")
def get_status(_token: dict = Depends(require_org_admin)):
    """Return training status + last 100 lines of log."""
    status = _read_status()
    status["is_running"] = _is_running()

    log_tail: list[str] = []
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        log_tail = lines[-100:]

    return {**status, "log_tail": log_tail}


@router.get("/stats")
def get_stats(_token: dict = Depends(require_org_admin)):
    """Return before/after evaluation metrics."""
    before_file = OUTPUT_DIR / "eval_before.json"
    after_file = OUTPUT_DIR / "eval_after.json"

    before = json.loads(before_file.read_text()) if before_file.exists() else None
    after = json.loads(after_file.read_text()) if after_file.exists() else None

    if before is None and after is None:
        return {"available": False, "message": "No evaluation data yet. Run training first."}

    def _delta(key: str) -> float | None:
        if before is None or after is None:
            return None
        b = before.get(key)
        a = after.get(key)
        if b is None or a is None:
            return None
        return round(a - b, 4)

    metric_keys = [
        "json_validity_rate", "schema_compliance_rate", "issue_type_accuracy",
        "severity_accuracy", "clause_uid_f1", "recommended_change_avg_tokens",
        "rouge_l_description",
    ]
    deltas = {k: _delta(k) for k in metric_keys}

    return {
        "available": True,
        "before": before,
        "after": after,
        "deltas": deltas,
    }
