#!/usr/bin/env python3
"""
build_batches.py — Build OpenAI Batch API input files from curated datasets.

Reads:
  data/curated/dataset_a/reviewer_{train,val,test}.jsonl   → reviewer clauses
  data/curated/dataset_b/validator_{train,val,test}.jsonl  → NLI pairs
  data/curated/dataset_c/maud_{train,val,test}.jsonl       → MAUD deal-point QA
  data/material/sec_contracts.parquet                      → full SEC contracts

Outputs:
  data/distillation/batches/reviewer_batch_{n}.jsonl       — normal-size contracts
  data/distillation/batches/reviewer_large_batch_{n}.jsonl — large contracts (run last)
  data/distillation/batches/validator_batch_{n}.jsonl
  data/distillation/batches/maud_batch_{n}.jsonl
  data/distillation/batches/sec_batch_{n}.jsonl
  data/distillation/batches/manifest.json

Key design decisions:
  Reviewer — one GPT call per full contract, covering ALL flagged clauses in that
  contract. Clauses are sorted deterministically by hash so parse_results.py can
  reconstruct the same order without re-reading the prompt. The manifest stores the
  ordered clause list per contract so annotations join back correctly.
  LEDGAR rows have no full contract available and are skipped from distillation
  (kept in the RL pool as weak-label-only auxiliary data).

  Validator — one GPT call per (premise, hypothesis) pair; no dedup needed.

  MAUD — one GPT call per unique (passage, question) pair, using the confirmed
  attorney answer as ground truth. GPT explains the risk, not re-evaluates the answer.

  SEC — one GPT call per full contract (no chunking). Contracts estimated above
  SEC_MAX_TOKENS are written to sec_large batch files and processed last.
  Contracts exceeding SEC_HARD_SKIP_TOKENS are skipped entirely.

  All batch files are sorted smallest-to-largest by estimated input tokens so
  each labeling session covers as many contracts as possible before hitting limits.
  Large contracts (> LARGE_CONTRACT_TOKENS) are written to *_large batch files and
  processed after all normal files.

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
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .config import (
    BATCH_MAX_REQUESTS,
    BATCHES_DIR,
    CURATED_DIR,
    DATA_DIR,
    DISTILL_DIR,
    LARGE_CONTRACT_TOKENS,
    MAX_OUTPUT_TOKENS,
    SEC_FILE,
    TEACHER_CLAUSE,
    TEACHER_CONTRACT,
)
from .prompts import (
    SYSTEM_CONTRACT_MULTI,
    SYSTEM_MAUD,
    SYSTEM_MULTI_CLAUSE,
    SYSTEM_NLI,
    USER_CONTRACT_MULTI,
    USER_MAUD,
    USER_MULTI_CLAUSE,
    USER_NLI,
)

DEFAULT_CONTRACTS_PATH = DATA_DIR / "atticus" / "CUAD_v1.json"

# SEC contracts above this estimated token count are put in sec_large batch files.
# Contracts above SEC_HARD_SKIP_TOKENS are skipped entirely (too large for context).
SEC_MAX_TOKENS      = LARGE_CONTRACT_TOKENS   # reuse same threshold as other datasets
SEC_HARD_SKIP_TOKENS = 14_000                 # ~10,500 words — safely within GPT context


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
                print(f"  [ContractStore] WARNING: {path} not found — LEDGAR rows skipped (no contract context).")
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


def _req_token_estimate(req: dict) -> int:
    """Estimate input token count for a single request (chars / 4 heuristic)."""
    msgs = req.get("body", {}).get("messages", [])
    return sum(len(m.get("content", "")) for m in msgs) // 4


def sort_and_split(requests: list[dict]) -> tuple[list[dict], list[dict]]:
    """Sort requests ascending by token estimate; split off large ones.

    Normal requests (≤ LARGE_CONTRACT_TOKENS) are processed first so the
    per-session rate-limit budget labels as many contracts as possible.
    Large requests are written to *_large batch files and run last.
    """
    requests.sort(key=_req_token_estimate)
    normal = [r for r in requests if _req_token_estimate(r) <= LARGE_CONTRACT_TOKENS]
    large  = [r for r in requests if _req_token_estimate(r) >  LARGE_CONTRACT_TOKENS]
    return normal, large


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


# ── Reviewer — contract-level multi-clause (Dataset A) ───────────────────────


def build_contract_reviewer_batches(
    contracts_path: Path | None = None,
    dry_run: bool = False,
) -> tuple[list[str], dict]:
    """One GPT call per full contract, covering all flagged clauses in that contract.

    Returns (batch_file_paths, contract_clause_map).

    contract_clause_map: {custom_id: [{"clause_hash": h, "issue_type": it,
                                        "first_id": row_id}, ...]}

    Clauses within each contract are sorted by clause_hash (deterministic) so
    parse_results.py can reconstruct the same ordering without re-reading the prompt.

    LEDGAR rows (contract_id = label_name, no full contract available) are skipped:
    they carry no structural context and are kept as weak-label auxiliary data in
    the RL pool instead.
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

    # Deduplicate across the 3 role-augmented rows — we only need one GPT call
    # per unique (clause_text, contract_id) pair regardless of agent_role.
    unique_clauses: dict[str, dict] = {}   # clause_hash → row
    for row in all_rows:
        clause = str(row.get("clause_text", "")).strip()
        contract_id = str(row.get("contract_id", "")).strip()
        if not clause:
            continue
        h = text_hash(clause + contract_id)
        if h not in unique_clauses:
            unique_clauses[h] = row

    # Group unique clauses by contract_id
    by_contract: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for h, row in unique_clauses.items():
        cid = str(row.get("contract_id", "")).strip()
        by_contract[cid].append((h, row))

    requests: list[dict] = []
    contract_clause_map: dict[str, list[dict]] = {}
    skipped_no_contract = 0
    skipped_cross_ref   = 0

    for contract_id, clause_pairs in by_contract.items():
        full_text = store.get(contract_id) if contract_id else None

        if full_text is None:
            # No full contract — skip clauses with unresolvable cross-references.
            # Clauses without cross-refs are also skipped here: without contract
            # context they produce weaker annotations, and LEDGAR already lives in
            # the RL pool as weak-label data.
            skipped_no_contract += len(clause_pairs)
            continue

        # Filter any clause whose text references a section/exhibit not in context
        # (should not happen since we have the full contract, but guard anyway).
        valid_pairs = [
            (h, row) for h, row in clause_pairs
            if not CROSS_REF_RE.search(str(row.get("clause_text", "")))
            or full_text  # cross-refs are fine when full contract is present
        ]
        if not valid_pairs:
            skipped_cross_ref += len(clause_pairs)
            continue

        # Sort deterministically by clause hash so parse_results.py can
        # reconstruct the same ordering without reading the original prompt.
        valid_pairs.sort(key=lambda x: x[0])

        clauses_lines = []
        for idx, (h, row) in enumerate(valid_pairs):
            clause = str(row.get("clause_text", "")).strip()
            issue_type = row.get("issue_type", "unknown")
            clauses_lines.append(f"[{idx}] Category: {issue_type}\n{clause}")
        clauses_block = "\n\n".join(clauses_lines)

        custom_id = f"rev_contract_{text_hash(contract_id)}"
        user_msg = USER_MULTI_CLAUSE.format(
            contract_text=full_text,
            clauses_block=clauses_block,
        )
        requests.append(
            make_request(custom_id, TEACHER_CLAUSE, SYSTEM_MULTI_CLAUSE, user_msg)
        )
        contract_clause_map[custom_id] = [
            {
                "clause_hash": h,
                "issue_type":  row.get("issue_type", ""),
                "first_id":    row.get("id", ""),
            }
            for h, row in valid_pairs
        ]

    n_contracts = len(requests)
    n_clauses   = sum(len(v) for v in contract_clause_map.values())
    print(
        f"  [reviewer] {len(all_rows):,} rows → {len(unique_clauses):,} unique clauses → "
        f"{n_contracts:,} contract-level calls covering {n_clauses:,} clauses  "
        f"({skipped_no_contract:,} clauses skipped — no full contract available)"
    )

    if dry_run:
        _print_token_estimate(requests, "reviewer")
        return [], {}

    normal, large = sort_and_split(requests)
    paths = write_batch_files(normal, "reviewer")
    if large:
        print(f"  [reviewer] {len(large):,} large contracts (>{LARGE_CONTRACT_TOKENS} est. tokens) → reviewer_large batch files (run last)")
        paths += write_batch_files(large, "reviewer_large")
    return paths, contract_clause_map


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
        premise   = str(row.get("premise",   "")).strip()
        hypothesis = str(row.get("hypothesis", "")).strip()
        if not premise or not hypothesis:
            continue
        custom_id = f"val_{row.get('id', text_hash(premise + hypothesis))}"
        user_msg  = USER_NLI.format(premise=premise, hypothesis=hypothesis)
        requests.append(make_request(custom_id, TEACHER_CLAUSE, SYSTEM_NLI, user_msg))

    print(f"  [validator] {len(all_rows):,} rows → {len(requests):,} requests")

    if dry_run:
        _print_token_estimate(requests, "validator")
        return []

    normal, large = sort_and_split(requests)
    paths = write_batch_files(normal, "validator")
    if large:
        print(f"  [validator] {len(large):,} large premises → validator_large batch files (run last)")
        paths += write_batch_files(large, "validator_large")
    return paths


# ── MAUD deal-point QA (Dataset C) ───────────────────────────────────────────


def build_maud_batches(dry_run: bool = False) -> list[str]:
    """One GPT call per unique (passage, question) pair.

    Uses the confirmed attorney answer as ground truth anchor.  GPT explains
    the legal risk and negotiation implications rather than re-evaluating the answer.
    """
    all_rows: list[dict] = []
    for split in ("train", "val", "test"):
        p = CURATED_DIR / "dataset_c" / f"maud_{split}.jsonl"
        if p.exists():
            all_rows.extend(load_jsonl(p))

    if not all_rows:
        print("  [maud] No curated Dataset C found — skipping.")
        return []

    seen: set[str] = set()
    requests: list[dict] = []

    for row in all_rows:
        passage  = str(row.get("passage",  "")).strip()
        question = str(row.get("question", "")).strip()
        answer   = str(row.get("answer",   "")).strip()
        if not passage or not question:
            continue

        # Dedup by (passage, question) — same pair appears across train/val/test
        # due to role augmentation; one GPT call covers all occurrences.
        key = text_hash(passage + question)
        if key in seen:
            continue
        seen.add(key)

        custom_id = f"maud_{key}"
        user_msg  = USER_MAUD.format(
            category  = str(row.get("category",  "")).strip(),
            text_type = str(row.get("text_type", "")).strip(),
            passage   = passage,
            question  = question,
            answer    = answer,
        )
        requests.append(make_request(custom_id, TEACHER_CLAUSE, SYSTEM_MAUD, user_msg))

    print(f"  [maud] {len(all_rows):,} rows → {len(requests):,} unique (passage, question) calls")

    if dry_run:
        _print_token_estimate(requests, "maud")
        return []

    normal, large = sort_and_split(requests)
    paths = write_batch_files(normal, "maud")
    if large:
        print(f"  [maud] {len(large):,} large passages (>{LARGE_CONTRACT_TOKENS} est. tokens) → maud_large batch files (run last)")
        paths += write_batch_files(large, "maud_large")
    return paths


# ── SEC full contracts (no chunking) ─────────────────────────────────────────


def build_sec_batches(dry_run: bool = False) -> list[str]:
    """One GPT call per full SEC contract — no chunking.

    GPT identifies and evaluates up to 5 highest-risk clauses per contract.
    Contracts above SEC_HARD_SKIP_TOKENS are skipped entirely (too large).
    """
    if not SEC_FILE.exists():
        print("  [sec] sec_contracts.parquet not found — skipping.")
        return []

    df = pd.read_parquet(SEC_FILE)
    df = df[df["full_text"].notna()]
    df = df[df["full_text"].str.split().str.len() >= 100].reset_index(drop=True)

    requests:  list[dict] = []
    skipped_too_large = 0

    for row_idx, row in df.iterrows():
        full_text  = str(row["full_text"])
        est_tokens = len(full_text) // 4

        if est_tokens > SEC_HARD_SKIP_TOKENS:
            skipped_too_large += 1
            continue

        custom_id = f"sec_{row_idx}"
        user_msg  = USER_CONTRACT_MULTI.format(contract_text=full_text)
        requests.append(
            make_request(custom_id, TEACHER_CONTRACT, SYSTEM_CONTRACT_MULTI, user_msg)
        )

    print(
        f"  [sec] {len(df):,} contracts → {len(requests):,} calls  "
        f"({skipped_too_large:,} skipped — exceed {SEC_HARD_SKIP_TOKENS:,} token hard limit)"
    )

    if dry_run:
        _print_token_estimate(requests, "sec")
        return []

    normal, large = sort_and_split(requests)
    paths = write_batch_files(normal, "sec")
    if large:
        print(f"  [sec] {len(large):,} large contracts → sec_large batch files (run last)")
        paths += write_batch_files(large, "sec_large")
    return paths


# ── Manifest ──────────────────────────────────────────────────────────────────


def save_manifest(
    reviewer_paths:       list[str],
    contract_clause_map:  dict,
    validator_paths:      list[str],
    maud_paths:           list[str],
    sec_paths:            list[str],
) -> None:
    manifest = {
        "reviewer": {
            "batch_files":         reviewer_paths,
            "model":               TEACHER_CLAUSE,
            # Ordered clause list per contract — required by parse_results.py
            # to join multi-finding arrays back to individual clause rows.
            "contract_clause_map": contract_clause_map,
        },
        "validator": {
            "batch_files": validator_paths,
            "model":       TEACHER_CLAUSE,
        },
        "maud": {
            "batch_files": maud_paths,
            "model":       TEACHER_CLAUSE,
        },
        "sec": {
            "batch_files": sec_paths,
            "model":       TEACHER_CONTRACT,
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
    args, _ = parser.parse_known_args()

    print("=" * 60)
    print("Build Batches" + (" [DRY RUN — no files written]" if args.dry_run else ""))
    print("=" * 60)

    print("\n[Reviewer — Dataset A  (one call per full contract)]")
    reviewer_paths, contract_clause_map = build_contract_reviewer_batches(
        contracts_path=args.contracts_path,
        dry_run=args.dry_run,
    )

    print("\n[Validator — Dataset B]")
    validator_paths = build_validator_batches(dry_run=args.dry_run)

    print("\n[MAUD — Dataset C  (one call per passage+question)]")
    maud_paths = build_maud_batches(dry_run=args.dry_run)

    print("\n[SEC Contracts  (full contract, no chunking)]")
    sec_paths = build_sec_batches(dry_run=args.dry_run)

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return

    save_manifest(
        reviewer_paths, contract_clause_map,
        validator_paths,
        maud_paths,
        sec_paths,
    )

    total_files = len(reviewer_paths) + len(validator_paths) + len(maud_paths) + len(sec_paths)
    print(f"\nDone. {total_files} batch file(s) written to {BATCHES_DIR}")
    print("Next: python -m scripts.run_distill calls")


if __name__ == "__main__":
    main()
