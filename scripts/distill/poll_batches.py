#!/usr/bin/env python3
"""
poll_batches.py — Check status of submitted batches and download completed ones.

Reads/updates: data/distillation/batches/state.json

Run at any time after submit_batches.py to check progress.
Automatically downloads output files for completed batches.
"""

import json
import sys
from pathlib import Path

from .config import BATCHES_DIR, DISTILL_DIR
from .oauth import make_openai_client

STATE_FILE = BATCHES_DIR / "state.json"
RESULTS_DIR = DISTILL_DIR / "results"

TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}


def load_state() -> dict:
    if not STATE_FILE.exists():
        sys.exit(f"No state file at {STATE_FILE}. Run submit_batches.py first.")
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def download_output(client, batch_id: str, output_file_id: str, key: str) -> Path:
    out_path = RESULTS_DIR / f"{key}_results.jsonl"
    if out_path.exists():
        print(f"    Already downloaded → {out_path.name}")
        return out_path
    print(f"    Downloading output for {key} ...")
    content = client.files.content(output_file_id)
    out_path.write_bytes(content.read())
    print(f"    Saved → {out_path.name}  ({out_path.stat().st_size // 1024} KB)")
    return out_path


def main() -> None:
    print("Authenticating via Codex OAuth...")
    client = make_openai_client()
    state = load_state()

    print("=" * 60)
    print("Batch Status")
    print("=" * 60)
    print(f"\n{'File':<40} {'Dataset':<12} {'Status':<14} {'Progress'}")
    print("-" * 80)

    all_done = True
    for key, entry in state.items():
        batch_id = entry.get("batch_id")
        if not batch_id:
            continue

        if entry.get("status") not in TERMINAL_STATUSES:
            batch = client.batches.retrieve(batch_id)
            entry["status"] = batch.status
            if batch.output_file_id:
                entry["output_file_id"] = batch.output_file_id
            save_state(state)

        status = entry.get("status", "unknown")
        counts = ""
        if status not in TERMINAL_STATUSES:
            all_done = False

        # Download if completed and not yet downloaded
        if status == "completed" and entry.get("output_file_id") and not entry.get("downloaded"):
            output_path = download_output(client, batch_id, entry["output_file_id"], Path(key).stem)
            entry["output_path"] = str(output_path)
            entry["downloaded"] = True
            save_state(state)

        print(f"  {key:<38} {entry.get('dataset',''):<12} {status:<14} {counts}")

    print()
    if all_done:
        pending = [k for k, v in state.items() if v.get("status") not in TERMINAL_STATUSES]
        if not pending:
            print("All batches complete.")
            print("Next: python -m scripts.distill.parse_results")
        else:
            print(f"{len(pending)} batch(es) still pending.")
    else:
        print("Some batches still in progress. Re-run to check again.")


if __name__ == "__main__":
    main()
