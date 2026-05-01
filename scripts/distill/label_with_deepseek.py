#!/usr/bin/env python3
"""
label_with_deepseek.py — Label raw Kira rows with DeepSeek.

Reads data/kira/raw/{split}.jsonl, calls DeepSeek API, writes
data/kira/labeled/{split}.jsonl with ds_* fields appended.

Checkpoints every 500 rows (resume-safe append mode).
Failed rows are kept with ds_labeled=False, ds_error=str(e).

Usage:
  python -m scripts.distill.label_with_deepseek --dry-run
  python -m scripts.distill.label_with_deepseek --split train
  python -m scripts.distill.label_with_deepseek --split train --workers 10
  python -m scripts.distill.label_with_deepseek --split all
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI

from scripts.distill.config import KIRA_RAW_DIR, KIRA_LABELED_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

CHECKPOINT_EVERY = 500

# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM = """You are a senior legal analyst at a top-tier law firm specializing in contract risk review.
Your job is to assess whether a contract clause creates material legal risk for the
party you represent, and if so, explain precisely why.

Use the following severity scale — assign based on actual clause language, not topic alone:
  CRITICAL — Existential risk: unlimited liability, loss of IP ownership, unilateral
             termination with no notice, automatic penalty clauses with no cap.
  HIGH     — Significant exposure: one-sided indemnification, broad IP assignment,
             uncapped consequential damages, automatic renewal with no opt-out.
  MEDIUM   — Moderate risk: ambiguous governing law, weak limitation of liability,
             unfavorable payment terms, non-compete with unclear scope.
  LOW      — Minor concern: boilerplate that could be improved but poses little
             real-world risk.

IMPORTANT: Do not assign HIGH or CRITICAL merely because the clause topic (e.g., governing
law, assignment, indemnification) appears in those examples. Severity must be based on
what the clause actually says."""

ISSUE_TYPES = (
    "liability_exposure | termination_risk | ip_risk | financial_obligation | "
    "restriction_clause | dispute_resolution | warranty_and_insurance | governance_risk | "
    "third_party_risk | compliance_obligation | confidentiality_risk | "
    "representation_risk | jurisdictional_risk"
)

JSON_SCHEMA = """{
  "issue_type": "<one of 13 types, or null if no material risk>",
  "severity": "<critical | high | medium | low>",
  "severity_rationale": "<1 sentence: which criterion above this meets, based on the actual clause language — not the topic category>",
  "what_is_wrong": "<2-3 sentences: what the clause does, why it is unfavorable, who bears the risk — or null if no material risk>",
  "worst_case": "<1 sentence: worst realistic outcome if enforced as written — or null>",
  "evidence_span": "<exact quoted text from the clause that creates the risk — or null>",
  "needs_full_contract": <true if the surrounding contract context is necessary to assess this clause correctly, false otherwise>
}"""

MAUD_JSON_SCHEMA = """{
  "issue_type": "<one of 13 types, or null>",
  "severity": "<critical | high | medium | low>",
  "severity_rationale": "<1 sentence based on actual clause language>",
  "what_is_wrong": "<2-3 sentences — or null if no material risk>",
  "worst_case": "<1 sentence — or null>",
  "evidence_span": "<exact quoted text from the passage — or null>",
  "needs_full_contract": false
}"""


def _build_cuad_user(row: dict, include_full_contract: bool = False) -> str:
    parts = []
    if include_full_contract and row.get("full_contract"):
        parts.append(f"[Full contract text for reference]\n{row['full_contract']}\n[End full contract]\n")
    parts.append(f"Contract: {row['contract_id']}")
    parts.append(f"Clause type: {row['clause_type']}")
    parts.append(f"Review question: {row['cuad_question']}")
    parts.append("")
    if row.get("left_context"):
        parts.append(f"Context before:\n{row['left_context']}")
    parts.append(f"--- CLAUSE ---\n{row['clause_text']}\n--- END CLAUSE ---")
    if row.get("right_context"):
        parts.append(f"Context after:\n{row['right_context']}")
    parts.append("")
    gt = row.get("ground_truth_spans") or []
    primary_span = gt[0] if gt else "(none provided)"
    parts.append(f"Confirmed relevant span: {primary_span}")
    parts.append("")
    parts.append(
        "Assess whether this clause creates material legal risk. If the clause is relevant but\n"
        "commercially standard or neutral, return no material risk.\n\n"
        f"13 issue types: {ISSUE_TYPES}\n\n"
        f"Return JSON only:\n{JSON_SCHEMA}"
    )
    return "\n".join(parts)


def _build_maud_user(row: dict) -> str:
    parts = [
        f"Contract: {row['contract_id']}",
        f"M&A category: {row.get('maud_category', '')}",
        f"Deal-point question: {row.get('maud_question', '')}",
        f"Attorney-verified answer: {row.get('maud_answer', '')}",
        "",
        f"--- PASSAGE ---\n{row['clause_text']}\n--- END PASSAGE ---",
        "",
        "The attorney-verified answer above is confirmed ground truth.\n"
        "Assess whether this deal point creates material legal risk. "
        f"Return JSON only:\n{MAUD_JSON_SCHEMA}",
    ]
    return "\n".join(parts)


# ── DeepSeek client ───────────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPSEEK_API_KEY not set in environment")
    return OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
    )


def _call_deepseek(client: OpenAI, model: str, messages: list) -> dict:
    for attempt in range(5):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.6,
                max_tokens=8000,
                reasoning_effort="high",
                extra_body={"thinking": {"type": "enabled"}},
            )
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                wait = 2 ** attempt
                log.warning("Rate limited — retrying in %ds (attempt %d/5)", wait, attempt + 1)
                time.sleep(wait)
                continue
            raise
        content = resp.choices[0].message.content
        if not content:
            finish = resp.choices[0].finish_reason
            raise ValueError(f"Empty response from DeepSeek (finish_reason={finish!r}) "
                             f"for model='{model}'")
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    raise RuntimeError("DeepSeek rate limit exceeded after 5 retries")


def label_row(client: OpenAI, model: str, row: dict) -> dict:
    """Label a single row. Two-step: context-window first, full-contract fallback."""
    row = dict(row)  # copy to avoid mutating caller's dict

    is_maud = row.get("source") == "maud"

    if is_maud:
        user_msg = _build_maud_user(row)
        parsed = _call_deepseek(client, model, [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": user_msg},
        ])
        parsed["needs_full_contract"] = False
    else:
        # Step 1: context-window-only call
        user_ctx = _build_cuad_user(row, include_full_contract=False)
        parsed = _call_deepseek(client, model, [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": user_ctx},
        ])

        # Step 2: full-contract fallback
        if parsed.get("needs_full_contract") and row.get("full_contract"):
            user_full = _build_cuad_user(row, include_full_contract=True)
            parsed = _call_deepseek(client, model, [
                {"role": "system", "content": SYSTEM},
                {"role": "user",   "content": user_full},
            ])

    ds_span = parsed.get("evidence_span") or ""
    ds_evidence_valid = bool(ds_span and ds_span in row["clause_text"])

    row.update({
        "ds_issue_type":          parsed.get("issue_type"),
        "ds_severity":            parsed.get("severity", "low"),
        "ds_severity_rationale":  parsed.get("severity_rationale", ""),
        "ds_what_is_wrong":       parsed.get("what_is_wrong"),
        "ds_worst_case":          parsed.get("worst_case"),
        "ds_evidence_span":       ds_span,
        "ds_evidence_valid":      ds_evidence_valid,
        "ds_used_full_contract":  bool(parsed.get("needs_full_contract")),
        "ds_labeled":             True,
    })
    return row


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def _load_labeled(path: Path) -> set[str]:
    """Return set of already-labeled row IDs from an existing output file."""
    done: set[str] = set()
    if not path.exists():
        return done
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("id"):
                    done.add(r["id"])
            except json.JSONDecodeError:
                pass
    return done


def _load_raw(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── Main labeling loop ────────────────────────────────────────────────────────

def process_split(split: str, dry_run: bool = False, workers: int = 1, limit: int = 0) -> None:
    raw_path     = KIRA_RAW_DIR     / f"{split}.jsonl"
    labeled_path = KIRA_LABELED_DIR / f"{split}.jsonl"

    if not raw_path.exists():
        log.warning("Raw file not found: %s", raw_path)
        return

    KIRA_LABELED_DIR.mkdir(parents=True, exist_ok=True)

    rows      = _load_raw(raw_path)
    already   = _load_labeled(labeled_path)
    remaining = [r for r in rows if r.get("id") not in already]

    if limit:
        remaining = remaining[:limit]

    log.info(
        "Split=%s  total=%d  already_labeled=%d  remaining=%d  workers=%d",
        split, len(rows), len(already), len(remaining), workers,
    )

    if dry_run:
        sample = remaining[:5]
        log.info("=== DRY RUN — 5 rows ===")
        client = _get_client()
        model  = os.environ["DEEPSEEK_MODEL"]
        for row in sample:
            try:
                labeled = label_row(client, model, row)
                log.info("ROW %s: severity=%s issue=%s valid=%s",
                         labeled["id"], labeled["ds_severity"],
                         labeled["ds_issue_type"], labeled["ds_evidence_valid"])
                print(json.dumps(labeled, indent=2, ensure_ascii=False))
            except Exception as e:
                log.error("Error on %s: %s", row.get("id"), e)
        return

    model  = os.environ["DEEPSEEK_MODEL"]
    client = _get_client()

    buffer: list[dict] = []
    lock    = threading.Lock()
    labeled = 0
    skipped = 0
    done    = 0

    def _flush(buf: list[dict]) -> None:
        if not buf:
            return
        with open(labeled_path, "a", encoding="utf-8") as f:
            for r in buf:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _process(row: dict) -> dict:
        return label_row(client, model, row)

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process, row): row for row in remaining}
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as e:
                    log.error("Skipping row (will retry next run): %s", e)
                    with lock:
                        skipped += 1
                        done += 1
                    continue
                with lock:
                    buffer.append(result)
                    labeled += 1
                    done += 1

                    if len(buffer) >= CHECKPOINT_EVERY:
                        _flush(buffer)
                        buffer.clear()
                        log.info("Checkpoint: %d/%d done  labeled=%d  skipped=%d",
                                 done, len(remaining), labeled, skipped)
    except KeyboardInterrupt:
        log.info("Interrupted — flushing buffer (%d rows)...", len(buffer))
    finally:
        with lock:
            _flush(buffer)
            buffer.clear()

    log.info("Split=%s done. Labeled=%d  Skipped=%d", split, labeled, skipped)

    # Report full-contract usage rate
    all_labeled = _load_raw(labeled_path)
    used_full = sum(1 for r in all_labeled if r.get("ds_used_full_contract"))
    ds_labeled_rows = [r for r in all_labeled if r.get("ds_labeled")]
    log.info(
        "ds_used_full_contract rate: %.1f%% (%d/%d)",
        100 * used_full / max(len(ds_labeled_rows), 1),
        used_full, len(ds_labeled_rows),
    )



# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Label Kira raw rows with DeepSeek")
    parser.add_argument("--split",   default="train", choices=["train", "val", "test", "all"])
    parser.add_argument("--dry-run", action="store_true", help="Label 5 rows and print, no write")
    parser.add_argument("--workers", type=int, default=10,
                        help="Number of parallel API calls (default: 10)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap processing to N rows (0 = no limit, for testing)")
    args = parser.parse_args()

    if not os.getenv("DEEPSEEK_API_KEY"):
        sys.exit("DEEPSEEK_API_KEY not set. Add it to your .env and source it.")
    if not os.getenv("DEEPSEEK_MODEL"):
        sys.exit("DEEPSEEK_MODEL not set. Add it to your .env and source it.")

    splits = ["train", "val", "test"] if args.split == "all" else [args.split]
    for s in splits:
        process_split(s, dry_run=args.dry_run, workers=args.workers, limit=args.limit)


if __name__ == "__main__":
    main()
