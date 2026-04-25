#!/usr/bin/env python3
"""
run_branch_pipeline.py — Orchestrates the full Harvey/Kira/Validator data pipeline.

Stages:
  1  normalize_schema        — add canonical fields, split reviewer pool by branch
  2  build_context_windows   — attach left/right context from source parquets
  3  build_branch_datasets   — apply composition ratios, write harvey/ kira/ validator/
  4  build_hard_negatives    — add 6 hard-negative types to harvey/kira train splits
  5  build_validator_candidates — build retain/reject/uncertain supervision rows
  6a export_branch harvey    — format Harvey FT data as structured JSON turns
  6b export_branch kira      — format Kira FT data
  6c export_branch validator — format Validator FT data

Training (not run here — launch manually after reviewing export stats):
  python -m scripts.distill.train_gemma --role harvey   --load-4bit
  python -m scripts.distill.train_gemma --role kira     --load-4bit
  python -m scripts.distill.train_gemma --role validator --load-4bit

Usage:
  python -m scripts.run_branch_pipeline          # run all stages
  python -m scripts.run_branch_pipeline --from 3 # resume from stage 3
  python -m scripts.run_branch_pipeline --only 4 # run only stage 4
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

STAGES = [
    (1, "normalize_schema",          ["python", "-m", "scripts.normalize_schema"]),
    (2, "build_context_windows",     ["python", "-m", "scripts.build_context_windows"]),
    (3, "build_branch_datasets",     ["python", "-m", "scripts.build_branch_datasets"]),
    (4, "build_hard_negatives",      ["python", "-m", "scripts.build_hard_negatives"]),
    (5, "build_validator_candidates",["python", "-m", "scripts.build_validator_candidates"]),
    (6, "export_branch (all)",       ["python", "-m", "scripts.distill.export_branch", "--role", "all"]),
]


def run_stage(n: int, name: str, cmd: list[str]) -> bool:
    print(f"\n{'=' * 60}")
    print(f"Stage {n}: {name}")
    print(f"{'=' * 60}")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent)
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"\n[ERROR] Stage {n} ({name}) failed with code {result.returncode}")
        return False
    print(f"\n[OK] Stage {n} complete in {elapsed:.1f}s")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from",  dest="from_stage", type=int, default=1,
                        help="Resume from this stage number (inclusive)")
    parser.add_argument("--only",  type=int, default=None,
                        help="Run only this stage number")
    args = parser.parse_args()

    print("=" * 60)
    print("Branch Training Pipeline")
    print("=" * 60)
    print("\nStages:")
    for n, name, _ in STAGES:
        print(f"  {n}. {name}")

    failed = False
    for n, name, cmd in STAGES:
        if args.only is not None and n != args.only:
            continue
        if args.only is None and n < args.from_stage:
            print(f"\n  [skip] Stage {n}: {name}")
            continue
        if not run_stage(n, name, cmd):
            failed = True
            break

    print("\n" + "=" * 60)
    if failed:
        print("Pipeline FAILED. Check output above.")
        sys.exit(1)
    else:
        print("Pipeline complete.")
        print("\nNext steps (run manually when GPU is available):")
        print("  python -m scripts.distill.train_gemma --role harvey    --load-4bit")
        print("  python -m scripts.distill.train_gemma --role kira      --load-4bit")
        print("  # After Harvey/Kira training, re-run validator candidates with real outputs:")
        print("  python -m scripts.build_validator_candidates --mode inference")
        print("  python -m scripts.distill.export_branch --role validator")
        print("  python -m scripts.distill.train_gemma --role validator  --load-4bit")


if __name__ == "__main__":
    main()
