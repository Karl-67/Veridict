#!/usr/bin/env python3
"""
export_branch.py — Export branch-specific fine-tuning data in structured JSON format.

Reads the pre-built branch datasets (data/distillation/{harvey,kira,validator}/)
and formats them as Gemma 4 chat turns using the new structured JSON output schema.

Output format (Harvey/Kira):
  {"messages": [{"role":"system",...}, {"role":"user",...}, {"role":"assistant","content":"{\"findings\":[...]}"}]}

Output format (Validator):
  {"messages": [{"role":"system",...}, {"role":"user",...}, {"role":"assistant","content":"{\"decision\":\"retain\",...}"}]}

Writes:
  data/distillation/harvey_ft/{train,val,test}.jsonl
  data/distillation/kira_ft/{train,val,test}.jsonl
  data/distillation/validator_ft/{train,val,test}.jsonl

Usage:
  python -m scripts.distill.export_branch --role harvey
  python -m scripts.distill.export_branch --role kira
  python -m scripts.distill.export_branch --role validator
  python -m scripts.distill.export_branch --role all
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from .config import (
    HARVEY_DIR, KIRA_DIR, VALIDATOR_DIR, MAUD_DIR,
    HARVEY_FT_DIR, KIRA_FT_DIR, VALIDATOR_FT_DIR,
    ISSUE_TYPE_DISPLAY,
)
from .prompts import (
    SYSTEM_HARVEY, USER_HARVEY,
    SYSTEM_KIRA, USER_KIRA,
    SYSTEM_VALIDATOR, USER_VALIDATOR,
    SYSTEM_KIRA_MAUD, USER_KIRA_MAUD,
    SYSTEM_HARVEY_MAUD, USER_HARVEY_MAUD,
)

SPLITS = ("train", "val", "test")

# Fraction of risk_present=False rows with empty findings to keep (prevent flooding)
EMPTY_FINDINGS_KEEP_RATE = 0.30

random.seed(42)


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ── Context block helpers ─────────────────────────────────────────────────────

def left_block(left: str) -> str:
    return f"Context before:\n{left}\n\n" if left and left.strip() else ""


def right_block(right: str) -> str:
    return f"Context after:\n{right}\n\n" if right and right.strip() else ""


# ── Reviewer turn builders (Harvey / Kira) ────────────────────────────────────

def reviewer_assistant(row: dict) -> str:
    """
    Build the assistant JSON string for a reviewer row.
    Returns {"findings": [...]} or {"findings": []}.
    """
    risk_present = row.get("risk_present", True)

    # Hard negatives and low-severity no-risk rows → empty findings
    if not risk_present or str(row.get("severity", "")).lower() == "low":
        if row.get("negative_type") or not risk_present:
            return json.dumps({"findings": []}, ensure_ascii=False)

    issue_type  = str(row.get("mapped_issue_type") or row.get("issue_type", "")).strip()
    severity    = str(row.get("severity", "medium")).strip().lower()
    rationale   = str(row.get("description", "")).strip()
    evidence    = str(row.get("evidence_text") or "").strip()

    # Use clause_text snippet as evidence fallback when empty
    if not evidence:
        clause = str(row.get("clause_text", "") or row.get("full_local_context", "")).strip()
        evidence = clause[:200] if clause else ""

    if not issue_type or not rationale:
        return json.dumps({"findings": []}, ensure_ascii=False)

    finding = {
        "issue_type":    issue_type,
        "severity":      severity if severity in ("critical", "high", "medium", "low") else "medium",
        "risk_present":  True,
        "rationale":     rationale,
        "evidence_span": evidence,
    }
    return json.dumps({"findings": [finding]}, ensure_ascii=False)


def build_reviewer_turn(row: dict, system_prompt: str, user_template: str) -> dict | None:
    clause    = str(row.get("clause_text") or row.get("full_local_context", "")).strip()
    title     = str(row.get("contract_title", "Unknown Contract")).strip()
    section   = str(row.get("section_heading", "General Terms")).strip()
    left      = str(row.get("left_context", "")).strip()
    right     = str(row.get("right_context", "")).strip()

    if not clause:
        return None

    user_content = user_template.format(
        contract_title=title or "Unknown Contract",
        section_heading=section or "General Terms",
        clause_text=clause,
        left_block=left_block(left),
        right_block=right_block(right),
    )
    assistant_content = reviewer_assistant(row)

    # Cap empty-findings rows (no-risk cases)
    if assistant_content == '{"findings": []}':
        if random.random() > EMPTY_FINDINGS_KEEP_RATE:
            return None

    return {
        "messages": [
            {"role": "system",    "content": system_prompt},
            {"role": "user",      "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
    }


# ── MAUD turn builders ────────────────────────────────────────────────────────

def build_maud_turn(row: dict, system_prompt: str, user_template: str) -> dict | None:
    passage  = str(row.get("passage") or row.get("full_local_context", "")).strip()
    question = str(row.get("question", "")).strip()
    answer   = str(row.get("answer", "")).strip()
    category = str(row.get("category", "")).strip()
    text_type= str(row.get("text_type", "")).strip()
    issue    = str(row.get("mapped_issue_type") or row.get("issue_type", "")).strip()

    if not passage or not question:
        return None

    user_content = user_template.format(
        category=category,
        text_type=text_type,
        passage=passage,
        question=question,
        answer=answer,
    )

    # For MAUD, build a finding from the issue_type (attorney-annotated answer is ground truth)
    finding = {
        "issue_type":    issue or "representation_risk",
        "severity":      "medium",
        "risk_present":  True,
        "rationale":     f"This deal point ({question}) is answered as: {answer}.",
        "evidence_span": passage[:250],
    }
    assistant_content = json.dumps({"findings": [finding]}, ensure_ascii=False)

    return {
        "messages": [
            {"role": "system",    "content": system_prompt},
            {"role": "user",      "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
    }


# ── Validator turn builder ────────────────────────────────────────────────────

def build_validator_turn(row: dict) -> dict | None:
    # Accept both ContractNLI rows (premise/hypothesis) and candidate rows (clause_text)
    clause_text = str(
        row.get("clause_text") or row.get("premise") or row.get("full_local_context", "")
    ).strip()
    hypothesis  = str(row.get("hypothesis", "")).strip()
    verdict     = str(row.get("verdict") or row.get("gpt_verdict", "")).strip().lower()

    # Candidate-finding rows (from build_validator_candidates.py)
    issue      = str(row.get("issue_type") or row.get("mapped_issue_type", "")).strip()
    severity   = str(row.get("severity", "medium")).strip()
    rationale  = str(row.get("rationale") or row.get("description") or "").strip()
    evidence   = str(row.get("evidence_span") or row.get("evidence_text") or "").strip()
    decision   = str(row.get("decision") or verdict or "").strip().lower()
    reason     = str(row.get("reason") or row.get("gpt_reason", "")).strip()
    alignment  = str(row.get("evidence_alignment", "")).strip().lower()

    if not clause_text:
        return None

    # Map NLI verdicts to validator decisions
    if decision not in ("retain", "reject", "uncertain"):
        nli_map = {"entailment": "retain", "contradiction": "reject", "neutral": "uncertain"}
        decision = nli_map.get(str(row.get("nli_label", "")).lower(), "uncertain")

    if not decision:
        return None

    # For ContractNLI rows, hypothesis is the "proposed finding"
    if not issue:
        issue     = "confidentiality_risk"
        rationale = hypothesis
        evidence  = clause_text[:200]
        severity  = "medium"

    if not alignment:
        alignment = "strong" if decision == "retain" else ("none" if decision == "reject" else "weak")
    if not reason:
        reason = f"Finding {'is' if decision == 'retain' else 'is not'} supported by the clause text."

    user_content = USER_VALIDATOR.format(
        clause_text=clause_text,
        issue_type=issue or "unknown",
        severity=severity or "medium",
        rationale=rationale or hypothesis or "",
        evidence_span=evidence or clause_text[:200],
    )

    assistant_content = json.dumps({
        "decision":           decision,
        "reason":             reason,
        "evidence_alignment": alignment,
    }, ensure_ascii=False)

    return {
        "messages": [
            {"role": "system",    "content": SYSTEM_VALIDATOR},
            {"role": "user",      "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
    }


# ── Export functions ──────────────────────────────────────────────────────────

def export_harvey() -> None:
    print("\n[Harvey]")
    _export_reviewer("harvey", HARVEY_DIR, HARVEY_FT_DIR, SYSTEM_HARVEY, USER_HARVEY,
                     SYSTEM_HARVEY_MAUD, USER_HARVEY_MAUD)


def export_kira() -> None:
    print("\n[Kira]")
    _export_reviewer("kira", KIRA_DIR, KIRA_FT_DIR, SYSTEM_KIRA, USER_KIRA,
                     SYSTEM_KIRA_MAUD, USER_KIRA_MAUD)


def _export_reviewer(branch: str, src_dir: Path, ft_dir: Path,
                     system: str, user_tmpl: str,
                     maud_system: str, maud_user_tmpl: str) -> None:
    for split in SPLITS:
        rows  = load_jsonl(src_dir / f"{split}.jsonl")
        turns = []
        skipped = 0

        for row in rows:
            source = str(row.get("source", ""))
            if source == "maud":
                turn = build_maud_turn(row, maud_system, maud_user_tmpl)
            else:
                turn = build_reviewer_turn(row, system, user_tmpl)

            if turn is None:
                skipped += 1
            else:
                turns.append(turn)

        random.shuffle(turns)
        write_jsonl(turns, ft_dir / f"{split}.jsonl")

        empty = sum(1 for t in turns if '"findings": []' in t["messages"][2]["content"])
        print(f"  [{branch}] {split:5}: {len(rows):>7,} rows  {len(turns):,} turns "
              f"(skipped:{skipped} empty:{empty})")


def export_validator() -> None:
    print("\n[Validator]")
    for split in SPLITS:
        # Load ContractNLI base
        base_rows = load_jsonl(VALIDATOR_DIR / f"base_{split}.jsonl")
        # Load candidate findings (if available — produced by build_validator_candidates.py)
        cand_rows = load_jsonl(VALIDATOR_DIR / f"candidates_{split}.jsonl")

        all_rows = base_rows + cand_rows
        turns = []
        skipped = 0

        for row in all_rows:
            turn = build_validator_turn(row)
            if turn is None:
                skipped += 1
            else:
                turns.append(turn)

        random.shuffle(turns)
        write_jsonl(turns, VALIDATOR_FT_DIR / f"{split}.jsonl")

        dec = Counter(
            json.loads(t["messages"][2]["content"]).get("decision", "?")
            for t in turns
        )
        print(f"  [validator] {split:5}: {len(all_rows):>7,} rows  {len(turns):,} turns "
              f"(skipped:{skipped} retain:{dec.get('retain',0)} "
              f"reject:{dec.get('reject',0)} uncertain:{dec.get('uncertain',0)})")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["harvey", "kira", "validator", "all"],
                        default="all", help="Which branch to export")
    args = parser.parse_args()

    print("=" * 60)
    print("Export Branch Fine-Tuning Data")
    print("=" * 60)
    print(f"  Role: {args.role.upper()}")

    if args.role in ("harvey", "all"):
        export_harvey()
    if args.role in ("kira", "all"):
        export_kira()
    if args.role in ("validator", "all"):
        export_validator()

    print("\nDone.")
    if args.role in ("harvey", "all"):
        print(f"  Harvey FT data: {HARVEY_FT_DIR}")
    if args.role in ("kira", "all"):
        print(f"  Kira FT data:   {KIRA_FT_DIR}")
    if args.role in ("validator", "all"):
        print(f"  Validator FT:   {VALIDATOR_FT_DIR}")
    print("\nNext: python -m scripts.distill.train_gemma --role harvey --load-4bit")


if __name__ == "__main__":
    main()
