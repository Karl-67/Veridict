#!/usr/bin/env python3
"""
submit_batches.py — Upload batch files to OpenAI and create batch jobs.

Reads:  data/distillation/batches/manifest.json
Writes: data/distillation/batches/state.json  (batch IDs + statuses)

Run once after build_batches.py. Re-running is safe — already-submitted
batches are skipped (their batch_id is already in state.json).
"""

import json
import sys
from pathlib import Path

from .config import BATCHES_DIR, DISTILL_DIR
from .oauth import make_openai_client

STATE_FILE = BATCHES_DIR / "state.json"
MANIFEST_FILE = BATCHES_DIR / "manifest.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def submit_file(client, batch_file: str, dataset: str, state: dict) -> None:
    key = Path(batch_file).name

    if key in state and state[key].get("batch_id"):
        print(f"  {key}: already submitted (batch_id={state[key]['batch_id']}) — skipping")
        return

    print(f"  Uploading {key} ...")
    with open(batch_file, "rb") as f:
        uploaded = client.files.create(file=f, purpose="batch")

    print(f"  Creating batch job for {key} ...")
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"dataset": dataset, "source_file": key},
    )

    state[key] = {
        "dataset": dataset,
        "batch_file": batch_file,
        "input_file_id": uploaded.id,
        "batch_id": batch.id,
        "status": batch.status,
        "output_file_id": None,
    }
    save_state(state)
    print(f"  {key}: batch_id={batch.id}  status={batch.status}")


def main() -> None:
    if not MANIFEST_FILE.exists():
        sys.exit(f"Manifest not found at {MANIFEST_FILE}. Run build_batches.py first.")

    with open(MANIFEST_FILE) as f:
        manifest = json.load(f)

    print("Authenticating via Codex OAuth...")
    client = make_openai_client()
    state = load_state()

    print("=" * 60)
    print("Submit Batches")
    print("=" * 60)

    for dataset in ("reviewer", "validator", "sec"):
        files = manifest.get(dataset, {}).get("batch_files", [])
        if not files:
            continue
        print(f"\n[{dataset}] {len(files)} file(s)")
        for batch_file in files:
            if not Path(batch_file).exists():
                print(f"  WARNING: {batch_file} not found — skipping")
                continue
            submit_file(client, batch_file, dataset, state)

    print(f"\nState saved → {STATE_FILE}")
    print("Next: python -m scripts.distill.poll_batches")


if __name__ == "__main__":
    main()
