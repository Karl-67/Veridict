#!/usr/bin/env python3
"""
build_batches.py — Build OpenAI Batch API input files from curated datasets.

Reads:
  data/curated/dataset_a/reviewer_{train,val,test}.jsonl   → reviewer clauses
  data/curated/dataset_b/validator_{train,val,test}.jsonl  → NLI pairs
  data/material/sec_contracts.parquet                      → full SEC contracts

Outputs:
  data/distillation/batches/reviewer_batch_{n}.jsonl
  data/distillation/batches/validator_batch_{n}.jsonl
  data/distillation/batches/sec_batch_{n}.jsonl
  data/distillation/batches/manifest.json

Deduplication:
  Reviewer — unique by sha256(clause_text). Multiple rows sharing the same
  clause_text (3 roles × same clause) get one GPT call; results join by hash.
  Validator — each (premise, hypothesis) pair is unique; no dedup needed.
  SEC       — each chunk is unique by (row_index, chunk_index).
"""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from .config import (
    BATCH_MAX_REQUESTS,
    BATCHES_DIR,
    CURATED_DIR,
    DISTILL_DIR,
    MAX_OUTPUT_TOKENS,
    SEC_CHUNK_OVERLAP_WORDS,
    SEC_CHUNK_WORDS,
    SEC_FILE,
    TEACHER_CLAUSE,
    TEACHER_CONTRACT,
)
from .prompts import (
    SYSTEM_CLAUSE,
    SYSTEM_CONTRACT,
    SYSTEM_NLI,
    USER_CLAUSE,
    USER_CONTRACT,
    USER_NLI,
)



# ── Helpers ───────────────────────────────────────────────────────────────────


def text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def make_request(custom_id: str, model: str, system: str, user: str) -> dict:
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": MAX_OUTPUT_TOKENS,
            "temperature": 0,
        },
    }


def write_batch_files(
    requests: list[dict], prefix: str
) -> list[str]:
    """Write requests into chunk files of BATCH_MAX_REQUESTS each. Returns file paths."""
    paths = []
    for i in range(0, max(1, len(requests)), BATCH_MAX_REQUESTS):
        chunk = requests[i : i + BATCH_MAX_REQUESTS]
        out = BATCHES_DIR / f"{prefix}_batch_{i // BATCH_MAX_REQUESTS}.jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for req in chunk:
                f.write(json.dumps(req, ensure_ascii=False) + "\n")
        print(f"  {out.name}: {len(chunk):,} requests")
        paths.append(str(out))
    return paths


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── Reviewer (Dataset A) ──────────────────────────────────────────────────────


def build_reviewer_batches() -> tuple[list[str], dict]:
    """
    Returns (batch_file_paths, hash_to_meta) where hash_to_meta maps
    each text_hash → {issue_type, first_id} for joining results back.
    """
    all_rows: list[dict] = []
    for split in ("train", "val", "test"):
        p = CURATED_DIR / "dataset_a" / f"reviewer_{split}.jsonl"
        if p.exists():
            all_rows.extend(load_jsonl(p))

    if not all_rows:
        print("  [reviewer] No curated Dataset A found — skipping.")
        return [], {}

    # Deduplicate by clause_text — one GPT call per unique clause
    seen: set[str] = set()
    requests: list[dict] = []
    hash_to_meta: dict[str, dict] = {}

    for row in all_rows:
        clause = str(row.get("clause_text", "")).strip()
        if not clause:
            continue
        h = text_hash(clause)
        if h in seen:
            continue
        seen.add(h)

        issue_type = row.get("issue_type", "unknown")
        custom_id = f"rev_{h}"
        user_msg = USER_CLAUSE.format(issue_type=issue_type, clause_text=clause)
        requests.append(make_request(custom_id, TEACHER_CLAUSE, SYSTEM_CLAUSE, user_msg))
        hash_to_meta[h] = {"issue_type": issue_type, "first_id": row.get("id", "")}

    print(f"  [reviewer] {len(all_rows):,} rows → {len(requests):,} unique clauses")
    paths = write_batch_files(requests, "reviewer")
    return paths, hash_to_meta


# ── Validator (Dataset B) ─────────────────────────────────────────────────────


def build_validator_batches() -> list[str]:
    all_rows: list[dict] = []
    for split in ("train", "val", "test"):
        p = CURATED_DIR / "dataset_b" / f"validator_{split}.jsonl"
        if p.exists():
            all_rows.extend(load_jsonl(p))

    if not all_rows:
        print("  [validator] No curated Dataset B found — skipping.")
        return []

    requests: list[dict] = []
    for row in all_rows:
        premise = str(row.get("premise", "")).strip()
        hypothesis = str(row.get("hypothesis", "")).strip()
        if not premise or not hypothesis:
            continue
        custom_id = f"val_{row.get('id', text_hash(premise + hypothesis))}"
        user_msg = USER_NLI.format(premise=premise, hypothesis=hypothesis)
        requests.append(make_request(custom_id, TEACHER_CLAUSE, SYSTEM_NLI, user_msg))

    print(f"  [validator] {len(all_rows):,} rows → {len(requests):,} requests")
    return write_batch_files(requests, "validator")


# ── SEC contracts ─────────────────────────────────────────────────────────────


def chunk_text(text: str, chunk_words: int, overlap_words: int) -> list[str]:
    words = text.split()
    chunks = []
    step = chunk_words - overlap_words
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_words])
        if chunk.strip():
            chunks.append(chunk)
        if start + chunk_words >= len(words):
            break
    return chunks


def build_sec_batches() -> list[str]:
    if not SEC_FILE.exists():
        print("  [sec] sec_contracts.parquet not found — skipping.")
        return []

    df = pd.read_parquet(SEC_FILE)
    df = df[df["full_text"].notna()]
    df = df[df["full_text"].str.split().str.len() >= 100].reset_index(drop=True)

    requests: list[dict] = []
    chunk_map: list[dict] = []   # saved so export_gemma can reconstruct user prompts

    for row_idx, row in df.iterrows():
        full_text = str(row["full_text"])
        chunks = chunk_text(full_text, SEC_CHUNK_WORDS, SEC_CHUNK_OVERLAP_WORDS)
        for chunk_idx, chunk in enumerate(chunks):
            custom_id = f"sec_{row_idx}_{chunk_idx}"
            user_msg = USER_CONTRACT.format(chunk_text=chunk)
            requests.append(
                make_request(custom_id, TEACHER_CONTRACT, SYSTEM_CONTRACT, user_msg)
            )
            chunk_map.append({"custom_id": custom_id, "chunk_text": chunk})

    # Persist chunk texts so parse_results can attach them to annotated rows
    chunk_map_path = BATCHES_DIR / "sec_chunk_map.jsonl"
    with open(chunk_map_path, "w", encoding="utf-8") as f:
        for entry in chunk_map:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"  [sec] {len(df):,} contracts → {len(requests):,} chunks  (chunk map → {chunk_map_path.name})")
    return write_batch_files(requests, "sec")


# ── Manifest ──────────────────────────────────────────────────────────────────


def save_manifest(
    reviewer_paths: list[str],
    reviewer_hash_meta: dict,
    validator_paths: list[str],
    sec_paths: list[str],
) -> None:
    manifest = {
        "reviewer": {
            "batch_files": reviewer_paths,
            "model": TEACHER_CLAUSE,
            "hash_to_meta": reviewer_hash_meta,
        },
        "validator": {
            "batch_files": validator_paths,
            "model": TEACHER_CLAUSE,
        },
        "sec": {
            "batch_files": sec_paths,
            "model": TEACHER_CONTRACT,
        },
    }
    out = BATCHES_DIR / "manifest.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n  Manifest → {out}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 60)
    print("Build Batches")
    print("=" * 60)

    print("\n[Reviewer — Dataset A]")
    reviewer_paths, reviewer_hash_meta = build_reviewer_batches()

    print("\n[Validator — Dataset B]")
    validator_paths = build_validator_batches()

    print("\n[SEC Contracts]")
    sec_paths = build_sec_batches()

    save_manifest(reviewer_paths, reviewer_hash_meta, validator_paths, sec_paths)

    total_files = len(reviewer_paths) + len(validator_paths) + len(sec_paths)
    print(f"\nDone. {total_files} batch file(s) written to {BATCHES_DIR}")
    print("Next: python -m scripts.distill.submit_batches")


if __name__ == "__main__":
    main()
