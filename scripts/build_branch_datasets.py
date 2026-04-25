#!/usr/bin/env python3
"""
build_branch_datasets.py — Phase 3 of the branch training pipeline.

Constructs branch-specific training sets from normalized + context-enriched rows
using the prescribed source composition ratios.

Harvey composition (target ~65k train rows):
  - CUAD rows  (branch=harvey): all positives + capped negatives  [primary]
  - LEDGAR rows (branch=harvey): up to 25% of Harvey train target [supplement]
  - MAUD rows: up to 10% of Harvey train target                   [auxiliary]
  - Hard negatives: 15%  added by build_hard_negatives.py (not here)

Kira composition (target ~55k train rows):
  - LEDGAR rows (branch=kira):  all positives + capped negatives  [primary]
  - CUAD rows  (branch=kira):   all available                     [supplement]
  - MAUD rows: up to 20% of Kira train target                     [auxiliary]
  - Hard negatives: 15%  added by build_hard_negatives.py (not here)

Outputs:
  data/distillation/harvey/{train,val,test}.jsonl
  data/distillation/kira/{train,val,test}.jsonl
  data/distillation/validator/base_{train,val,test}.jsonl  (ContractNLI)
  data/distillation/maud/{train,val,test}.jsonl            (reference copy)

Run: python -m scripts.build_branch_datasets
"""

import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR   = ROOT / "data"
NORM_DIR   = DATA_DIR / "curated" / "normalized"
DISTILL_DIR = DATA_DIR / "distillation"

SPLITS = ("train", "val", "test")

# ── Composition targets ───────────────────────────────────────────────────────
HARVEY_TRAIN_TARGET = 65_000
KIRA_TRAIN_TARGET   = 55_000

# Source caps (fraction of branch train target)
HARVEY_LEDGAR_CAP = 0.25   # max 25% LEDGAR rows in Harvey
HARVEY_MAUD_CAP   = 0.10   # max 10% MAUD rows in Harvey
KIRA_MAUD_CAP     = 0.20   # max 20% MAUD rows in Kira

# Negative cap: negatives ≤ this fraction of positives
NEGATIVE_CAP_FRAC = 0.40

# MAUD issue-type preferences per branch
HARVEY_MAUD_ISSUES = {"termination_risk", "ip_risk", "representation_risk", "governance_risk", "financial_obligation"}
KIRA_MAUD_ISSUES   = {"representation_risk", "compliance_obligation", "jurisdictional_risk", "confidentiality_risk"}

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


# ── Balancing helpers ─────────────────────────────────────────────────────────

def cap_negatives(rows: list[dict], cap_frac: float = NEGATIVE_CAP_FRAC) -> list[dict]:
    """Keep all positives; cap negatives to cap_frac × len(positives)."""
    positives = [r for r in rows if r.get("risk_present", True)]
    negatives = [r for r in rows if not r.get("risk_present", True)]
    max_neg   = max(1, int(len(positives) * cap_frac))
    if len(negatives) > max_neg:
        negatives = random.sample(negatives, max_neg)
    return positives + negatives


def sample_to(rows: list[dict], cap: int) -> list[dict]:
    if len(rows) <= cap:
        return list(rows)
    return random.sample(rows, cap)


def partition_by_source(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(str(r.get("source", "unknown")), []).append(r)
    return out


# ── Branch builder ────────────────────────────────────────────────────────────

def build_harvey(harvey_rows: dict, maud_rows: dict) -> dict[str, list[dict]]:
    result = {s: [] for s in SPLITS}
    for split in SPLITS:
        rows  = harvey_rows[split]
        mauds = maud_rows[split]
        is_train = split == "train"
        target = HARVEY_TRAIN_TARGET if is_train else None

        by_src = partition_by_source(rows)
        cuad_rows   = cap_negatives(by_src.get("cuad",   []))
        ledgar_rows = cap_negatives(by_src.get("ledgar", []))

        # Cap LEDGAR at 25% of train target
        ledgar_cap = int(HARVEY_TRAIN_TARGET * HARVEY_LEDGAR_CAP) if is_train else len(ledgar_rows)
        ledgar_rows = sample_to(ledgar_rows, ledgar_cap)

        # MAUD: prefer domain-relevant issues
        maud_cap = int(HARVEY_TRAIN_TARGET * HARVEY_MAUD_CAP) if is_train else len(mauds)
        pref  = [r for r in mauds if r.get("mapped_issue_type") in HARVEY_MAUD_ISSUES]
        rest  = [r for r in mauds if r.get("mapped_issue_type") not in HARVEY_MAUD_ISSUES]
        maud_sel = pref + sample_to(rest, max(0, maud_cap - len(pref)))
        maud_sel = sample_to(maud_sel, maud_cap)

        combined = cuad_rows + ledgar_rows + maud_sel
        random.shuffle(combined)
        if target and len(combined) > target:
            combined = sample_to(combined, target)
        result[split] = combined

    return result


def build_kira(kira_rows: dict, maud_rows: dict) -> dict[str, list[dict]]:
    result = {s: [] for s in SPLITS}
    for split in SPLITS:
        rows  = kira_rows[split]
        mauds = maud_rows[split]
        is_train = split == "train"
        target = KIRA_TRAIN_TARGET if is_train else None

        by_src = partition_by_source(rows)
        ledgar_rows = cap_negatives(by_src.get("ledgar", []))
        cuad_rows   = cap_negatives(by_src.get("cuad",   []))   # all CUAD-kira rows

        # MAUD: prefer domain-relevant issues
        maud_cap = int(KIRA_TRAIN_TARGET * KIRA_MAUD_CAP) if is_train else len(mauds)
        pref  = [r for r in mauds if r.get("mapped_issue_type") in KIRA_MAUD_ISSUES]
        rest  = [r for r in mauds if r.get("mapped_issue_type") not in KIRA_MAUD_ISSUES]
        maud_sel = pref + sample_to(rest, max(0, maud_cap - len(pref)))
        maud_sel = sample_to(maud_sel, maud_cap)

        combined = ledgar_rows + cuad_rows + maud_sel
        random.shuffle(combined)
        if target and len(combined) > target:
            combined = sample_to(combined, target)
        result[split] = combined

    return result


# ── Stats ─────────────────────────────────────────────────────────────────────

def print_stats(branch: str, result: dict) -> None:
    for split, rows in result.items():
        src   = Counter(r.get("source", "?") for r in rows)
        pos   = sum(1 for r in rows if r.get("risk_present", True))
        neg   = len(rows) - pos
        issues = Counter(r.get("mapped_issue_type", "?") for r in rows)
        top3  = ", ".join(f"{k}:{v}" for k, v in issues.most_common(3))
        print(f"  [{branch}] {split:5}: {len(rows):>7,}  pos={pos:,} neg={neg:,}  "
              f"src={dict(src)}  top_issues=[{top3}]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Build Branch Datasets")
    print("=" * 60)

    harvey_rows = {s: load_jsonl(NORM_DIR / f"harvey_{s}.jsonl") for s in SPLITS}
    kira_rows   = {s: load_jsonl(NORM_DIR / f"kira_{s}.jsonl")   for s in SPLITS}
    maud_rows   = {s: load_jsonl(NORM_DIR / f"maud_{s}.jsonl")   for s in SPLITS}
    val_rows    = {s: load_jsonl(NORM_DIR / f"validator_{s}.jsonl") for s in SPLITS}

    print("\n[Harvey]")
    harvey_out = build_harvey(harvey_rows, maud_rows)
    for split, rows in harvey_out.items():
        write_jsonl(rows, DISTILL_DIR / "harvey" / f"{split}.jsonl")
    print_stats("harvey", harvey_out)

    print("\n[Kira]")
    kira_out = build_kira(kira_rows, maud_rows)
    for split, rows in kira_out.items():
        write_jsonl(rows, DISTILL_DIR / "kira" / f"{split}.jsonl")
    print_stats("kira", kira_out)

    print("\n[Validator base — ContractNLI]")
    val_dir = DISTILL_DIR / "validator"
    for split, rows in val_rows.items():
        write_jsonl(rows, val_dir / f"base_{split}.jsonl")
        print(f"  [validator] {split:5}: {len(rows):>7,} rows")

    print("\n[MAUD reference]")
    maud_dir = DISTILL_DIR / "maud"
    for split, rows in maud_rows.items():
        write_jsonl(rows, maud_dir / f"{split}.jsonl")
        print(f"  [maud] {split:5}: {len(rows):>7,} rows")

    print(f"\nOutputs in {DISTILL_DIR}")
    print("\nDone. Run build_hard_negatives.py next.")


if __name__ == "__main__":
    main()
