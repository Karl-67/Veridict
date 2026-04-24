#!/usr/bin/env python3
"""
run_distill.py — Knowledge distillation pipeline runner.

Usage:
  python -m scripts.run_distill build                    # Build batch input files (sorted small→large)
  python -m scripts.run_distill calls                    # Run all calls via Codex OAuth (no API key)
  python -m scripts.run_distill calls --max-new 200      # Label at most 200 requests, then stop
  python -m scripts.run_distill calls --status           # Print progress without making any calls
  python -m scripts.run_distill calls --dry-run 5        # Test with 5 requests first
  python -m scripts.run_distill parse                    # Merge GPT annotations into curated rows
  python -m scripts.run_distill export                   # Export Gemma 4 fine-tuning JSONL
  python -m scripts.run_distill train                    # Fine-tune Gemma 4 on distillation data
  python -m scripts.run_distill all                      # build → calls → parse → export

Resume workflow (when rate limit resets):
  # First run — labels as many small contracts as possible
  python -m scripts.run_distill calls --max-new 500
  # Check what is left
  python -m scripts.run_distill calls --status
  # Next session — picks up exactly where it left off
  python -m scripts.run_distill calls --max-new 500

Prerequisites:
  1. Run scripts/curate_dataset.py to generate data/curated/
  2. Set OPENAI_API_KEY environment variable
  3. pip install openai
"""

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "build":
        from scripts.distill.build_batches import main as run
        run()

    elif cmd == "calls":
        from scripts.distill.run_calls import main as run
        run()

    elif cmd == "parse":
        from scripts.distill.parse_results import main as run
        run()

    elif cmd == "export":
        from scripts.distill.export_gemma import main as run
        run()

    elif cmd == "train":
        from scripts.distill.train_gemma import main as run
        run()

    elif cmd == "all":
        print("Running: build → calls → parse → export\n")
        from scripts.distill.build_batches import main as build
        from scripts.distill.run_calls import main as calls
        from scripts.distill.parse_results import main as parse
        from scripts.distill.export_gemma import main as export
        build()
        print()
        calls()
        print()
        parse()
        print()
        export()

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
