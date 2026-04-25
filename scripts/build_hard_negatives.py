#!/usr/bin/env python3
"""
build_hard_negatives.py — Phase 4 of the branch training pipeline.

Constructs 6 types of hard negatives and appends them to Harvey and Kira
branch training files (train split only). Val/test splits are left clean.

Hard negative types:
  1. scary_vocab_safe    — boilerplate rows with risk vocabulary but low severity
  2. adjacent_non_risk   — same-contract neighbor clause labeled risk_present=False
  3. corrupted_evidence  — positive row with evidence span replaced by unrelated text
  4. wrong_issue_label   — positive row with issue_type swapped to adjacent-but-wrong category
  5. severity_inflation  — low/medium row relabeled high (Validator should reject)
  6. paraphrased_finding — description paraphrased to sever clause grounding (Validator rejects)

Target: 15% of each branch's train set.
Type budget distribution: see TYPE_BUDGET_FRAC.

Reads:
  data/distillation/harvey/train.jsonl
  data/distillation/kira/train.jsonl
  data/curated/boilerplate_archive.jsonl

Writes (in-place merges — only train.jsonl):
  data/distillation/harvey/train.jsonl
  data/distillation/kira/train.jsonl
  data/curated/hard_negatives/hard_negatives.jsonl   (all HNs for inspection)

Run: python -m scripts.build_hard_negatives
"""

import hashlib
import json
import random
import re
from collections import defaultdict
from pathlib import Path

ROOT        = Path(__file__).resolve().parent.parent
DATA_DIR    = ROOT / "data"
DISTILL_DIR = DATA_DIR / "distillation"
CURATED_DIR = DATA_DIR / "curated"
HN_DIR      = CURATED_DIR / "hard_negatives"
HN_DIR.mkdir(parents=True, exist_ok=True)

BOILERPLATE_FILE = CURATED_DIR / "boilerplate_archive.jsonl"

HARD_NEG_FRACTION = 0.15   # hard negatives as fraction of train size

TYPE_BUDGET_FRAC = {
    "scary_vocab_safe":    0.25,
    "adjacent_non_risk":   0.20,
    "corrupted_evidence":  0.15,
    "wrong_issue_label":   0.15,
    "severity_inflation":  0.15,
    "paraphrased_finding": 0.10,
}

RISK_VOCABULARY = [
    "indemnif", "liabilit", "terminat", "penalt", "forfeit",
    "damages", "injunction", "liquidat", "warrant", "comply",
    "obligat", "restrict", "prohibit", "disclos", "confiden",
    "govern", "arbitrat", "jurisdict", "represent", "covenant",
]

# Plausible-but-wrong issue label swaps
ADJACENT_ISSUES: dict[str, list[str]] = {
    "liability_exposure":    ["warranty_and_insurance", "financial_obligation"],
    "restriction_clause":    ["ip_risk", "governance_risk"],
    "ip_risk":               ["restriction_clause", "third_party_risk"],
    "financial_obligation":  ["liability_exposure", "termination_risk"],
    "termination_risk":      ["financial_obligation", "governance_risk"],
    "governance_risk":       ["termination_risk", "restriction_clause"],
    "compliance_obligation": ["jurisdictional_risk", "representation_risk"],
    "dispute_resolution":    ["liability_exposure", "jurisdictional_risk"],
    "confidentiality_risk":  ["representation_risk", "restriction_clause"],
    "warranty_and_insurance":["liability_exposure", "compliance_obligation"],
    "jurisdictional_risk":   ["compliance_obligation", "dispute_resolution"],
    "representation_risk":   ["confidentiality_risk", "compliance_obligation"],
    "third_party_risk":      ["ip_risk", "compliance_obligation"],
}

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def hn_id(base: str, suffix: str) -> str:
    raw = f"{base}_{suffix}"
    h   = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"hn_{h}_{suffix[:4]}"


def has_risk_vocab(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in RISK_VOCABULARY)


def corrupt_span(text: str, pool: list[str]) -> str:
    """Replace the first sentence with a random unrelated clause snippet."""
    sents = re.split(r'(?<=[.!?])\s+', text.strip())
    if not sents or not pool:
        return text
    sents[0] = random.choice(pool)[:150]
    return " ".join(sents)


# Simple rule-based paraphrase: weaken risk signals without making it obviously wrong
PARAPHRASE_RULES = [
    (r'\bsignificant\b', 'minor'),
    (r'\bhigh[\s-]risk\b', 'low-risk'),
    (r'\bcritical\b', 'standard'),
    (r'\brisky\b', 'routine'),
    (r'\bexposure\b', 'obligation'),
    (r'\bliabilit\w+\b', 'obligation'),
    (r'\btermination\b', 'renewal'),
    (r'\bdamages\b', 'consideration'),
    (r'\bindemnif\w+\b', 'support'),
    (r'\bsevere\b', 'limited'),
    (r'\bmaterial\b', 'minor'),
    (r'\bexploit\w+\b', 'exercise'),
]


def paraphrase(text: str) -> str:
    result = text
    for pat, rep in PARAPHRASE_RULES:
        result = re.sub(pat, rep, result, flags=re.IGNORECASE)
    return result


# ── Hard-negative constructors ────────────────────────────────────────────────

def build_scary_vocab_safe(boilerplate: list[dict], budget: int) -> list[dict]:
    """Type 1: boilerplate with risk vocab but explicitly safe."""
    candidates = [
        r for r in boilerplate
        if has_risk_vocab(str(r.get("clause_text", "")))
        and str(r.get("severity", "low")).lower() in ("low", "")
    ]
    random.shuffle(candidates)
    result = []
    for row in candidates[:budget]:
        hn = dict(row)
        hn["id"]            = hn_id(str(row.get("id", "")), "svs")
        hn["risk_present"]  = False
        hn["severity"]      = "low"
        hn["negative_type"] = "scary_vocab_safe"
        hn["description"]   = (
            "Although this clause uses legal-sounding language, it is standard "
            "boilerplate with no material risk."
        )
        hn["negative_label"] = "no_finding"
        result.append(hn)
    return result


def build_adjacent_non_risk(positives: list[dict], budget: int) -> list[dict]:
    """Type 2: neighbor clause in same contract, labeled not risky."""
    by_contract: dict[str, list[dict]] = defaultdict(list)
    for r in positives:
        by_contract[str(r.get("contract_id", ""))].append(r)

    result = []
    for contract_rows in by_contract.values():
        if len(contract_rows) < 2:
            continue
        for i, row in enumerate(contract_rows):
            neighbor = contract_rows[(i + 1) % len(contract_rows)]
            if neighbor.get("id") == row.get("id"):
                continue
            hn = dict(neighbor)
            hn["id"]            = hn_id(str(row.get("id", "")), "anr")
            hn["risk_present"]  = False
            hn["severity"]      = "low"
            hn["negative_type"] = "adjacent_non_risk"
            hn["negative_label"] = "no_finding"
            hn["description"]   = (
                "This clause is adjacent to a flagged provision but does not itself "
                "create material legal risk."
            )
            result.append(hn)
            if len(result) >= budget:
                return result
    return result[:budget]


def build_corrupted_evidence(positives: list[dict], budget: int) -> list[dict]:
    """Type 3: positive with evidence/description corrupted."""
    all_texts = [str(r.get("clause_text", "")) for r in positives if r.get("clause_text")]
    candidates = [r for r in positives if r.get("evidence_text") or r.get("description")]
    random.shuffle(candidates)
    result = []
    for row in candidates[:budget]:
        hn = dict(row)
        hn["id"]            = hn_id(str(row.get("id", "")), "ce")
        src_text            = str(row.get("evidence_text") or row.get("description", ""))
        hn["evidence_text"] = corrupt_span(src_text, all_texts)
        hn["negative_type"] = "corrupted_evidence"
        hn["negative_label"] = "reject"   # Validator should reject
        result.append(hn)
    return result[:budget]


def build_wrong_issue_label(positives: list[dict], budget: int) -> list[dict]:
    """Type 4: positive with issue_type swapped to adjacent-but-wrong category."""
    candidates = [r for r in positives if str(r.get("issue_type", "")) in ADJACENT_ISSUES]
    random.shuffle(candidates)
    result = []
    for row in candidates[:budget]:
        issue       = str(row.get("issue_type", ""))
        wrong_pool  = ADJACENT_ISSUES.get(issue, [])
        if not wrong_pool:
            continue
        hn = dict(row)
        hn["id"]                = hn_id(str(row.get("id", "")), "wil")
        hn["issue_type"]        = random.choice(wrong_pool)
        hn["mapped_issue_type"] = hn["issue_type"]
        hn["negative_type"]     = "wrong_issue_label"
        hn["negative_label"]    = "reject"
        result.append(hn)
    return result[:budget]


def build_severity_inflation(rows: list[dict], budget: int) -> list[dict]:
    """Type 5: low/medium row with severity inflated to high."""
    candidates = [r for r in rows if str(r.get("severity", "")).lower() in ("low", "medium")]
    random.shuffle(candidates)
    result = []
    for row in candidates[:budget]:
        hn = dict(row)
        hn["id"]                 = hn_id(str(row.get("id", "")), "si")
        hn["original_severity"]  = str(row.get("severity", ""))
        hn["severity"]           = "high"
        hn["negative_type"]      = "severity_inflation"
        hn["negative_label"]     = "reject"
        result.append(hn)
    return result[:budget]


def build_paraphrased_finding(positives: list[dict], budget: int) -> list[dict]:
    """Type 6: description paraphrased to break clause grounding."""
    candidates = [r for r in positives if r.get("description")]
    random.shuffle(candidates)
    result = []
    for row in candidates[:budget]:
        hn = dict(row)
        hn["id"]             = hn_id(str(row.get("id", "")), "pf")
        hn["description"]    = paraphrase(str(row.get("description", "")))
        hn["recommendation"] = paraphrase(str(row.get("recommendation", "")))
        hn["negative_type"]  = "paraphrased_finding"
        hn["negative_label"] = "reject"
        hn["risk_present"]   = False
        result.append(hn)
    return result[:budget]


# ── Branch processor ──────────────────────────────────────────────────────────

def process_branch(branch: str, boilerplate: list[dict]) -> list[dict]:
    train_path = DISTILL_DIR / branch / "train.jsonl"
    train_rows = load_jsonl(train_path)
    if not train_rows:
        print(f"  [WARN] No train rows for branch={branch}")
        return []

    total_budget = max(1, int(len(train_rows) * HARD_NEG_FRACTION))
    budgets      = {t: max(1, int(total_budget * f)) for t, f in TYPE_BUDGET_FRAC.items()}
    positives    = [r for r in train_rows if r.get("risk_present", True)]

    print(f"\n[{branch.upper()}] {len(train_rows):,} train rows  "
          f"positives:{len(positives):,}  HN budget:{total_budget:,}")

    builders = [
        ("scary_vocab_safe",    build_scary_vocab_safe,    (boilerplate,  budgets["scary_vocab_safe"])),
        ("adjacent_non_risk",   build_adjacent_non_risk,   (positives,    budgets["adjacent_non_risk"])),
        ("corrupted_evidence",  build_corrupted_evidence,  (positives,    budgets["corrupted_evidence"])),
        ("wrong_issue_label",   build_wrong_issue_label,   (positives,    budgets["wrong_issue_label"])),
        ("severity_inflation",  build_severity_inflation,  (train_rows,   budgets["severity_inflation"])),
        ("paraphrased_finding", build_paraphrased_finding, (positives,    budgets["paraphrased_finding"])),
    ]

    all_hns: list[dict] = []
    for name, fn, args in builders:
        hns = fn(*args)
        for hn in hns:
            hn["branch"] = branch
        print(f"  {name:25}: {len(hns):>5,}  (budget {budgets[name]:,})")
        all_hns.extend(hns)

    merged = train_rows + all_hns
    random.shuffle(merged)
    write_jsonl(merged, train_path)
    print(f"  Merged train: {len(merged):,} rows  (+{len(all_hns):,} hard negatives)")
    return all_hns


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Build Hard Negatives")
    print("=" * 60)

    boilerplate = load_jsonl(BOILERPLATE_FILE)
    print(f"  Boilerplate archive: {len(boilerplate):,} rows")

    all_hns: list[dict] = []
    for branch in ("harvey", "kira"):
        hns = process_branch(branch, boilerplate)
        all_hns.extend(hns)

    out = HN_DIR / "hard_negatives.jsonl"
    write_jsonl(all_hns, out)
    print(f"\n  All hard negatives: {out}  ({len(all_hns):,} rows)")
    print("\nDone. Run scripts/distill/export_branch.py next.")


if __name__ == "__main__":
    main()
