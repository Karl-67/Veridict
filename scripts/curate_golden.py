#!/usr/bin/env python3
"""
curate_golden.py — Golden Edge-Case Dataset

Must be run AFTER curate_dataset.py (reads split_manifest.json and the
curated test-split files).

Design principle
────────────────
The golden set provides dense evaluation coverage for issue types and
categories that are underrepresented in the regular test split.  Each
selection function reads the test split distribution first, identifies
what is rare (count < RARE_TEST_THRESHOLD), and then sources additional
examples of those rare types from held-out data that never appeared in
the training set.

Four categories
───────────────
  rare_reviewer      issue types with few rows in reviewer_test.jsonl;
                     sourced from CUAD golden contracts + LEDGAR golden rows

  rare_validator     verdicts with few rows in validator_test.jsonl;
                     sourced from ContractNLI non-train rows

  rare_maud          MAUD categories with few rows in maud_test.jsonl;
                     sourced from MAUD val/test rows

  false_positive_trap boilerplate containing risk keywords;
                     tests over-eager reviewer flagging

Zero-overlap check
──────────────────
Exact SHA-256 hash match against training data only.  Jaccard fuzzy
matching is intentionally omitted here: legal boilerplate shares
phrasing across splits, so a 0.85 Jaccard threshold removes too many
legitimate golden examples.  Jaccard is still used to deduplicate
within the golden set itself (to avoid near-identical rows in the
benchmark).

Outputs
───────
  data/curated/golden/golden_edge_cases.jsonl
  data/curated/golden/overlap_report.txt
"""

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR  = DATA_DIR / "curated" / "golden"
CUAD_FILE   = DATA_DIR / "atticus" / "cuad_clauses.parquet"
LEDGAR_FILE = DATA_DIR / "legal_clauses" / "ledgar.parquet"
CNLI_FILE   = DATA_DIR / "contractnli" / "contractnli.parquet"
MAUD_FILE   = DATA_DIR / "maud" / "maud.parquet"
MANIFEST    = DATA_DIR / "curated" / "split_manifest.json"
BOILER_FILE = DATA_DIR / "curated" / "boilerplate_archive.jsonl"

OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Limits ────────────────────────────────────────────────────────────────────

# Issue types / categories with fewer than this many rows in their test split
# are considered rare and become candidates for golden selection.
RARE_TEST_THRESHOLD = 500

N_PER_RARE_TYPE    = 50   # golden rows per rare reviewer issue type
N_RARE_VALIDATOR   = 50   # golden rows for rare validator verdicts
N_PER_RARE_MAUD    = 30   # golden rows per rare MAUD category
N_FP_TRAP          = 30   # false-positive trap rows

JACCARD_THRESHOLD  = 0.85  # used only for within-golden dedup

# ── False-positive trap: boilerplate labels containing risk keywords ───────────

RISK_KEYWORDS = [
    "liabilit", "indemnif", "terminat", "breach", "default", "penalt",
    "warrant", "damages", "negligence", "willful",
]

FP_BOILERPLATE_LABELS = [
    "Entire Agreements",
    "Cooperation",
    "Definitions",
    "General",
    "Miscellaneous",
    "Further Assurances",
    "Counterparts",
    "Amendments",
]

# ── MAUD category → issue type (keep in sync with curate_dataset.py) ─────────

_MAUD_CAT_ISSUE = {
    "Material Adverse Effect":                "termination_risk",
    "Deal Protection and Related Provisions":  "governance_risk",
    "Conditions to Closing":                  "representation_risk",
    "Operating and Efforts Covenant":         "compliance_obligation",
    "Knowledge":                              "representation_risk",
    "General Information":                    "financial_obligation",
    "Remedies":                               "dispute_resolution",
}

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def exact_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def text_to_words(text: str) -> frozenset:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return frozenset(cleaned.split())


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def risk_keyword_count(text: str) -> int:
    t = text.lower()
    return sum(1 for kw in RISK_KEYWORDS if kw in t)


# ── Manifest ──────────────────────────────────────────────────────────────────


def load_manifest() -> dict:
    if not MANIFEST.exists():
        raise FileNotFoundError(
            f"split_manifest.json not found at {MANIFEST}.\n"
            "Run `python scripts/curate_dataset.py` first."
        )
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


# ── Training hash collection (exact only — used to block leakage) ─────────────


def collect_training_hashes() -> set[str]:
    """Return SHA-256 hashes of every text in the training splits.

    Covers all three curated datasets:
      dataset_a  reviewer_train.jsonl   → clause_text
      dataset_b  validator_train.jsonl  → premise
      dataset_c  maud_train.jsonl       → passage
    """
    exact: set[str] = set()

    def _collect(path: Path, text_col: str) -> None:
        if not path.exists():
            return
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
                if r.get("split") != "train":
                    continue
                t = str(r.get(text_col, r.get("clause_text", r.get("premise", ""))))
                exact.add(exact_hash(t))
            except Exception:
                pass

    _collect(DATA_DIR / "curated" / "dataset_a" / "reviewer_train.jsonl",  "clause_text")
    _collect(DATA_DIR / "curated" / "dataset_b" / "validator_train.jsonl", "premise")
    _collect(DATA_DIR / "curated" / "dataset_c" / "maud_train.jsonl",      "passage")

    print(f"  Loaded {len(exact):,} training hashes for overlap verification")
    return exact


# ══════════════════════════════════════════════════════════════════════════════
# Dedup helpers
# ══════════════════════════════════════════════════════════════════════════════


def deduplicate_against_training(
    golden: list[dict],
    train_exact: set[str],
) -> tuple[list[dict], int]:
    """Remove golden examples whose exact text already appears in training.

    Only exact SHA-256 matches are removed.  Fuzzy/Jaccard matching is
    intentionally skipped: legal boilerplate shares phrasing across splits
    and a 0.85 threshold removes too many legitimate edge-case examples.
    """
    clean: list[dict] = []
    n_removed = 0
    for r in golden:
        h = exact_hash(str(r.get("clause_text", "")))
        if h in train_exact:
            n_removed += 1
        else:
            clean.append(r)
    return clean, n_removed


def deduplicate_within_golden(rows: list[dict]) -> list[dict]:
    """Remove near-duplicates within the golden set (exact + Jaccard ≥ 0.85)."""
    seen_hashes: set[str] = set()
    seen_word_sets: list[frozenset] = []
    clean: list[dict] = []

    for r in rows:
        text = str(r.get("clause_text", ""))
        h = exact_hash(text)
        ws = text_to_words(text)

        if h in seen_hashes:
            continue
        if any(jaccard(ws, sw) >= JACCARD_THRESHOLD for sw in seen_word_sets):
            continue

        seen_hashes.add(h)
        seen_word_sets.append(ws)
        clean.append(r)

    return clean


# ══════════════════════════════════════════════════════════════════════════════
# Category 1: Rare reviewer issue types
#   Reads reviewer_test.jsonl to find issue types with < RARE_TEST_THRESHOLD
#   rows, then sources from CUAD golden contracts + LEDGAR golden rows.
# ══════════════════════════════════════════════════════════════════════════════


def select_rare_reviewer_types(manifest: dict, n_per_type: int) -> list[dict]:
    from curate_dataset import (
        map_cuad_clause_type, map_ledgar_label, LEDGAR_LABELS_LIST,
        SEVERITY_MAP, KIRA_ISSUE_TYPES, get_branch,
    )

    # ── Step 1: test split distribution ──────────────────────────────────────
    test_path = DATA_DIR / "curated" / "dataset_a" / "reviewer_test.jsonl"
    test_counts: Counter = Counter()
    if test_path.exists():
        for line in open(test_path, encoding="utf-8"):
            try:
                test_counts[json.loads(line)["issue_type"]] += 1
            except Exception:
                pass

    rare_types = {it for it, cnt in test_counts.items() if cnt < RARE_TEST_THRESHOLD}
    if not rare_types and test_counts:
        # fallback: bottom 3 by test count
        rare_types = {it for it, _ in test_counts.most_common()[-3:]}

    dist_str = " ".join(f"{it}={cnt}" for it, cnt in sorted(test_counts.items(), key=lambda x: x[1]))
    print(f"  [rare_reviewer] test dist: {dist_str}")
    print(f"  [rare_reviewer] rare types (< {RARE_TEST_THRESHOLD}): {sorted(rare_types)}")

    # ── Step 2: source from CUAD golden contracts ─────────────────────────────
    golden_contracts = set(manifest.get("cuad_contracts", {}).get("golden", []))
    by_type: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

    if CUAD_FILE.exists() and golden_contracts:
        df = pd.read_parquet(CUAD_FILE)
        df = df.drop_duplicates(subset=["clause_text"])
        df = df[df["clause_text"].str.split().str.len() >= 10]
        df["issue_type"] = df["clause_type"].apply(map_cuad_clause_type)
        for _, r in df[df["contract_title"].isin(golden_contracts) &
                       df["issue_type"].isin(rare_types)].iterrows():
            by_type[r["issue_type"]].append(
                ("cuad", str(r.get("clause_text", "")), str(r.get("contract_title", "")))
            )

    # ── Step 3: source from LEDGAR golden rows ────────────────────────────────
    golden_indices = set(manifest.get("ledgar_row_indices", {}).get("golden", []))
    if LEDGAR_FILE.exists() and golden_indices:
        df = pd.read_parquet(LEDGAR_FILE)
        if df["label"].dtype in ("int64", "int32", "float64"):
            df["label_name"] = df["label"].map(
                lambda x: LEDGAR_LABELS_LIST[int(x)] if 0 <= int(x) < len(LEDGAR_LABELS_LIST)
                else f"Label_{int(x)}"
            )
        else:
            df["label_name"] = df["label"].astype(str)
        df["issue_type"] = df["label_name"].apply(map_ledgar_label)
        for _, r in df.iloc[list(golden_indices)][
            df.iloc[list(golden_indices)]["issue_type"].isin(rare_types)
        ].iterrows():
            by_type[r["issue_type"]].append(
                ("ledgar", str(r.get("text", "")), str(r.get("label_name", "")))
            )

    # ── Step 4: build golden rows ─────────────────────────────────────────────
    rows: list[dict] = []
    for issue_type in sorted(rare_types):
        candidates = by_type.get(issue_type, [])
        if not candidates:
            print(f"    {issue_type}: no held-out examples found")
            continue
        random.shuffle(candidates)
        branch   = get_branch(issue_type)
        severity = SEVERITY_MAP.get(issue_type, "medium")
        n_added  = 0
        for source, text, contract_id in candidates:
            if n_added >= n_per_type or not text.strip():
                break
            rows.append({
                "id":          f"golden_{1000 + len(rows):04d}",
                "category":    "rare_reviewer",
                "source":      source,
                "clause_text": text,
                "hypothesis":  None,
                "issue_type":  issue_type,
                "expected_behavior": {
                    "reviewer_issue_type": issue_type,
                    "validator_verdict":   None,
                    "failure_mode":        "rare_type_recall",
                    "branch":              branch,
                    "severity":            severity,
                    "severity_confidence": "weak",
                    "notes": (
                        f"Issue type '{issue_type}' has only "
                        f"{test_counts.get(issue_type, 0)} examples in the reviewer "
                        f"test split. Reviewer must identify this rare type correctly."
                    ),
                },
            })
            n_added += 1
        print(f"    {issue_type}: test_count={test_counts.get(issue_type, 0)}, selected={n_added}")

    print(f"  [rare_reviewer] Selected {len(rows)} examples")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Category 2: Rare validator verdicts
#   Reads validator_test.jsonl to find verdicts with < RARE_TEST_THRESHOLD
#   rows, then sources from ContractNLI non-train rows for those verdicts.
# ══════════════════════════════════════════════════════════════════════════════

_NLI_VERDICT_MAP = {"entailment": "retain", "contradiction": "reject", "neutral": "uncertain"}


def select_rare_validator_labels(n: int) -> list[dict]:
    # ── Step 1: test split distribution ──────────────────────────────────────
    test_path = DATA_DIR / "curated" / "dataset_b" / "validator_test.jsonl"
    test_counts: Counter = Counter()
    if test_path.exists():
        for line in open(test_path, encoding="utf-8"):
            try:
                test_counts[json.loads(line)["verdict"]] += 1
            except Exception:
                pass

    rare_verdicts = {v for v, cnt in test_counts.items() if cnt < RARE_TEST_THRESHOLD}
    if not rare_verdicts and test_counts:
        rare_verdicts = {min(test_counts, key=test_counts.get)}

    print(f"  [rare_validator] test dist: {dict(test_counts)}")
    print(f"  [rare_validator] rare verdicts (< {RARE_TEST_THRESHOLD}): {sorted(rare_verdicts)}")

    if not CNLI_FILE.exists():
        print("  [rare_validator] ContractNLI parquet not found — skipping")
        return []

    # ── Step 2: source from ContractNLI non-train rows ───────────────────────
    df = pd.read_parquet(CNLI_FILE)
    label_col = "label" if "label" in df.columns else "label_name"
    df["_label"]   = df[label_col].astype(str).str.lower().str.strip()
    df["_verdict"] = df["_label"].map(_NLI_VERDICT_MAP).fillna("uncertain")
    df["_split"]   = df["split"].str.lower().replace({"validation": "val", "dev": "val"})

    pool = df[
        df["_split"].isin(["test", "val"]) &
        df["_verdict"].isin(rare_verdicts)
    ].copy()

    if pool.empty:
        print("  [rare_validator] No non-train rows for rare verdicts — skipping")
        return []

    pool = pool.sample(min(n * 3, len(pool)), random_state=42)

    rows: list[dict] = []
    for _, r in pool.iterrows():
        if len(rows) >= n:
            break
        premise = str(r.get("premise", "")).strip()
        if not premise:
            continue
        verdict = str(r["_verdict"])
        rows.append({
            "id":          f"golden_{500 + len(rows):04d}",
            "category":    "rare_validator",
            "source":      "contractnli",
            "clause_text": premise,
            "hypothesis":  str(r.get("hypothesis", "")),
            "issue_type":  None,
            "expected_behavior": {
                "reviewer_issue_type": None,
                "validator_verdict":   verdict,
                "failure_mode":        "rare_verdict_recall",
                "nli_label":           str(r["_label"]),
                "notes": (
                    f"Verdict '{verdict}' has only {test_counts.get(verdict, 0)} "
                    f"examples in the validator test split. Validator must correctly "
                    f"identify this rare verdict."
                ),
            },
        })

    print(f"  [rare_validator] Selected {len(rows)} examples")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Category 3: Rare MAUD categories
#   Reads maud_test.jsonl to find categories with < RARE_TEST_THRESHOLD rows,
#   then sources from MAUD val/test rows for those categories.
# ══════════════════════════════════════════════════════════════════════════════


def select_rare_maud_categories(n_per_cat: int) -> list[dict]:
    # ── Step 1: test split distribution ──────────────────────────────────────
    test_path = DATA_DIR / "curated" / "dataset_c" / "maud_test.jsonl"
    test_counts: Counter = Counter()
    if test_path.exists():
        for line in open(test_path, encoding="utf-8"):
            try:
                test_counts[json.loads(line)["category"]] += 1
            except Exception:
                pass

    rare_cats = {cat for cat, cnt in test_counts.items() if cnt < RARE_TEST_THRESHOLD}
    if not rare_cats and test_counts:
        rare_cats = {cat for cat, _ in sorted(test_counts.items(), key=lambda x: x[1])[:3]}

    dist_str = " ".join(f"{c}={n}" for c, n in sorted(test_counts.items(), key=lambda x: x[1]))
    print(f"  [rare_maud] test dist: {dist_str}")
    print(f"  [rare_maud] rare categories (< {RARE_TEST_THRESHOLD}): {sorted(rare_cats)}")

    if not MAUD_FILE.exists():
        print("  [rare_maud] MAUD parquet not found — skipping")
        return []

    # ── Step 2: source from MAUD val/test rows ────────────────────────────────
    df = pd.read_parquet(MAUD_FILE)
    df["_split"] = df["split"].str.lower().replace({"validation": "val", "dev": "val"})
    df["word_count"] = df["text"].astype(str).str.split().str.len()
    pool = df[
        df["_split"].isin(["val", "test"]) &
        df["category"].isin(rare_cats) &
        (df["word_count"] >= 10) &
        (df["word_count"] <= 600)
    ].copy()

    if pool.empty:
        print("  [rare_maud] No val/test rows for rare categories — skipping")
        return []

    by_cat: dict[str, list] = defaultdict(list)
    for _, r in pool.iterrows():
        by_cat[str(r["category"])].append(r)

    rows: list[dict] = []
    for cat in sorted(rare_cats):
        cat_rows = by_cat.get(cat, [])
        if not cat_rows:
            print(f"    {cat}: no val/test rows available")
            continue
        random.shuffle(cat_rows)
        issue_type = _MAUD_CAT_ISSUE.get(cat, "governance_risk")
        n_added = 0
        for r in cat_rows:
            if n_added >= n_per_cat:
                break
            passage = str(r.get("text", "")).strip()
            if not passage:
                continue
            rows.append({
                "id":          f"golden_{4000 + len(rows):04d}",
                "category":    "rare_maud",
                "source":      "maud",
                "clause_text": passage,
                "hypothesis":  None,
                "issue_type":  issue_type,
                "expected_behavior": {
                    "reviewer_issue_type": issue_type,
                    "validator_verdict":   None,
                    "failure_mode":        "rare_maud_category_recall",
                    "maud_category":       cat,
                    "question":            str(r.get("question", "")),
                    "expected_answer":     str(r.get("answer", "")),
                    "word_count":          int(r["word_count"]),
                    "notes": (
                        f"MAUD category '{cat}' has only {test_counts.get(cat, 0)} "
                        f"examples in the test split. Tests the model's ability to "
                        f"handle rare M&A deal-point types."
                    ),
                },
            })
            n_added += 1
        print(f"    {cat}: test_count={test_counts.get(cat, 0)}, selected={n_added}")

    print(f"  [rare_maud] Selected {len(rows)} examples across {len(rare_cats)} categories")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Category 4: False-positive traps (boilerplate with risk keywords)
# ══════════════════════════════════════════════════════════════════════════════


def select_fp_traps(n: int) -> list[dict]:
    if not BOILER_FILE.exists():
        print("  [fp_trap] boilerplate_archive.jsonl not found — skipping")
        return []

    candidates = []
    with open(BOILER_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                text  = str(r.get("clause_text", ""))
                label = str(r.get("original_label", ""))
                kw_count = risk_keyword_count(text)
                if label in FP_BOILERPLATE_LABELS and kw_count >= 2:
                    candidates.append((kw_count, r, label, text))
            except Exception:
                pass

    candidates.sort(key=lambda x: -x[0])
    print(f"  [fp_trap] {len(candidates)} candidates (boilerplate + ≥2 risk keywords), selecting {n}")

    rows: list[dict] = []
    for kw_count, r, label, text in candidates[:n * 2]:
        if len(rows) >= n:
            break
        rows.append({
            "id":          f"golden_{3000 + len(rows):04d}",
            "category":    "false_positive_trap",
            "source":      r.get("source", "ledgar"),
            "clause_text": text,
            "hypothesis":  None,
            "issue_type":  "boilerplate",
            "expected_behavior": {
                "reviewer_issue_type": None,
                "validator_verdict":   None,
                "failure_mode":        "false_positive_over_flagging",
                "notes": (
                    f"Label '{label}' is boilerplate but contains {kw_count} risk "
                    f"keywords ({', '.join(kw for kw in RISK_KEYWORDS if kw in text.lower()[:200])}). "
                    "Reviewer should NOT flag this clause — it tests over-eager risk detection."
                ),
                "risk_keyword_count": kw_count,
            },
        })

    print(f"  [fp_trap] Selected {len(rows)} examples")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Sharding — mirrors curate_dataset.py logic
#
#   label_shard = (stable_hash(group_key) % num_shards) + 1
#
#   Group keys per golden category:
#     rare_reviewer / false_positive_trap → source, clause_text
#     rare_validator                      → source, clause_text (=premise), hypothesis
#     rare_maud                           → source, clause_text (=passage), question
#
#   Global IDs are preserved in shard output for cross-shard traceability.
# ══════════════════════════════════════════════════════════════════════════════


def _golden_stable_hash(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)


def _golden_key(r: dict) -> str:
    cat    = r.get("category", "")
    source = r.get("source", "")
    text   = r.get("clause_text", "")
    if cat == "rare_validator":
        hyp = r.get("hypothesis") or ""
        return "\x00".join([source, text, hyp])
    if cat == "rare_maud":
        q = (r.get("expected_behavior") or {}).get("question", "")
        return "\x00".join([source, text, q])
    # rare_reviewer, false_positive_trap
    return "\x00".join([source, text])


def _assign_golden_shards(rows: list[dict], num_shards: int) -> None:
    """Attach label_shard (1-based) in-place."""
    for r in rows:
        r["label_shard"] = (_golden_stable_hash(_golden_key(r)) % num_shards) + 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Golden Edge-Case Dataset Builder")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--shard", type=int, metavar="N",
                     help="Also write shard N to data/curated/shards/shard_N/golden/")
    grp.add_argument("--shard1", dest="shard", action="store_const", const=1)
    grp.add_argument("--shard2", dest="shard", action="store_const", const=2)
    grp.add_argument("--shard3", dest="shard", action="store_const", const=3)
    p.add_argument("--num-shards", type=int, default=3,
                   help="Total number of shards (default 3)")
    return p.parse_args()


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    args = parse_args()

    print("=" * 60)
    print("Golden Edge-Case Dataset Builder")
    print("=" * 60)

    random.seed(42)

    print("\nLoading split manifest...")
    manifest = load_manifest()

    print("\nCollecting training hashes for overlap verification...")
    train_exact = collect_training_hashes()

    # ── Select categories ──────────────────────────────────────────────────────
    print("\n[1/4] Selecting rare reviewer issue types...")
    reviewer_rows = select_rare_reviewer_types(manifest, N_PER_RARE_TYPE)

    print("\n[2/4] Selecting rare validator verdicts...")
    validator_rows = select_rare_validator_labels(N_RARE_VALIDATOR)

    print("\n[3/4] Selecting rare MAUD categories...")
    maud_rows = select_rare_maud_categories(N_PER_RARE_MAUD)

    print("\n[4/4] Selecting false-positive traps...")
    fp_rows = select_fp_traps(N_FP_TRAP)

    all_golden = reviewer_rows + validator_rows + maud_rows + fp_rows
    print(f"\nPre-dedup total: {len(all_golden)} examples")

    # ── Dedup within golden set ────────────────────────────────────────────────
    all_golden = deduplicate_within_golden(all_golden)
    print(f"After within-golden dedup: {len(all_golden)}")

    # ── Remove exact training duplicates ──────────────────────────────────────
    print("\nRemoving exact training duplicates...")
    all_golden, n_removed = deduplicate_against_training(all_golden, train_exact)
    print(f"  Removed (exact hash match): {n_removed}")
    print(f"  Final golden set:           {len(all_golden)}")

    # ── Re-index IDs ──────────────────────────────────────────────────────────
    for i, r in enumerate(all_golden):
        r["id"] = f"golden_{i + 1:04d}"

    # ── Write output ───────────────────────────────────────────────────────────
    out_file = OUT_DIR / "golden_edge_cases.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for r in all_golden:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(all_golden)} golden examples → {out_file}")

    # ── Overlap report ─────────────────────────────────────────────────────────
    by_category: dict[str, int] = {}
    for r in all_golden:
        cat = r.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1

    report_lines = [
        "Golden Edge-Case Dataset — Build Report",
        "=" * 50,
        f"Total examples:          {len(all_golden)}",
        f"Training hashes checked: {len(train_exact):,}",
        f"Removed (exact hash):    {n_removed}",
        "",
        "Category breakdown:",
    ]
    for cat, cnt in sorted(by_category.items()):
        report_lines.append(f"  {cat:<25} {cnt:>4}")
    report_lines += [
        "",
        "Selection thresholds:",
        f"  RARE_TEST_THRESHOLD = {RARE_TEST_THRESHOLD}",
        f"  N_PER_RARE_TYPE     = {N_PER_RARE_TYPE}",
        f"  N_RARE_VALIDATOR    = {N_RARE_VALIDATOR}",
        f"  N_PER_RARE_MAUD     = {N_PER_RARE_MAUD}",
        f"  N_FP_TRAP           = {N_FP_TRAP}",
        "",
        "Split manifest reference:",
        f"  {MANIFEST}",
        "",
        "Overlap check method:",
        "  Exact SHA-256 on normalized (lowercase, collapsed whitespace) clause_text.",
        "  Jaccard fuzzy matching is used only within the golden set (dedup), not",
        "  against training — legal boilerplate shares phrasing across splits and",
        "  0.85 Jaccard removes too many legitimate edge-case examples.",
    ]

    report_path = OUT_DIR / "overlap_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines) + "\n")

    print(f"Report → {report_path}")
    print("\nCategory breakdown:")
    for cat, cnt in sorted(by_category.items()):
        print(f"  {cat:<25} {cnt:>4}")

    # ── Shard output ──────────────────────────────────────────────────────────
    if args.shard is not None:
        shard_n    = args.shard
        num_shards = args.num_shards
        if not (1 <= shard_n <= num_shards):
            raise ValueError(f"--shard must be between 1 and {num_shards}, got {shard_n}")
        _assign_golden_shards(all_golden, num_shards)
        shard_rows = [r for r in all_golden if r["label_shard"] == shard_n]
        shard_dir = DATA_DIR / "curated" / "shards" / f"shard_{shard_n}" / "golden"
        shard_dir.mkdir(parents=True, exist_ok=True)
        shard_out = shard_dir / "golden_edge_cases.jsonl"
        with open(shard_out, "w", encoding="utf-8") as f:
            for r in shard_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n[Shard {shard_n}/{num_shards}] {len(shard_rows)} golden examples -> {shard_out}")

    print("\nDone.")


if __name__ == "__main__":
    main()
