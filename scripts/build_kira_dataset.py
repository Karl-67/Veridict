#!/usr/bin/env python3
"""
build_kira_dataset.py — Build raw CUAD + MAUD rows for Kira fine-tuning.

Outputs:
  data/kira/raw/{train,val,test}.jsonl

Usage:
  python -m scripts.build_kira_dataset
"""

import hashlib
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

CUAD_QA_FILE  = DATA_DIR / "atticus" / "cuad.parquet"
CUAD_CL_FILE  = DATA_DIR / "atticus" / "cuad_clauses.parquet"
MAUD_FILE     = DATA_DIR / "maud"    / "maud.parquet"
OUT_DIR       = DATA_DIR / "kira"    / "raw"

TRAIN_FRAC = 0.70
VAL_FRAC   = 0.15
# TEST_FRAC  = 0.15 (remainder)

MAX_CTX_CHARS = 600   # per side
CTX_SENTENCES  = 8

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()[:16]


def _wc(text: str) -> int:
    return len(text.split())


_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Simple sentence splitter on .!? boundaries."""
    return [s.strip() for s in _SENT_RE.split(text) if s.strip()]


def _extract_context(full_text: str, clause_text: str, n_sents: int, max_chars: int) -> tuple[str, str]:
    """
    Find clause_text in full_text, extract ±n_sents sentences on each side.
    Returns (left_context, right_context), each capped at max_chars.
    """
    pos = full_text.find(clause_text)
    if pos == -1:
        return "", ""

    before = full_text[:pos]
    after  = full_text[pos + len(clause_text):]

    left_sents  = _split_sentences(before)[-n_sents:]
    right_sents = _split_sentences(after)[:n_sents]

    left  = " ".join(left_sents)[-max_chars:]
    right = " ".join(right_sents)[:max_chars]
    return left, right


def _extract_category(question: str) -> str:
    """Extract human-readable category name from CUAD question string."""
    m = re.search(r'"([^"]+)"', question)
    return m.group(1) if m else question[:60]


# ── CUAD ──────────────────────────────────────────────────────────────────────

def build_cuad_rows() -> list[dict]:
    log.info("Loading cuad_clauses.parquet …")
    clauses = pd.read_parquet(CUAD_CL_FILE)
    # clause_type column holds the full question string
    clauses = clauses.rename(columns={"contract_title": "contract_id"})
    before = len(clauses)
    clauses = clauses.drop_duplicates(subset=["contract_id", "clause_text"])
    clauses = clauses[clauses["clause_text"].apply(_wc) >= 10]
    log.info("cuad_clauses: %d → %d rows after dedup+filter", before, len(clauses))

    log.info("Loading cuad.parquet …")
    qa = pd.read_parquet(CUAD_QA_FILE)
    # Build index: (title, question) → list of all span texts
    span_index: dict[tuple, list[str]] = defaultdict(list)
    for _, row in qa.iterrows():
        if row["is_impossible"]:
            continue
        ans = row["answers"]
        spans = list(ans["text"]) if isinstance(ans, dict) else []
        key = (row["title"], row["question"])
        span_index[key].extend(spans)

    log.info("Built span index with %d (title, question) keys", len(span_index))

    rows = []
    missing_q = 0
    for _, cl in clauses.iterrows():
        contract_id = cl["contract_id"]
        question    = cl["clause_type"]   # full question string = cuad_question
        clause_text = cl["clause_text"]
        full_ctx    = cl["context"] if pd.notna(cl.get("context", None)) else ""

        key = (contract_id, question)
        gt_spans = span_index.get(key, [])
        if not gt_spans:
            # Still keep the row — some clauses are "is_impossible"
            missing_q += 1

        left_ctx, right_ctx = _extract_context(full_ctx, clause_text, CTX_SENTENCES, MAX_CTX_CHARS)

        rows.append({
            "id":                 f"cuad_{_sha1(contract_id + '|' + clause_text)}",
            "source":             "cuad",
            "contract_id":        contract_id,
            "clause_type":        _extract_category(question),
            "clause_text":        clause_text,
            "cuad_question":      question,
            "ground_truth_spans": gt_spans,
            "left_context":       left_ctx,
            "right_context":      right_ctx,
            "full_contract":      full_ctx,   # DS fallback only — not in Gemma export
        })

    log.info("CUAD rows built: %d  (missing GT spans: %d)", len(rows), missing_q)
    return rows


def split_cuad(rows: list[dict]) -> dict[str, list[dict]]:
    """Document-level split: same contract_id never crosses splits."""
    contracts = sorted({r["contract_id"] for r in rows})
    n = len(contracts)
    n_train = int(n * TRAIN_FRAC)
    n_val   = int(n * VAL_FRAC)

    train_contracts = set(contracts[:n_train])
    val_contracts   = set(contracts[n_train : n_train + n_val])
    test_contracts  = set(contracts[n_train + n_val :])

    splits: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for r in rows:
        cid = r["contract_id"]
        if cid in train_contracts:
            r["split"] = "train"
            splits["train"].append(r)
        elif cid in val_contracts:
            r["split"] = "val"
            splits["val"].append(r)
        else:
            r["split"] = "test"
            splits["test"].append(r)

    log.info(
        "CUAD split → train=%d val=%d test=%d (contracts: train=%d val=%d test=%d)",
        len(splits["train"]), len(splits["val"]), len(splits["test"]),
        len(train_contracts), len(val_contracts), len(test_contracts),
    )

    # Warn on severely skewed clause-type distribution
    _check_clause_skew(splits)
    return splits


def _check_clause_skew(splits: dict[str, list[dict]]) -> None:
    from collections import Counter
    for split_name, rows in splits.items():
        counts = Counter(r["clause_type"] for r in rows)
        if not counts:
            continue
        vals = list(counts.values())
        ratio = max(vals) / (min(vals) + 1)
        if ratio > 10:
            log.warning(
                "Clause-type skew in %s: max/min ratio=%.1f (most common=%s)",
                split_name, ratio, counts.most_common(1)[0][0],
            )


# ── MAUD ──────────────────────────────────────────────────────────────────────

def build_maud_rows() -> dict[str, list[dict]]:
    log.info("Loading maud.parquet …")
    maud = pd.read_parquet(MAUD_FILE)
    before = len(maud)
    maud["wc"] = maud["text"].apply(_wc)
    maud = maud[(maud["wc"] >= 10) & (maud["wc"] <= 600)]
    log.info("MAUD: %d → %d rows after word-count filter", before, len(maud))

    # Official splits: train / validation / test → rename validation → val
    split_map = {"train": "train", "validation": "val", "test": "test"}

    splits: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for _, row in maud.iterrows():
        split_key = split_map.get(row["split"], "test")
        record = {
            "id":             f"maud_{row['id']}",
            "source":         "maud",
            "split":          split_key,
            "contract_id":    row["contract_name"],
            "clause_type":    row["text_type"],
            "maud_category":  row["category"],
            "clause_text":    row["text"],
            "maud_question":  row["question"],
            "maud_answer":    row["answer"],
            "left_context":   "",
            "right_context":  "",
            "full_contract":  "",
        }
        splits[split_key].append(record)

    log.info(
        "MAUD split → train=%d val=%d test=%d",
        len(splits["train"]), len(splits["val"]), len(splits["test"]),
    )
    return splits


# ── Write ─────────────────────────────────────────────────────────────────────

def write_splits(combined: dict[str, list[dict]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for split_name, rows in combined.items():
        out_path = OUT_DIR / f"{split_name}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        log.info("Wrote %d rows → %s", len(rows), out_path)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    cuad_rows   = build_cuad_rows()
    cuad_splits = split_cuad(cuad_rows)
    maud_splits = build_maud_rows()

    combined: dict[str, list[dict]] = {}
    for split in ("train", "val", "test"):
        combined[split] = cuad_splits[split] + maud_splits[split]
        log.info("Combined %s: %d rows (%d CUAD + %d MAUD)",
                 split, len(combined[split]),
                 len(cuad_splits[split]), len(maud_splits[split]))

    write_splits(combined)
    log.info("Done. Raw dataset written to %s", OUT_DIR)


if __name__ == "__main__":
    main()
