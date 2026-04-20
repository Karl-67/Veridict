#!/usr/bin/env python3
"""
parse_results.py — Parse completed batch results and merge GPT annotations
back into the original curated rows.

Reads:
  data/distillation/results/*_results.jsonl   (OpenAI batch outputs)
  data/distillation/batches/manifest.json     (hash → meta mapping)
  data/curated/dataset_a/reviewer_*.jsonl
  data/curated/dataset_b/validator_*.jsonl

Writes:
  data/distillation/annotated/reviewer_annotated.jsonl
  data/distillation/annotated/validator_annotated.jsonl
  data/distillation/annotated/sec_annotated.jsonl
  data/distillation/annotated/parse_report.json
"""

import json
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from .config import ANNOTATED_DIR, BATCHES_DIR, CURATED_DIR, RESULTS_DIR, TEACHER_CLAUSE, TEACHER_CONTRACT
from .build_batches import text_hash

MANIFEST_FILE = BATCHES_DIR / "manifest.json"
SEC_CHUNK_MAP_FILE = BATCHES_DIR / "sec_chunk_map.jsonl"

VALID_ACTIONS = {"accept", "note", "flag", "redline", "reject"}
VALID_VERDICTS = {"retain", "reject", "uncertain"}
VALID_CONFIDENCE = {"high", "medium", "low"}


# ── Result loading ────────────────────────────────────────────────────────────


def load_batch_results(result_files: list[Path]) -> dict[str, dict]:
    """Load all batch result files into a dict keyed by custom_id."""
    results: dict[str, dict] = {}
    for path in result_files:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                custom_id = obj.get("custom_id", "")
                if not custom_id:
                    continue
                # Extract the assistant message content
                try:
                    content = (
                        obj["response"]["body"]["choices"][0]["message"]["content"]
                    )
                    parsed = json.loads(content)
                    results[custom_id] = {"raw": parsed, "error": None}
                except (KeyError, json.JSONDecodeError, TypeError) as e:
                    results[custom_id] = {"raw": None, "error": str(e)}
    return results


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(rows: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ── Annotation helpers ────────────────────────────────────────────────────────


def safe_score(val) -> int | None:
    try:
        s = int(val)
        return s if 0 <= s <= 5 else None
    except (TypeError, ValueError):
        return None


def annotate_clause(row: dict, gpt: dict, model: str) -> dict:
    score = safe_score(gpt.get("score"))
    action = gpt.get("action", "").lower()
    confidence = gpt.get("confidence", "").lower()
    return {
        **row,
        "gpt_score": score,
        "gpt_reason": str(gpt.get("reason", "")).strip(),
        "gpt_action": action if action in VALID_ACTIONS else None,
        "gpt_issue_type": str(gpt.get("issue_type", row.get("issue_type", ""))).strip(),
        "gpt_confidence": confidence if confidence in VALID_CONFIDENCE else None,
        "gpt_model": model,
        "gpt_ts": datetime.now(timezone.utc).isoformat(),
    }


def annotate_nli(row: dict, gpt: dict, model: str) -> dict:
    score = safe_score(gpt.get("score"))
    verdict = gpt.get("verdict", "").lower()
    confidence = gpt.get("confidence", "").lower()
    return {
        **row,
        "gpt_score": score,
        "gpt_verdict": verdict if verdict in VALID_VERDICTS else None,
        "gpt_reason": str(gpt.get("reason", "")).strip(),
        "gpt_confidence": confidence if confidence in VALID_CONFIDENCE else None,
        "gpt_model": model,
        "gpt_ts": datetime.now(timezone.utc).isoformat(),
    }


def annotate_sec(custom_id: str, gpt: dict, model: str) -> dict:
    parts = custom_id.split("_")
    row_idx = int(parts[1]) if len(parts) > 1 else -1
    chunk_idx = int(parts[2]) if len(parts) > 2 else -1
    score = safe_score(gpt.get("score"))
    action = gpt.get("action", "").lower()
    confidence = gpt.get("confidence", "").lower()
    return {
        "custom_id": custom_id,
        "source": "sec",
        "row_idx": row_idx,
        "chunk_idx": chunk_idx,
        "gpt_score": score,
        "gpt_issue_type": str(gpt.get("issue_type", "")).strip(),
        "gpt_key_clause": str(gpt.get("key_clause", "")).strip(),
        "gpt_reason": str(gpt.get("reason", "")).strip(),
        "gpt_action": action if action in VALID_ACTIONS else None,
        "gpt_confidence": confidence if confidence in VALID_CONFIDENCE else None,
        "gpt_model": model,
        "gpt_ts": datetime.now(timezone.utc).isoformat(),
    }


# ── Per-dataset parsers ───────────────────────────────────────────────────────


def parse_reviewer(results: dict[str, dict], model: str) -> tuple[list[dict], dict]:
    all_rows: list[dict] = []
    for split in ("train", "val", "test"):
        all_rows.extend(load_jsonl(CURATED_DIR / "dataset_a" / f"reviewer_{split}.jsonl"))

    if not all_rows:
        return [], {"skipped": "no curated data"}

    annotated = []
    stats = {"total": len(all_rows), "annotated": 0, "missing": 0, "parse_error": 0}

    for row in all_rows:
        clause = str(row.get("clause_text", "")).strip()
        h = text_hash(clause)
        custom_id = f"rev_{h}"
        result = results.get(custom_id)

        if result is None:
            stats["missing"] += 1
            annotated.append(row)
            continue
        if result["error"] or result["raw"] is None:
            stats["parse_error"] += 1
            annotated.append(row)
            continue

        annotated.append(annotate_clause(row, result["raw"], model))
        stats["annotated"] += 1

    return annotated, stats


def parse_validator(results: dict[str, dict], model: str) -> tuple[list[dict], dict]:
    all_rows: list[dict] = []
    for split in ("train", "val", "test"):
        all_rows.extend(load_jsonl(CURATED_DIR / "dataset_b" / f"validator_{split}.jsonl"))

    if not all_rows:
        return [], {"skipped": "no curated data"}

    annotated = []
    stats = {"total": len(all_rows), "annotated": 0, "missing": 0, "parse_error": 0}

    for row in all_rows:
        premise = str(row.get("premise", "")).strip()
        hypothesis = str(row.get("hypothesis", "")).strip()
        custom_id = f"val_{row.get('id', text_hash(premise + hypothesis))}"
        result = results.get(custom_id)

        if result is None:
            stats["missing"] += 1
            annotated.append(row)
            continue
        if result["error"] or result["raw"] is None:
            stats["parse_error"] += 1
            annotated.append(row)
            continue

        annotated.append(annotate_nli(row, result["raw"], model))
        stats["annotated"] += 1

    return annotated, stats


def load_sec_chunk_map() -> dict[str, str]:
    """Load custom_id → chunk_text mapping saved by build_batches."""
    chunk_map: dict[str, str] = {}
    if not SEC_CHUNK_MAP_FILE.exists():
        return chunk_map
    with open(SEC_CHUNK_MAP_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                chunk_map[obj["custom_id"]] = obj["chunk_text"]
    return chunk_map


def parse_sec(results: dict[str, dict], model: str) -> tuple[list[dict], dict]:
    sec_results = {k: v for k, v in results.items() if k.startswith("sec_")}
    chunk_map = load_sec_chunk_map()
    rows = []
    stats = {"total": len(sec_results), "annotated": 0, "parse_error": 0}

    for custom_id, result in sec_results.items():
        if result["error"] or result["raw"] is None:
            stats["parse_error"] += 1
            rows.append({"custom_id": custom_id, "error": result["error"]})
            continue
        row = annotate_sec(custom_id, result["raw"], model)
        row["chunk_text"] = chunk_map.get(custom_id, "")
        rows.append(row)
        stats["annotated"] += 1

    rows.sort(key=lambda r: (r.get("row_idx", -1), r.get("chunk_idx", -1)))
    return rows, stats


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 60)
    print("Parse Results")
    print("=" * 60)

    if not MANIFEST_FILE.exists():
        print(f"Manifest not found at {MANIFEST_FILE}. Run build_batches.py first.")
        return

    with open(MANIFEST_FILE) as f:
        manifest = json.load(f)

    # Collect all result files
    all_result_files = list(RESULTS_DIR.glob("*_results.jsonl"))
    if not all_result_files:
        print(f"No result files in {RESULTS_DIR}. Run poll_batches.py first.")
        return

    print(f"\nLoading {len(all_result_files)} result file(s)...")
    results = load_batch_results(all_result_files)
    print(f"  {len(results):,} total responses loaded")

    report = {}

    # Reviewer
    print("\n[Reviewer]")
    rev_model = manifest.get("reviewer", {}).get("model", TEACHER_CLAUSE)
    rev_rows, rev_stats = parse_reviewer(results, rev_model)
    if rev_rows:
        out = ANNOTATED_DIR / "reviewer_annotated.jsonl"
        write_jsonl(rev_rows, out)
        print(f"  {out.name}: {len(rev_rows):,} rows  {rev_stats}")
        report["reviewer"] = rev_stats

    # Validator
    print("\n[Validator]")
    val_model = manifest.get("validator", {}).get("model", TEACHER_CLAUSE)
    val_rows, val_stats = parse_validator(results, val_model)
    if val_rows:
        out = ANNOTATED_DIR / "validator_annotated.jsonl"
        write_jsonl(val_rows, out)
        print(f"  {out.name}: {len(val_rows):,} rows  {val_stats}")
        report["validator"] = val_stats

    # SEC
    print("\n[SEC]")
    sec_model = manifest.get("sec", {}).get("model", TEACHER_CONTRACT)
    sec_rows, sec_stats = parse_sec(results, sec_model)
    if sec_rows:
        out = ANNOTATED_DIR / "sec_annotated.jsonl"
        write_jsonl(sec_rows, out)
        print(f"  {out.name}: {len(sec_rows):,} rows  {sec_stats}")
        report["sec"] = sec_stats

    # Save report
    report_path = ANNOTATED_DIR / "parse_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nParse report → {report_path}")
    print("Next: python -m scripts.distill.export_gemma")


if __name__ == "__main__":
    main()
