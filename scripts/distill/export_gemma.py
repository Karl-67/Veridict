#!/usr/bin/env python3
"""
export_gemma.py — Export distillation data as Gemma 4 fine-tuning JSONL.

Reads:  data/distillation/annotated/{reviewer,validator,sec}_annotated.jsonl
Writes: data/distillation/gemma/train.jsonl
        data/distillation/gemma/val.jsonl
        data/distillation/gemma/test.jsonl
        data/distillation/gemma/export_report.json

Only rows with a valid gpt_score (0–5) are exported.
Rows with score=0 are included at a capped rate to avoid flooding the
fine-tuning set with trivial negatives (boilerplate).
"""

import json
import random
from collections import Counter
from pathlib import Path

from .config import ANNOTATED_DIR, GEMMA_DIR, ISSUE_TYPE_DISPLAY, SCORE_LABELS
BOILERPLATE_SAMPLE_RATE = 0.15   # keep 15% of score=0 rows to balance negatives

SYSTEM_PROMPT = (
    "You are Veridict, a specialized AI legal contract reviewer. "
    "When given a contract clause, you assess its legal risk, identify the issue type, "
    "explain the risk, and recommend a course of action."
)

SYSTEM_PROMPT_VALIDATOR = (
    "You are Veridict, a specialized AI legal contract validator. "
    "Given a contract clause and a proposed legal finding, determine whether "
    "the finding is supported by the clause text."
)


# ── Format helpers ────────────────────────────────────────────────────────────


def format_issue_type(raw: str) -> str:
    return ISSUE_TYPE_DISPLAY.get(raw, raw.replace("_", " ").title())


def reviewer_turn(row: dict) -> dict | None:
    score = row.get("gpt_score")
    if score is None:
        return None
    reason = str(row.get("gpt_reason", "")).strip()
    action = str(row.get("gpt_action") or "").strip() or _action_from_score(score)
    issue_type = format_issue_type(str(row.get("gpt_issue_type") or row.get("issue_type", "")))
    clause_text = str(row.get("clause_text", "")).strip()
    if not clause_text:
        return None

    user_content = f"Review this contract clause:\n\n{clause_text}"
    assistant_content = (
        f"Risk Score: {score}/5 — {SCORE_LABELS[score]}\n"
        f"Category: {issue_type}\n"
        f"Assessment: {reason}\n"
        f"Recommended Action: {action}"
    )
    return _chat(SYSTEM_PROMPT, user_content, assistant_content)


def validator_turn(row: dict) -> dict | None:
    score = row.get("gpt_score")
    verdict = str(row.get("gpt_verdict") or row.get("verdict", "")).strip()
    reason = str(row.get("gpt_reason", "")).strip()
    premise = str(row.get("premise", "")).strip()
    hypothesis = str(row.get("hypothesis", "")).strip()
    if not premise or not hypothesis or not verdict:
        return None

    user_content = f"Validate this contract finding:\n\nClause: {premise}\nFinding: {hypothesis}"
    score_line = f"\nRisk Score: {score}/5" if score is not None else ""
    assistant_content = (
        f"Verdict: {verdict.capitalize()}\n"
        f"{score_line}\n"
        f"Reasoning: {reason}"
    ).strip()
    return _chat(SYSTEM_PROMPT_VALIDATOR, user_content, assistant_content)


def sec_turn(row: dict) -> dict | None:
    score = row.get("gpt_score")
    if score is None:
        return None
    reason = str(row.get("gpt_reason", "")).strip()
    action = str(row.get("gpt_action") or "").strip() or _action_from_score(score)
    issue_type = format_issue_type(str(row.get("gpt_issue_type", "")))
    key_clause = str(row.get("gpt_key_clause", "")).strip()
    chunk_text = str(row.get("chunk_text", "")).strip()

    if not chunk_text and not key_clause:
        return None

    user_content = f"Analyze this contract excerpt for risk:\n\n{chunk_text}" if chunk_text else \
        f"Analyze this contract clause:\n\n{key_clause}"

    key_clause_line = f'\nKey Clause: "{key_clause}"' if key_clause else ""
    assistant_content = (
        f"Risk Score: {score}/5 — {SCORE_LABELS[score]}\n"
        f"Category: {issue_type}"
        f"{key_clause_line}\n"
        f"Assessment: {reason}\n"
        f"Recommended Action: {action}"
    ).strip()
    return _chat(SYSTEM_PROMPT, user_content, assistant_content)


def _action_from_score(score: int) -> str:
    mapping = {0: "accept", 1: "note", 2: "note", 3: "flag", 4: "redline", 5: "reject"}
    return mapping.get(score, "flag")


def _chat(system: str, user: str, assistant: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


# ── Loaders ───────────────────────────────────────────────────────────────────


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


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    random.seed(42)

    print("=" * 60)
    print("Export to Gemma 4 Format")
    print("=" * 60)

    by_split: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    report: dict = {}

    # ── Reviewer ──────────────────────────────────────────────────────────────
    rev_rows = load_jsonl(ANNOTATED_DIR / "reviewer_annotated.jsonl")
    rev_converted = skipped = 0
    score_zero_seen = 0

    for row in rev_rows:
        if row.get("gpt_score") == 0:
            # Cap boilerplate negatives
            if random.random() > BOILERPLATE_SAMPLE_RATE:
                score_zero_seen += 1
                continue
        turn = reviewer_turn(row)
        if turn is None:
            skipped += 1
            continue
        split = row.get("split", "train")
        if split not in by_split:
            split = "train"
        by_split[split].append(turn)
        rev_converted += 1

    print(f"\n[Reviewer] {len(rev_rows):,} rows → {rev_converted:,} turns  (skipped {skipped}, boilerplate-capped {score_zero_seen})")
    report["reviewer"] = {"input": len(rev_rows), "exported": rev_converted}

    # ── Validator ─────────────────────────────────────────────────────────────
    val_rows = load_jsonl(ANNOTATED_DIR / "validator_annotated.jsonl")
    val_converted = val_skipped = 0

    for row in val_rows:
        turn = validator_turn(row)
        if turn is None:
            val_skipped += 1
            continue
        split = row.get("split", "train")
        if split not in by_split:
            split = "train"
        by_split[split].append(turn)
        val_converted += 1

    print(f"[Validator] {len(val_rows):,} rows → {val_converted:,} turns  (skipped {val_skipped})")
    report["validator"] = {"input": len(val_rows), "exported": val_converted}

    # ── SEC ───────────────────────────────────────────────────────────────────
    sec_rows = load_jsonl(ANNOTATED_DIR / "sec_annotated.jsonl")
    sec_converted = sec_skipped = 0

    for row in sec_rows:
        turn = sec_turn(row)
        if turn is None:
            sec_skipped += 1
            continue
        by_split["train"].append(turn)   # SEC has no pre-assigned split
        sec_converted += 1

    print(f"[SEC]       {len(sec_rows):,} rows → {sec_converted:,} turns  (skipped {sec_skipped})")
    report["sec"] = {"input": len(sec_rows), "exported": sec_converted}

    # ── Write splits ──────────────────────────────────────────────────────────
    print()
    for split, turns in by_split.items():
        random.shuffle(turns)
        out = GEMMA_DIR / f"{split}.jsonl"
        write_jsonl(turns, out)
        score_dist = Counter(
            t["messages"][2]["content"].split("\n")[0] for t in turns
        )
        print(f"  {split:6}: {len(turns):>7,} turns → {out.name}")
        report[split] = len(turns)

    total = sum(len(v) for v in by_split.values())
    print(f"\n  Total: {total:,} fine-tuning turns")

    report_path = GEMMA_DIR / "export_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nExport report → {report_path}")
    print("\nDone. Fine-tuning data ready in data/distillation/gemma/")


if __name__ == "__main__":
    main()
