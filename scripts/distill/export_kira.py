#!/usr/bin/env python3
"""
export_kira.py — Export labeled Kira rows to Gemma chat-turn format.

Reads  data/kira/labeled/{train,val,test}.jsonl
Writes data/kira/ft/{train,val,test}.jsonl

Balancing (train only):
  1. No-risk rows (ds_issue_type is null) capped at 20% of train.
  2. Per clause_type: cap at median_count × 3.
  3. Within each clause_type bucket: ensure ≥1 example per severity (upsample ≤2×).

Usage:
  python -m scripts.distill.export_kira
"""

import json
import logging
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from .config import KIRA_LABELED_DIR, KIRA_FT_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

random.seed(42)

SPLITS = ("train", "val", "test")

SYSTEM_KIRA = (
    "You are Kira, an expert AI legal contract reviewer. Given a contract clause with context "
    "and a targeted review question, you assess whether it creates material legal risk. "
    "You assign severity based on actual clause language, not topic alone, and always "
    "justify your assessment with exact text evidence."
)


# ── Evidence span resolution ──────────────────────────────────────────────────

def get_evidence(row: dict) -> str:
    if row.get("ds_evidence_valid"):
        return (row.get("ds_evidence_span") or "")[:300]
    gt_spans = row.get("ground_truth_spans") or []
    if gt_spans:
        return max(gt_spans, key=len)[:300]
    return row["clause_text"][:200]


# ── Chat turn builders ────────────────────────────────────────────────────────

def _user_cuad(row: dict) -> str:
    parts = [
        f"Contract: {row['contract_id']}",
        f"Clause type: {row['clause_type']}",
        f"Review question: {row['cuad_question']}",
        "",
    ]
    if row.get("left_context"):
        parts.append(f"Context before:\n{row['left_context']}")
    parts += [
        f"--- CLAUSE ---\n{row['clause_text']}\n--- END CLAUSE ---",
    ]
    if row.get("right_context"):
        parts.append(f"Context after:\n{row['right_context']}")
    return "\n".join(parts)


def _user_maud(row: dict) -> str:
    return "\n".join([
        f"Contract: {row['contract_id']}",
        f"M&A category: {row.get('maud_category', '')}",
        f"Deal-point question: {row.get('maud_question', '')}",
        f"Attorney-verified answer: {row.get('maud_answer', '')}",
        "",
        f"--- PASSAGE ---\n{row['clause_text']}\n--- END PASSAGE ---",
    ])


def _assistant(row: dict) -> str:
    issue = row.get("ds_issue_type")
    if not issue:
        return json.dumps({"findings": []}, ensure_ascii=False)

    finding = {
        "issue_type":         issue,
        "severity":           row.get("ds_severity", "low"),
        "severity_rationale": row.get("ds_severity_rationale", ""),
        "what_is_wrong":      row.get("ds_what_is_wrong", ""),
        "worst_case":         row.get("ds_worst_case", ""),
        "evidence_span":      get_evidence(row),
    }
    return json.dumps({"findings": [finding]}, ensure_ascii=False)


def row_to_turn(row: dict) -> dict:
    is_maud = row.get("source") == "maud"
    user_content = _user_maud(row) if is_maud else _user_cuad(row)
    return {
        "messages": [
            {"role": "system",    "content": SYSTEM_KIRA},
            {"role": "user",      "content": user_content},
            {"role": "assistant", "content": _assistant(row)},
        ]
    }


# ── Balancing ─────────────────────────────────────────────────────────────────

def balance_train(rows: list[dict]) -> list[dict]:
    """Apply three-pass balancing to train rows only."""
    # Pass 1: cap no-risk rows at 20%
    risk_rows    = [r for r in rows if r.get("ds_issue_type")]
    no_risk_rows = [r for r in rows if not r.get("ds_issue_type")]

    max_no_risk = max(1, int(len(rows) * 0.20))
    if len(no_risk_rows) > max_no_risk:
        random.shuffle(no_risk_rows)
        no_risk_rows = no_risk_rows[:max_no_risk]
        log.info("No-risk cap: kept %d / original (capped at 20%%)", len(no_risk_rows))

    rows = risk_rows + no_risk_rows

    # Pass 2: per-clause-type cap at median × 3
    ct_buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        ct_buckets[r.get("clause_type", "")].append(r)

    counts = [len(v) for v in ct_buckets.values()]
    if counts:
        median_count = sorted(counts)[len(counts) // 2]
        cap = max(1, median_count * 3)
        capped_rows: list[dict] = []
        for ct, bucket in ct_buckets.items():
            if len(bucket) > cap:
                random.shuffle(bucket)
                log.info(
                    "Clause-type cap: '%s' %d → %d (median×3=%d)",
                    ct, len(bucket), cap, cap,
                )
                capped_rows.extend(bucket[:cap])
            else:
                capped_rows.extend(bucket)
        rows = capped_rows

    # Pass 3: within each clause_type, ensure ≥1 per severity (upsample ≤2×)
    severities = ("critical", "high", "medium", "low")
    ct_buckets = defaultdict(list)
    for r in rows:
        ct_buckets[r.get("clause_type", "")].append(r)

    final_rows: list[dict] = []
    for ct, bucket in ct_buckets.items():
        sev_present = {r.get("ds_severity", "") for r in bucket}
        for sev in severities:
            if sev not in sev_present:
                # Look for any row in the full rows list with this ct+severity
                candidates = [r for r in rows if r.get("clause_type") == ct
                              and r.get("ds_severity") == sev]
                if candidates:
                    extra = min(len(candidates), max(1, len(bucket) // 4))
                    upsample = random.choices(candidates, k=extra)
                    bucket.extend(upsample)
        final_rows.extend(bucket)

    random.shuffle(final_rows)
    log.info("After balancing: %d train rows", len(final_rows))
    return final_rows


# ── Stats helpers ─────────────────────────────────────────────────────────────

def _print_stats(split: str, rows: list[dict]) -> None:
    total = len(rows)
    if not total:
        log.info("%s: 0 rows", split)
        return
    no_risk = sum(1 for r in rows if not r.get("ds_issue_type"))
    sev_counts = Counter(r.get("ds_severity", "low") for r in rows if r.get("ds_issue_type"))
    log.info(
        "%s: %d rows  no-risk=%.1f%%  severity=%s",
        split, total, 100 * no_risk / total,
        dict(sev_counts.most_common()),
    )


# ── I/O ───────────────────────────────────────────────────────────────────────

def _load_labeled(path: Path) -> list[dict]:
    if not path.exists():
        log.warning("Labeled file not found: %s", path)
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    if r.get("ds_labeled", True):  # keep all unless explicitly False
                        rows.append(r)
                except json.JSONDecodeError:
                    pass
    return rows


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    KIRA_FT_DIR.mkdir(parents=True, exist_ok=True)

    for split in SPLITS:
        rows = _load_labeled(KIRA_LABELED_DIR / f"{split}.jsonl")
        if not rows:
            log.warning("No labeled rows for split=%s", split)
            continue

        if split == "train":
            rows = balance_train(rows)

        _print_stats(split, rows)

        out_path = KIRA_FT_DIR / f"{split}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for row in rows:
                turn = row_to_turn(row)
                f.write(json.dumps(turn, ensure_ascii=False) + "\n")
        log.info("Wrote %d turns → %s", len(rows), out_path)

    log.info("Export complete. Files in %s", KIRA_FT_DIR)


if __name__ == "__main__":
    main()
