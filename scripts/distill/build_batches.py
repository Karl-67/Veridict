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
  Reviewer — unique by sha256(clause_text + contract_id). Multiple rows sharing
  the same (clause_text, contract_id) pair get one GPT call; results join by
  hash. LEDGAR rows (no full contract available) fall back to clause-only context.
  Validator — each (premise, hypothesis) pair is unique; no dedup needed.
  SEC       — each chunk is unique by (row_index, chunk_index).

Options:
  --contracts-path PATH  Path to CUAD_v1.json or a contracts.jsonl file mapping
                         contract_id → full text.
                         Default: data/atticus/CUAD_v1.json
  --dry-run              Estimate input token counts per batch and exit without
                         writing any files.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from .config import (
    BATCH_MAX_REQUESTS,
    BATCHES_DIR,
    CURATED_DIR,
    DATA_DIR,
    DISTILL_DIR,
    MAX_OUTPUT_TOKENS,
    SEC_CHUNK_OVERLAP_WORDS,
    SEC_CHUNK_WORDS,
    SEC_FILE,
    TEACHER_CLAUSE,
    TEACHER_CONTRACT,
)
from .prompts import (
    SYSTEM_CONTRACT,
    SYSTEM_NLI,
    USER_CONTRACT,
    USER_NLI,
)

DEFAULT_CONTRACTS_PATH = DATA_DIR / "atticus" / "CUAD_v1.json"

# ── Context-aware reviewer prompts ────────────────────────────────────────────

SYSTEM_CLAUSE_WITH_CONTEXT = (
    "You are an expert contract lawyer specializing in mixed contract types "
    "(NDA, Employment, M&A, Commercial, Lease, Service Agreements). "
    "You will be given a full contract for context and a specific clause to evaluate. "
    "Your tasks: (1) identify the contract type; (2) evaluate the target clause "
    "IN THE CONTEXT of the full contract; (3) return a JSON object. "
    "Be especially alert to: defined terms in the clause that are defined elsewhere "
    "in the contract; clauses that appear reasonable alone but conflict with other "
    "provisions; missing standard protections given the contract type; "
    "jurisdiction-specific issues if governing law is stated. "
    "Return valid JSON only. No text outside the JSON object."
)

USER_CLAUSE_WITH_CONTEXT = """\
{contract_block}

---

TARGET CLAUSE (evaluate the following clause in the context above):
Category: {issue_type}
Clause text:
{clause_text}

Return this JSON schema exactly:
{{
  "contract_type": "<one of: NDA, Employment, M&A, Commercial, Lease, Service Agreement, Other>",
  "risk_score": <integer 1-10, where 10 is highest risk>,
  "legal_analysis": "<detailed explanation of legal issues, 2-4 sentences>",
  "inconsistencies": ["<conflict with another clause, if any — empty list if none>"],
  "severity": "<one of: critical, high, medium, low>",
  "severity_confidence": "<strong or weak>",
  "recommendations": "<specific redline or negotiation guidance, 1-3 sentences>"
}}

Risk score guide:
  1-2  = standard boilerplate, no exploitable risk
  3-4  = minor ambiguity, manageable with good faith
  5-6  = significant gap or scope that favors counterparty
  7-8  = clause actively disadvantages the client or enables material harm
  9-10 = critical defect — severe financial, legal, or operational exposure

Severity (independent of risk_score, based on consequence type):
  critical = severe structural defect, recommend rejection
  high     = material exposure, must redline before signing
  medium   = worth flagging in review
  low      = informational, no negotiation required

When in doubt, score higher."""


# ── Contract text store ───────────────────────────────────────────────────────


class ContractStore:
    """Map contract_id → full contract text.

    Supports two source formats:
      CUAD_v1.json  : {"data": [{"title": ..., "paragraphs": [{"context": ...}]}]}
      contracts.jsonl: one JSON object per line with "contract_id"/"id" and
                       "text"/"full_text" fields.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._store: dict[str, str] = {}
        if path is None or not path.exists():
            if path is not None:
                print(f"  [ContractStore] WARNING: {path} not found — all clauses use isolation fallback.")
            return
        if path.suffix == ".json":
            self._load_cuad_json(path)
        else:
            self._load_jsonl(path)

    def _load_cuad_json(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("data", []):
            title = str(item.get("title", "")).strip()
            paragraphs = item.get("paragraphs", [])
            if title and paragraphs:
                self._store[title] = str(paragraphs[0].get("context", ""))
        print(f"  [ContractStore] {len(self._store):,} contracts loaded from {path.name}")

    def _load_jsonl(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                cid = str(obj.get("contract_id", obj.get("id", ""))).strip()
                text = str(obj.get("text", obj.get("full_text", ""))).strip()
                if cid and text:
                    self._store[cid] = text
        print(f"  [ContractStore] {len(self._store):,} contracts loaded from {path.name}")

    def get(self, contract_id: str) -> str | None:
        return self._store.get(str(contract_id).strip())

    def __len__(self) -> int:
        return len(self._store)


# ── Helpers ───────────────────────────────────────────────────────────────────

# Clauses that reference sections, exhibits, or defined terms from a parent
# contract they are not accompanied by cannot be reliably evaluated in isolation.
# These patterns identify unresolvable cross-references.
CROSS_REF_RE = re.compile(
    r"\bSection\s+\d"
    r"|\bArticle\s+\d"
    r"|\bExhibit\s+[A-Z]"
    r"|\bSchedule\s+[A-Z0-9]"
    r"|\bas\s+defined\b"
    r"|\bhereinafter\b",
    re.IGNORECASE,
)


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


def write_batch_files(requests: list[dict], prefix: str) -> list[str]:
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


def _print_token_estimate(requests: list[dict], label: str) -> None:
    if not requests:
        return
    total_chars = sum(
        len(r["body"]["messages"][0]["content"]) + len(r["body"]["messages"][1]["content"])
        for r in requests
    )
    total_est = total_chars // 4
    avg_est = total_est // len(requests)
    print(
        f"  [{label}] {len(requests):,} requests — "
        f"total input ≈ {total_est:,} tokens  avg ≈ {avg_est:,} tokens/call"
    )


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── Reviewer (Dataset A) ──────────────────────────────────────────────────────


def build_reviewer_batches(
    contracts_path: Path | None = None,
    dry_run: bool = False,
) -> tuple[list[str], dict]:
    """
    Returns (batch_file_paths, hash_to_meta).

    Cache key: sha256(clause_text + contract_id) — one GPT call per unique
    (clause, contract) pair, covering all 3 role-expanded rows for that pair.
    Clauses whose contract is not found in the store are evaluated in isolation
    with the same new output schema (contract_type field will reflect best guess).
    """
    all_rows: list[dict] = []
    for split in ("train", "val", "test"):
        p = CURATED_DIR / "dataset_a" / f"reviewer_{split}.jsonl"
        if p.exists():
            all_rows.extend(load_jsonl(p))

    if not all_rows:
        print("  [reviewer] No curated Dataset A found — skipping.")
        return [], {}

    store = ContractStore(contracts_path)
    store_miss = 0
    cross_ref_dropped = 0

    seen: set[str] = set()
    requests: list[dict] = []
    hash_to_meta: dict[str, dict] = {}

    for row in all_rows:
        clause = str(row.get("clause_text", "")).strip()
        if not clause:
            continue

        contract_id = str(row.get("contract_id", "")).strip()
        # Include contract_id in the hash so the same clause in different
        # contracts gets independent evaluations with separate context.
        h = text_hash(clause + contract_id)

        if h in seen:
            continue
        seen.add(h)

        issue_type = row.get("issue_type", "unknown")
        custom_id = f"rev_{h}"

        full_text = store.get(contract_id) if contract_id else None
        if full_text:
            contract_block = f"FULL CONTRACT:\n{full_text}"
        else:
            # Drop clauses that reference sections, exhibits, or defined terms
            # from a contract we don't have — they cannot be meaningfully scored
            # in isolation.
            if CROSS_REF_RE.search(clause):
                cross_ref_dropped += 1
                continue
            contract_block = (
                "[Note: Full contract text unavailable — evaluate clause in isolation.]"
            )
            store_miss += 1

        user_msg = USER_CLAUSE_WITH_CONTEXT.format(
            contract_block=contract_block,
            issue_type=issue_type,
            clause_text=clause,
        )
        requests.append(
            make_request(custom_id, TEACHER_CLAUSE, SYSTEM_CLAUSE_WITH_CONTEXT, user_msg)
        )
        hash_to_meta[h] = {"issue_type": issue_type, "first_id": row.get("id", "")}

    n_with_context = len(requests) - store_miss
    print(
        f"  [reviewer] {len(all_rows):,} rows → {len(requests):,} unique (clause, contract) pairs  "
        f"({n_with_context:,} with full context, {store_miss:,} isolation fallback, "
        f"{cross_ref_dropped:,} dropped — unresolvable cross-references)"
    )

    if dry_run:
        _print_token_estimate(requests, "reviewer")
        return [], {}

    paths = write_batch_files(requests, "reviewer")
    return paths, hash_to_meta


# ── Validator (Dataset B) ─────────────────────────────────────────────────────


def build_validator_batches(dry_run: bool = False) -> list[str]:
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

    if dry_run:
        _print_token_estimate(requests, "validator")
        return []

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


def build_sec_batches(dry_run: bool = False) -> list[str]:
    if not SEC_FILE.exists():
        print("  [sec] sec_contracts.parquet not found — skipping.")
        return []

    df = pd.read_parquet(SEC_FILE)
    df = df[df["full_text"].notna()]
    df = df[df["full_text"].str.split().str.len() >= 100].reset_index(drop=True)

    requests: list[dict] = []
    chunk_map: list[dict] = []

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

    print(f"  [sec] {len(df):,} contracts → {len(requests):,} chunks")

    if dry_run:
        _print_token_estimate(requests, "sec")
        return []

    chunk_map_path = BATCHES_DIR / "sec_chunk_map.jsonl"
    with open(chunk_map_path, "w", encoding="utf-8") as f:
        for entry in chunk_map:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"  chunk map → {chunk_map_path.name}")

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
    parser = argparse.ArgumentParser(
        description="Build distillation batch files.",
        add_help=False,
    )
    parser.add_argument(
        "--contracts-path",
        type=Path,
        default=DEFAULT_CONTRACTS_PATH,
        metavar="PATH",
        help=(
            "Path to CUAD_v1.json or a contracts.jsonl file "
            "(default: data/atticus/CUAD_v1.json)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate token counts per batch without writing any files.",
    )
    # parse_known_args so that unknown tokens (e.g. 'all' from run_distill.py)
    # are silently ignored when this is called as part of a larger pipeline.
    args, _ = parser.parse_known_args()

    print("=" * 60)
    print("Build Batches" + (" [DRY RUN — no files written]" if args.dry_run else ""))
    print("=" * 60)

    print("\n[Reviewer — Dataset A]")
    reviewer_paths, reviewer_hash_meta = build_reviewer_batches(
        contracts_path=args.contracts_path,
        dry_run=args.dry_run,
    )

    print("\n[Validator — Dataset B]")
    validator_paths = build_validator_batches(dry_run=args.dry_run)

    print("\n[SEC Contracts]")
    sec_paths = build_sec_batches(dry_run=args.dry_run)

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return

    save_manifest(reviewer_paths, reviewer_hash_meta, validator_paths, sec_paths)

    total_files = len(reviewer_paths) + len(validator_paths) + len(sec_paths)
    print(f"\nDone. {total_files} batch file(s) written to {BATCHES_DIR}")
    print("Next: python -m scripts.run_distill calls")


if __name__ == "__main__":
    main()
