#!/usr/bin/env python3
"""
build_context_windows.py — Phase 2 of the branch training pipeline.

Enriches normalized JSONL files with real left_context and right_context
extracted from source parquets.

Sources:
  CUAD  — cuad_clauses.parquet has a 'context' field (full contract text).
           We locate clause_text within context and extract ±CONTEXT_SENTENCES sentences.
  LEDGAR — no surrounding context; left/right remain empty strings.
  MAUD  — passage is already full_local_context; left/right set to "".
  ContractNLI — premise is full_local_context; no surrounding text available.

Reads:  data/curated/normalized/{harvey,kira,validator,maud}_{train,val,test}.jsonl
Writes: same files in-place (overwrites left_context, right_context, full_local_context)

Run: python -m scripts.build_context_windows
"""

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
NORM_DIR = DATA_DIR / "curated" / "normalized"
CUAD_CLAUSES_FILE = DATA_DIR / "atticus" / "cuad_clauses.parquet"

CONTEXT_SENTENCES = 3     # sentences to include on each side of the clause
MAX_CONTEXT_CHARS = 600   # hard cap per side to prevent token bloat
ROLES = ("harvey", "kira", "validator", "maud")
SPLITS = ("train", "val", "test")


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
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ── Sentence splitter ─────────────────────────────────────────────────────────

def split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation followed by whitespace."""
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]


# ── Context extraction ────────────────────────────────────────────────────────

def extract_context(full_text: str, clause: str,
                    n: int = CONTEXT_SENTENCES) -> tuple[str, str]:
    """
    Locate clause in full_text and return (left_context, right_context).
    Returns ("", "") when clause cannot be located.
    """
    clause_clean = clause.strip()
    if not clause_clean or not full_text:
        return "", ""

    # Try exact match first
    idx = full_text.find(clause_clean)

    # Fall back to leading 120-char snippet (case-insensitive)
    if idx == -1:
        snippet = clause_clean[:120].lower()
        idx = full_text.lower().find(snippet)
        if idx != -1:
            # Advance idx to the real start
            pass

    if idx == -1:
        return "", ""

    left_raw  = full_text[:idx].strip()
    right_raw = full_text[idx + len(clause_clean):].strip()

    left_sents  = split_sentences(left_raw)
    right_sents = split_sentences(right_raw)

    left  = " ".join(left_sents[-n:])[-MAX_CONTEXT_CHARS:]
    right = " ".join(right_sents[:n])[:MAX_CONTEXT_CHARS]

    return left.strip(), right.strip()


def build_full_local_context(left: str, clause: str, right: str) -> str:
    parts = [p for p in [left, clause, right] if p]
    return "\n".join(parts)


# ── CUAD index ────────────────────────────────────────────────────────────────

def build_cuad_index() -> dict[str, str]:
    """
    Returns {clause_text → full_contract_context} from cuad_clauses.parquet.
    When a clause_text appears in multiple contracts, the last one wins
    (acceptable: context window content is structurally similar).
    """
    if not CUAD_CLAUSES_FILE.exists():
        print(f"  [WARN] {CUAD_CLAUSES_FILE} not found — CUAD context unavailable")
        return {}

    df = pd.read_parquet(CUAD_CLAUSES_FILE)
    index: dict[str, str] = {}
    # Primary key: (contract_title, clause_text) → context
    titled: dict[tuple[str, str], str] = {}
    for _, r in df.iterrows():
        ct  = str(r["contract_title"]).strip()
        cl  = str(r["clause_text"]).strip()
        ctx = str(r.get("context", ""))
        titled[(ct, cl)] = ctx
        index[cl] = ctx          # fallback: clause_text only

    print(f"  [CUAD index] {len(index):,} clause entries  ({len(titled):,} titled)")
    return index, titled


# ── Row enrichment ────────────────────────────────────────────────────────────

def enrich_rows(rows: list[dict],
                cuad_by_clause: dict[str, str],
                cuad_by_title:  dict[tuple[str, str], str]) -> tuple[list[dict], int, int]:
    hits = misses = 0

    for row in rows:
        source      = str(row.get("source", ""))
        clause_text = str(row.get("clause_text") or row.get("premise", "")).strip()

        if source == "cuad" and clause_text:
            contract_id = str(row.get("contract_id", "")).strip()
            # Try titled lookup first, then clause-only fallback
            context = cuad_by_title.get((contract_id, clause_text), "") or \
                      cuad_by_clause.get(clause_text, "")

            if context:
                left, right = extract_context(context, clause_text)
                row["left_context"]       = left
                row["right_context"]      = right
                row["full_local_context"] = build_full_local_context(left, clause_text, right)
                hits += 1
            else:
                # Keep existing (clause_text only)
                row.setdefault("left_context",  "")
                row.setdefault("right_context", "")
                row.setdefault("full_local_context", clause_text)
                misses += 1

        elif source == "maud":
            # Passage already is the context
            passage = str(row.get("passage") or row.get("full_local_context", clause_text)).strip()
            row["left_context"]       = ""
            row["right_context"]      = ""
            row["full_local_context"] = passage
            hits += 1

        elif source == "contractnli":
            premise = str(row.get("premise", clause_text)).strip()
            row["left_context"]       = ""
            row["right_context"]      = ""
            row["full_local_context"] = premise
            hits += 1

        else:
            # LEDGAR and others — no context source
            row.setdefault("left_context",  "")
            row.setdefault("right_context", "")
            row.setdefault("full_local_context", clause_text)
            misses += (1 if clause_text else 0)

    return rows, hits, misses


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Build Context Windows")
    print("=" * 60)

    cuad_by_clause, cuad_by_title = build_cuad_index()

    total_hits = total_misses = 0

    for role in ROLES:
        for split in SPLITS:
            path = NORM_DIR / f"{role}_{split}.jsonl"
            rows = load_jsonl(path)
            if not rows:
                continue
            enriched, hits, misses = enrich_rows(rows, cuad_by_clause, cuad_by_title)
            write_jsonl(enriched, path)
            total_hits   += hits
            total_misses += misses
            rate = hits / (hits + misses) * 100 if (hits + misses) else 0
            print(f"  {role}_{split}: {len(rows):>7,} rows — hits:{hits:,} misses:{misses:,} ({rate:.0f}%)")

    total = total_hits + total_misses
    pct = total_hits / total * 100 if total else 0
    print(f"\n  Overall context hit rate: {total_hits:,}/{total:,} ({pct:.1f}%)")
    print("\nDone. Run build_branch_datasets.py next.")


if __name__ == "__main__":
    main()
