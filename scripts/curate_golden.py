#!/usr/bin/env python3
"""
curate_golden.py — Golden Edge-Case Dataset

Must be run AFTER curate_dataset.py (reads split_manifest.json).

Selects ~100–200 total examples across 4 failure-mode categories:
  contradiction      — hardest ContractNLI contradictions (high lexical overlap + contradiction)
  rare_issue         — CUAD golden contracts with rare issue types (<200 training examples)
  ambiguity          — LEDGAR golden candidates on taxonomy boundary (justified by collision score)
  false_positive_trap— LEDGAR boilerplate containing risk keywords (traps over-eager reviewers)

Zero-overlap verification:
  1. Exact hash (SHA-256 on normalized text)   — necessary
  2. Jaccard similarity on word sets (≥0.85)  — catches lightly edited templates

Outputs:
  data/curated/golden/golden_edge_cases.jsonl
  data/curated/golden/overlap_report.txt
"""

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR  = DATA_DIR / "curated" / "golden"
CUAD_FILE   = DATA_DIR / "atticus" / "cuad_clauses.parquet"
LEDGAR_FILE = DATA_DIR / "legal_clauses" / "ledgar.parquet"
CNLI_FILE   = DATA_DIR / "contractnli" / "contractnli.parquet"
MANIFEST    = DATA_DIR / "curated" / "split_manifest.json"
BOILER_FILE = DATA_DIR / "curated" / "boilerplate_archive.jsonl"

OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Limits (keep golden tight: manually inspectable, stable for regression) ───

TARGET_TOTAL        = 180   # hard ceiling before dedup
N_CONTRADICTION     = 50    # hardest ContractNLI contradictions
N_RARE_ISSUE        = 50    # rare CUAD issue types from golden contracts
N_AMBIGUOUS         = 50    # LEDGAR taxonomy-boundary labels
N_FP_TRAP           = 30    # boilerplate with risk keywords
JACCARD_THRESHOLD   = 0.85  # near-duplicate similarity cutoff

# ── Ambiguous LEDGAR labels ─────────────────────────────────────────────────
# Each label maps to one issue type in LEDGAR_LABEL_MAP, but also contains
# strong vocabulary from a second issue type — "collision" labels.
# Justification: computed at runtime via keyword collision score (see below).

AMBIGUOUS_LABELS = [
    "Obligations",    # compliance_obligation — but financial keywords common
    "Events",         # termination_risk — but governance/control keywords appear
    "Consequences",   # liability_exposure — but termination keywords appear
    "Limitations",    # liability_exposure — but restriction keywords appear
    "No Waivers",     # restriction_clause — but compliance keywords appear
    "Powers",         # governance_risk — but compliance keywords appear
    "Sharing",        # (if present) financial_obligation vs confidentiality_risk
]

# ── False-positive trap: boilerplate labels with risk keywords ────────────────

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


def word_overlap_score(text_a: str, text_b: str) -> float:
    """Jaccard similarity between word sets of two texts."""
    return jaccard(text_to_words(text_a), text_to_words(text_b))


def risk_keyword_count(text: str) -> int:
    t = text.lower()
    return sum(1 for kw in RISK_KEYWORDS if kw in t)


def collision_score(clause_text: str, other_issue_keywords: list[str]) -> int:
    """Count how many keywords from a second issue type appear in clause_text."""
    t = clause_text.lower()
    return sum(1 for kw in other_issue_keywords if kw in t)


# ── Load split manifest ────────────────────────────────────────────────────────


def load_manifest() -> dict:
    if not MANIFEST.exists():
        raise FileNotFoundError(
            f"split_manifest.json not found at {MANIFEST}.\n"
            "Run `python scripts/curate_dataset.py` first."
        )
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


# ── Collect training hashes (for zero-overlap verification) ───────────────────


def collect_training_hashes() -> tuple[set[str], list[frozenset]]:
    """Return (exact_hash_set, word_set_list) for all training clause texts."""
    exact: set[str] = set()
    word_sets: list[frozenset] = []

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
                word_sets.append(text_to_words(t))
            except Exception:
                pass

    a_dir = DATA_DIR / "curated" / "dataset_a"
    for f in a_dir.glob("reviewer_train.jsonl"):
        _collect(f, "clause_text")

    b_dir = DATA_DIR / "curated" / "dataset_b"
    for f in b_dir.glob("validator_train.jsonl"):
        _collect(f, "premise")

    print(f"  Loaded {len(exact):,} training hashes for overlap verification")
    return exact, word_sets


def is_near_duplicate(
    text: str,
    train_exact: set[str],
    train_word_sets: list[frozenset],
) -> bool:
    """True if text matches any training example by exact hash OR Jaccard ≥ threshold."""
    h = exact_hash(text)
    if h in train_exact:
        return True
    ws = text_to_words(text)
    return any(jaccard(ws, tw) >= JACCARD_THRESHOLD for tw in train_word_sets)


# ══════════════════════════════════════════════════════════════════════════════
# Category 1: Hardest contradictions (ContractNLI)
#   Selection: contradiction rows where premise ∩ hypothesis is largest
#   (high lexical overlap + contradiction = model must detect subtle conflict)
# ══════════════════════════════════════════════════════════════════════════════


def select_hard_contradictions(n: int) -> list[dict]:
    df = pd.read_parquet(CNLI_FILE)

    # identify label column
    label_col = "label" if "label" in df.columns else "label_name"
    df["_label"] = df[label_col].astype(str).str.lower().str.strip()

    # use test + validation rows (not training)
    mask = (df["_label"] == "contradiction") & (df["split"].isin(["test", "validation", "val", "dev"]))
    contra = df[mask].copy()

    if contra.empty:
        print(f"  [contradiction] No contradiction rows found in test/val splits — using all splits")
        contra = df[df["_label"] == "contradiction"].copy()

    # score by lexical overlap (premise ∩ hypothesis words / union)
    contra["_overlap"] = contra.apply(
        lambda r: word_overlap_score(str(r.get("premise", "")), str(r.get("hypothesis", ""))),
        axis=1,
    )
    contra = contra.sort_values("_overlap", ascending=False)

    print(f"  [contradiction] {len(contra):,} total contradiction rows, selecting top {n} by lexical overlap")
    if not contra.empty:
        print(f"    overlap score range: {contra['_overlap'].min():.3f} – {contra['_overlap'].max():.3f}")

    rows = []
    for i, (_, r) in enumerate(contra.head(n * 3).iterrows()):
        if len(rows) >= n:
            break
        premise   = str(r.get("premise", ""))
        hypothesis = str(r.get("hypothesis", ""))
        rows.append({
            "id":       f"golden_{len(rows) + 1:04d}",
            "category": "contradiction",
            "source":   "contractnli",
            "clause_text":  premise,
            "hypothesis":   hypothesis,
            "issue_type":   None,
            "overlap_score": round(float(r["_overlap"]), 4),
            "expected_behavior": {
                "reviewer_issue_type": None,
                "validator_verdict":   "reject",
                "failure_mode":        "hallucination_detection",
                "notes": (
                    "Clause explicitly contradicts the hypothesis despite high lexical overlap. "
                    "Validator must reject — model must detect contradiction, not just similarity."
                ),
            },
        })

    print(f"  [contradiction] Selected {len(rows)} examples")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Category 2: Rare issue types from CUAD golden contracts
# ══════════════════════════════════════════════════════════════════════════════


def select_rare_issue_examples(manifest: dict, n: int) -> list[dict]:
    from curate_dataset import map_cuad_clause_type, SEVERITY_MAP, KIRA_ISSUE_TYPES

    golden_contracts = set(manifest.get("cuad_contracts", {}).get("golden", []))
    if not golden_contracts:
        print("  [rare_issue] No golden contracts in manifest")
        return []

    df = pd.read_parquet(CUAD_FILE)
    df = df.drop_duplicates(subset=["clause_text"])
    df = df[df["clause_text"].str.split().str.len() >= 3]
    df["issue_type"] = df["clause_type"].apply(map_cuad_clause_type)

    golden_df = df[df["contract_title"].isin(golden_contracts) & (df["issue_type"] != "boilerplate")].copy()

    # Load training issue type counts to identify rare types
    train_counts: Counter = Counter()
    train_path = DATA_DIR / "curated" / "dataset_a" / "reviewer_train.jsonl"
    if train_path.exists():
        for line in open(train_path, encoding="utf-8"):
            try:
                r = json.loads(line)
                if r.get("source") == "cuad":
                    train_counts[r["issue_type"]] += 1
            except Exception:
                pass

    rare_threshold = 200
    if train_counts:
        rare_types = {it for it, cnt in train_counts.items() if cnt < rare_threshold}
    else:
        # fallback: pick issue types with fewest golden examples
        golden_counts = Counter(golden_df["issue_type"].tolist())
        rare_types = {it for it, cnt in golden_counts.items() if cnt < rare_threshold}

    print(f"  [rare_issue] Rare issue types (< {rare_threshold} train examples): {sorted(rare_types)}")

    rare_golden = golden_df[golden_df["issue_type"].isin(rare_types)].copy()
    if rare_golden.empty:
        # fallback: take least-common issue types from golden contracts
        counts = Counter(golden_df["issue_type"].tolist())
        rare_golden = golden_df[golden_df["issue_type"].isin(
            [k for k, _ in counts.most_common()[-5:]]
        )].copy()

    # sample evenly across rare types
    per_type = max(1, n // max(len(rare_types), 1))
    rows = []
    by_type = defaultdict(list)
    for _, r in rare_golden.iterrows():
        by_type[r["issue_type"]].append(r)

    for issue_type, type_rows in sorted(by_type.items()):
        import random
        sample = random.sample(type_rows, min(per_type, len(type_rows)))
        for r in sample:
            if len(rows) >= n:
                break
            branch = "kira" if issue_type in KIRA_ISSUE_TYPES else "harvey"
            rows.append({
                "id":       f"golden_{1000 + len(rows):04d}",
                "category": "rare_issue",
                "source":   "cuad",
                "clause_text": str(r.get("clause_text", "")),
                "hypothesis":  None,
                "issue_type":  issue_type,
                "expected_behavior": {
                    "reviewer_issue_type": issue_type,
                    "validator_verdict":   None,
                    "failure_mode":        "rare_class_recall",
                    "notes": (
                        f"Rare issue type '{issue_type}' from a contract not in the training set. "
                        "Reviewer must identify the correct issue type despite low training frequency."
                    ),
                    "branch": branch,
                    "severity": SEVERITY_MAP.get(issue_type, "medium"),
                    "severity_confidence": "weak",
                },
            })

    print(f"  [rare_issue] Selected {len(rows)} examples from {golden_df['contract_title'].nunique()} golden contracts")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Category 3: Ambiguous LEDGAR labels (taxonomy boundary)
#   Justification: runtime collision score — count keywords from a second issue
#   type that appear in clauses of this label.
# ══════════════════════════════════════════════════════════════════════════════

# Second-type keywords used for collision scoring
SECONDARY_TYPE_KEYWORDS: dict[str, tuple[str, list[str]]] = {
    "Obligations":  ("financial_obligation",  ["payment", "fee", "cost", "price", "amount", "due"]),
    "Events":       ("governance_risk",        ["control", "merger", "acquisition", "transfer", "assign"]),
    "Consequences": ("termination_risk",       ["terminat", "expir", "cancel", "end", "dissolv"]),
    "Limitations":  ("restriction_clause",     ["restrict", "prohibit", "shall not", "may not", "limit"]),
    "No Waivers":   ("compliance_obligation",  ["comply", "complian", "regulat", "law", "statute"]),
    "Powers":       ("compliance_obligation",  ["comply", "regulat", "authorit", "approv", "permit"]),
    "Sharing":      ("confidentiality_risk",   ["confidential", "disclos", "secret", "proprietary"]),
}


def select_ambiguous_examples(manifest: dict, n: int) -> list[dict]:
    from curate_dataset import LEDGAR_LABELS_LIST, map_ledgar_label

    golden_indices = set(manifest.get("ledgar_row_indices", {}).get("golden", []))
    if not golden_indices:
        print("  [ambiguity] No golden LEDGAR indices in manifest")
        return []

    df = pd.read_parquet(LEDGAR_FILE)
    if df["label"].dtype in ("int64", "int32", "float64"):
        df["label_name"] = df["label"].map(
            lambda x: LEDGAR_LABELS_LIST[int(x)] if 0 <= int(x) < len(LEDGAR_LABELS_LIST) else f"Label_{int(x)}"
        )
    else:
        df["label_name"] = df["label"].astype(str)
    df["issue_type"] = df["label_name"].apply(map_ledgar_label)

    golden_df = df.iloc[list(golden_indices)] if golden_indices else df[df["split"] == "test"]
    golden_df = golden_df[golden_df["label_name"].isin(AMBIGUOUS_LABELS)].copy()

    if golden_df.empty:
        print("  [ambiguity] No golden rows match ambiguous labels — using all test rows for these labels")
        golden_df = df[df["label_name"].isin(AMBIGUOUS_LABELS)].copy()

    per_label = max(1, n // max(len(AMBIGUOUS_LABELS), 1))
    rows = []

    print("  [ambiguity] Collision scores (justifying label selection):")
    by_label = defaultdict(list)
    for _, r in golden_df.iterrows():
        by_label[r["label_name"]].append(r)

    for label, label_rows in sorted(by_label.items()):
        if label not in SECONDARY_TYPE_KEYWORDS:
            continue
        second_type, keywords = SECONDARY_TYPE_KEYWORDS[label]
        primary_type = label_rows[0]["issue_type"] if label_rows else "unknown"

        # compute mean collision score across sample
        sample_size = min(20, len(label_rows))
        import random
        sample = random.sample(label_rows, sample_size)
        scores = [collision_score(str(r.get("text", "")), keywords) for r in sample]
        mean_score = sum(scores) / len(scores) if scores else 0.0
        print(f"    {label:<25} primary={primary_type:<25} secondary={second_type:<25} avg_collision={mean_score:.2f}")

        # only include if collision score > 0 (runtime justification)
        qualifying = [
            r for r in label_rows
            if collision_score(str(r.get("text", "")), keywords) > 0
        ]

        pick = random.sample(qualifying, min(per_label, len(qualifying))) if qualifying else []
        for r in pick:
            if len(rows) >= n:
                break
            rows.append({
                "id":        f"golden_{2000 + len(rows):04d}",
                "category":  "ambiguity",
                "source":    "ledgar",
                "clause_text": str(r.get("text", "")),
                "hypothesis":  None,
                "issue_type":  primary_type,
                "expected_behavior": {
                    "reviewer_issue_type":    primary_type,
                    "secondary_issue_type":   second_type,
                    "validator_verdict":      None,
                    "failure_mode":           "taxonomy_boundary_confusion",
                    "notes": (
                        f"Label '{label}' sits on the boundary between '{primary_type}' and '{second_type}'. "
                        f"Clause contains keywords from both issue types (collision score > 0). "
                        "Reviewer must resolve to the correct primary type."
                    ),
                    "collision_justification": {
                        "second_type": second_type,
                        "keywords_matched": [kw for kw in keywords if kw in str(r.get("text", "")).lower()],
                    },
                },
            })

    print(f"  [ambiguity] Selected {len(rows)} examples")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Category 4: False-positive traps (boilerplate with risk keywords)
# ══════════════════════════════════════════════════════════════════════════════


def select_fp_traps(n: int) -> list[dict]:
    if not BOILER_FILE.exists():
        print("  [fp_trap] boilerplate_archive.jsonl not found — skipping")
        return []

    rows: list[dict] = []
    import random

    with open(BOILER_FILE, encoding="utf-8") as f:
        candidates = []
        for line in f:
            try:
                r = json.loads(line)
                text = str(r.get("clause_text", ""))
                label = str(r.get("original_label", ""))
                kw_count = risk_keyword_count(text)
                # trap = boilerplate label + clause contains 2+ risk keywords
                if label in FP_BOILERPLATE_LABELS and kw_count >= 2:
                    candidates.append((kw_count, r, label, text))
            except Exception:
                pass

    # sort by keyword count descending (most trap-like first)
    candidates.sort(key=lambda x: -x[0])
    print(f"  [fp_trap] {len(candidates)} candidates (boilerplate + ≥2 risk keywords), selecting {n}")

    pick = candidates[:n * 2]  # over-select, dedup will trim
    for kw_count, r, label, text in pick:
        if len(rows) >= n:
            break
        rows.append({
            "id":        f"golden_{3000 + len(rows):04d}",
            "category":  "false_positive_trap",
            "source":    r.get("source", "ledgar"),
            "clause_text": text,
            "hypothesis":  None,
            "issue_type":  "boilerplate",
            "expected_behavior": {
                "reviewer_issue_type":  None,
                "validator_verdict":    None,
                "failure_mode":         "false_positive_over_flagging",
                "notes": (
                    f"Label '{label}' is boilerplate but contains {kw_count} risk keywords ({', '.join(kw for kw in RISK_KEYWORDS if kw in text.lower()[:200])}). "
                    "Reviewer should NOT flag this clause — it tests over-eager risk detection."
                ),
                "risk_keyword_count": kw_count,
            },
        })

    print(f"  [fp_trap] Selected {len(rows)} examples")
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Zero-overlap verification
# ══════════════════════════════════════════════════════════════════════════════


def deduplicate_against_training(
    golden: list[dict],
    train_exact: set[str],
    train_word_sets: list[frozenset],
) -> tuple[list[dict], int, int]:
    """Remove golden examples that overlap with training data."""
    clean: list[dict] = []
    n_exact_removed = 0
    n_fuzzy_removed = 0

    for r in golden:
        text = str(r.get("clause_text", ""))
        h = exact_hash(text)
        ws = text_to_words(text)

        if h in train_exact:
            n_exact_removed += 1
            continue

        fuzzy_match = any(jaccard(ws, tw) >= JACCARD_THRESHOLD for tw in train_word_sets)
        if fuzzy_match:
            n_fuzzy_removed += 1
            continue

        # also deduplicate within golden set
        clean.append(r)

    return clean, n_exact_removed, n_fuzzy_removed


def deduplicate_within_golden(rows: list[dict]) -> list[dict]:
    """Remove near-duplicates within the golden set itself."""
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
# Main
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    print("=" * 60)
    print("Golden Edge-Case Dataset Builder")
    print("=" * 60)

    # ── Load manifest ──────────────────────────────────────────────────────────
    print("\nLoading split manifest...")
    manifest = load_manifest()

    # ── Collect training hashes ────────────────────────────────────────────────
    print("\nCollecting training hashes for overlap verification...")
    train_exact, train_word_sets = collect_training_hashes()

    # ── Select categories ──────────────────────────────────────────────────────
    print("\n[1/4] Selecting hard contradictions...")
    contra_rows = select_hard_contradictions(N_CONTRADICTION)

    print("\n[2/4] Selecting rare issue examples...")
    rare_rows = select_rare_issue_examples(manifest, N_RARE_ISSUE)

    print("\n[3/4] Selecting ambiguous LEDGAR examples...")
    ambig_rows = select_ambiguous_examples(manifest, N_AMBIGUOUS)

    print("\n[4/4] Selecting false-positive traps...")
    fp_rows = select_fp_traps(N_FP_TRAP)

    all_golden = contra_rows + rare_rows + ambig_rows + fp_rows
    print(f"\nPre-dedup total: {len(all_golden)} examples")

    # ── Dedup within golden set ────────────────────────────────────────────────
    all_golden = deduplicate_within_golden(all_golden)
    print(f"After within-golden dedup: {len(all_golden)}")

    # ── Zero-overlap verification ──────────────────────────────────────────────
    print("\nRunning zero-overlap verification against training data...")
    all_golden, n_exact, n_fuzzy = deduplicate_against_training(all_golden, train_exact, train_word_sets)
    print(f"  Removed (exact hash match): {n_exact}")
    print(f"  Removed (Jaccard ≥ {JACCARD_THRESHOLD}):    {n_fuzzy}")
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
    by_category = {}
    for r in all_golden:
        cat = r.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1

    report_lines = [
        "Golden Edge-Case Dataset — Overlap Report",
        "=" * 50,
        f"Total examples:          {len(all_golden)}",
        f"Training hashes checked: {len(train_exact):,}",
        f"Removed (exact hash):    {n_exact}",
        f"Removed (Jaccard≥{JACCARD_THRESHOLD}): {n_fuzzy}",
        "",
        "Category breakdown:",
    ]
    for cat, cnt in sorted(by_category.items()):
        report_lines.append(f"  {cat:<25} {cnt:>4}")
    report_lines += [
        "",
        "Split manifest reference:",
        f"  {MANIFEST}",
        "",
        "Verification method:",
        f"  1. Exact SHA-256 on normalized (lowercase, collapsed whitespace) clause_text",
        f"  2. Jaccard similarity on word sets, threshold = {JACCARD_THRESHOLD}",
        "     (catches lightly edited templates, punctuation variants, pluralisation changes)",
    ]

    report_path = OUT_DIR / "overlap_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines) + "\n")

    print(f"Overlap report → {report_path}")
    print("\nCategory breakdown:")
    for cat, cnt in sorted(by_category.items()):
        print(f"  {cat:<25} {cnt:>4}")
    print("\nDone.")


if __name__ == "__main__":
    main()
