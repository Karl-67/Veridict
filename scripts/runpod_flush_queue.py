"""
Cancel all queued (IN_QUEUE) jobs on a RunPod Serverless endpoint.

Usage:
  python scripts/runpod_flush_queue.py --endpoint <endpoint_id>
  python scripts/runpod_flush_queue.py --endpoint vk8tji6dujwj35   # Harvey
  python scripts/runpod_flush_queue.py --endpoint xueffdgu1fz9jo   # Kira

Reads RUNPOD_API_KEY from env or .env file.
"""
import argparse
import os
import sys

import requests


def _api_key() -> str:
    key = os.environ.get("RUNPOD_API_KEY") or os.environ.get("VLLM_API_KEY")
    if key:
        return key
    # Try app/backend/.env
    env_path = os.path.join(os.path.dirname(__file__), "..", "app", "backend", ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith("VLLM_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    print("ERROR: set RUNPOD_API_KEY env var or ensure VLLM_API_KEY is in app/backend/.env", file=sys.stderr)
    sys.exit(1)


def flush_queue(endpoint_id: str, api_key: str, dry_run: bool = False) -> None:
    base = "https://api.runpod.io/v2"
    headers = {"Authorization": f"Bearer {api_key}"}

    # List queued jobs
    resp = requests.get(f"{base}/{endpoint_id}/requests", headers=headers, timeout=30)
    resp.raise_for_status()
    jobs = resp.json()

    queued = [j for j in jobs if j.get("status") in ("IN_QUEUE", "IN_PROGRESS")]
    print(f"Endpoint {endpoint_id}: {len(queued)} queued/in-progress jobs found")

    if not queued:
        print("Nothing to cancel.")
        return

    if dry_run:
        for j in queued:
            print(f"  [DRY RUN] would cancel job {j['id']} (status={j.get('status')})")
        return

    cancelled = 0
    failed = 0
    for j in queued:
        job_id = j["id"]
        try:
            r = requests.post(f"{base}/{endpoint_id}/cancel/{job_id}", headers=headers, timeout=10)
            if r.ok:
                print(f"  Cancelled {job_id}")
                cancelled += 1
            else:
                print(f"  Failed to cancel {job_id}: {r.status_code} {r.text[:100]}")
                failed += 1
        except Exception as e:
            print(f"  Error cancelling {job_id}: {e}")
            failed += 1

    print(f"\nDone. Cancelled={cancelled} Failed={failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cancel all queued RunPod jobs for an endpoint")
    parser.add_argument("--endpoint", required=True, help="RunPod endpoint ID")
    parser.add_argument("--dry-run", action="store_true", help="List jobs without cancelling")
    args = parser.parse_args()

    flush_queue(args.endpoint, _api_key(), dry_run=args.dry_run)
