"""
Wake Harvey and Kira RunPod workers by submitting ping jobs,
then poll until both are IN_PROGRESS (model loaded), and hold
for 20 minutes before exiting.

Usage:
    RUNPOD_API_KEY=rpa_... python scripts/warmup_runpod.py
"""

import os
import sys
import time
import requests

RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
if not RUNPOD_API_KEY:
    sys.exit("ERROR: set RUNPOD_API_KEY environment variable before running this script.")

ENDPOINTS = {
    "verdict-harvey": "vk8tji6dujwj35",
    "verdict-kira":   "xueffdgu1fz9jo",
}

MODEL_NAMES = {
    "verdict-harvey": "harvey_q4km",
    "verdict-kira":   "kira_q4km",
}

BASE_URL = "https://api.runpod.ai/v2"
WARM_MINUTES = 20


def _headers():
    return {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json",
    }


def ping_endpoint(name: str, endpoint_id: str) -> str | None:
    """Submit a minimal 1-token job to wake the worker. Returns job_id or None."""
    payload = {
        "input": {
            "messages": [{"role": "user", "content": "ping"}],
            "model": MODEL_NAMES[name],
            "max_tokens": 1,
        }
    }
    resp = requests.post(f"{BASE_URL}/{endpoint_id}/run", headers=_headers(), json=payload, timeout=30)
    if resp.status_code != 200:
        print(f"  ERROR {name}: HTTP {resp.status_code} — {resp.text[:200]}")
        return None
    data = resp.json()
    job_id = data.get("id")
    status = data.get("status")
    print(f"  {name}: job {job_id} -> {status}")
    return job_id


def poll_job(endpoint_id: str, job_id: str) -> str:
    resp = requests.get(f"{BASE_URL}/{endpoint_id}/status/{job_id}", headers=_headers(), timeout=15)
    if resp.status_code != 200:
        return "UNKNOWN"
    return resp.json().get("status", "UNKNOWN")


def wait_until_warm(jobs: dict[str, tuple[str, str]], timeout_seconds: int = 300) -> None:
    """Poll jobs until all are IN_PROGRESS or COMPLETED (model loaded)."""
    warm = set()
    deadline = time.time() + timeout_seconds
    tick = 0
    while time.time() < deadline:
        time.sleep(5)
        tick += 1
        for name, (eid, job_id) in jobs.items():
            if name in warm:
                continue
            status = poll_job(eid, job_id)
            if status in ("IN_PROGRESS", "COMPLETED"):
                print(f"  OK {name} warm (job status: {status})")
                warm.add(name)
        if len(warm) == len(jobs):
            print("\nAll workers warm.")
            return
        if tick % 6 == 0:
            remaining = int(deadline - time.time())
            print(f"  Waiting for workers... {remaining}s left. Warm so far: {warm or 'none'}")
    print(f"\nWarning: not all workers confirmed warm after {timeout_seconds}s. Proceeding anyway.")
    print(f"  Warm: {warm}, Pending: {set(jobs) - warm}")


def countdown(minutes: int) -> None:
    total = minutes * 60
    elapsed = 0
    while elapsed < total:
        remaining = total - elapsed
        m, s = divmod(remaining, 60)
        print(f"  {m:02d}:{s:02d} remaining — workers warm", flush=True)
        sleep = min(60, remaining)
        time.sleep(sleep)
        elapsed += sleep


if __name__ == "__main__":
    print("RunPod warmup script")
    print(f"Endpoints: {list(ENDPOINTS.keys())}")
    print(f"Warm window: {WARM_MINUTES} minutes\n")

    print("[1/3] Submitting ping jobs...")
    jobs: dict[str, tuple[str, str]] = {}
    for name, eid in ENDPOINTS.items():
        job_id = ping_endpoint(name, eid)
        if job_id:
            jobs[name] = (eid, job_id)

    if not jobs:
        sys.exit("ERROR: failed to submit any ping jobs. Check RUNPOD_API_KEY.")

    print(f"\n[2/3] Waiting for workers to load model (up to 5 min)...")
    wait_until_warm(jobs, timeout_seconds=300)

    print(f"\n[3/3] Holding warm for {WARM_MINUTES} minutes. Press Ctrl+C to exit early.\n")
    try:
        countdown(WARM_MINUTES)
    except KeyboardInterrupt:
        print("\nInterrupted.")

    print("\nDone. Workers will idle-timeout naturally (workersMin=0).")
