"""
Temporarily set workersMin=1 for Harvey and Kira RunPod endpoints,
hold for 20 minutes, then reset to 0.

Usage:
    RUNPOD_API_KEY=rpa_... python scripts/warmup_runpod.py

Or set the key directly in this file (do not commit).
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

GRAPHQL_URL = "https://api.runpod.io/graphql"
WARM_MINUTES = 20

MUTATION = """
mutation SetWorkers($id: String!, $min: Int!) {
  saveEndpoint(input: { id: $id, workersMin: $min }) {
    id
    workersMin
  }
}
"""


def set_workers_min(endpoint_id: str, endpoint_name: str, min_workers: int) -> bool:
    resp = requests.post(
        GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {RUNPOD_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"query": MUTATION, "variables": {"id": endpoint_id, "min": min_workers}},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  ERROR {endpoint_name}: HTTP {resp.status_code} — {resp.text[:200]}")
        return False

    data = resp.json()
    if "errors" in data:
        print(f"  ERROR {endpoint_name}: {data['errors']}")
        return False

    result = data.get("data", {}).get("saveEndpoint", {})
    print(f"  {endpoint_name} ({endpoint_id}): workersMin → {result.get('workersMin')}")
    return True


def set_all(min_workers: int, label: str) -> None:
    print(f"\n[{label}] Setting workersMin={min_workers} for all endpoints...")
    for name, eid in ENDPOINTS.items():
        set_workers_min(eid, name, min_workers)


def countdown(minutes: int) -> None:
    total_seconds = minutes * 60
    interval = 60
    elapsed = 0
    while elapsed < total_seconds:
        remaining = total_seconds - elapsed
        mins, secs = divmod(remaining, 60)
        print(f"  {mins:02d}:{secs:02d} remaining — workers warm", flush=True)
        sleep_time = min(interval, remaining)
        time.sleep(sleep_time)
        elapsed += sleep_time


if __name__ == "__main__":
    print("RunPod warmup script")
    print(f"Endpoints: {list(ENDPOINTS.keys())}")
    print(f"Warm window: {WARM_MINUTES} minutes")

    set_all(1, "WARM UP")

    print(f"\nWorkers warm. You have {WARM_MINUTES} minutes to test.")
    print("Press Ctrl+C at any time to reset workers immediately.\n")

    try:
        countdown(WARM_MINUTES)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    set_all(0, "COOL DOWN")
    print("\nDone. Workers reset to workersMin=0.")
