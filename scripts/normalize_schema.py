#!/usr/bin/env python3
"""
normalize_schema.py — Phase 1 of the branch training pipeline.

Reads the existing curated JSONL files and enriches them to the canonical schema:
  contract_title, document_type, section_heading, left_context, right_context,
  full_local_context, risk_present, evidence_text, mapped_issue_type.

Reviewer rows are split by branch field:
  harvey → data/curated/normalized/harvey_{train,val,test}.jsonl
  kira   → data/curated/normalized/kira_{train,val,test}.jsonl

Other outputs:
  data/curated/normalized/validator_{train,val,test}.jsonl
  data/curated/normalized/maud_{train,val,test}.jsonl

Run: python -m scripts.normalize_schema
"""

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CURATED_DIR = DATA_DIR / "curated"
NORM_DIR = CURATED_DIR / "normalized"
NORM_DIR.mkdir(parents=True, exist_ok=True)

SPLITS = ("train", "val", "test")

HARVEY_ISSUES = {
    "liability_exposure", "termination_risk", "ip_risk",
    "financial_obligation", "restriction_clause", "dispute_resolution",
    "warranty_and_insurance", "governance_risk", "third_party_risk",
}
KIRA_ISSUES = {
    "compliance_obligation", "confidentiality_risk",
    "representation_risk", "jurisdictional_risk",
}

DOCUMENT_TYPE_MAP = {
    "cuad":        "Commercial Contract",
    "ledgar":      "Regulatory Provision",
    "maud":        "Merger Agreement",
    "contractnli": "Confidentiality Agreement",
}

SECTION_HEADING_MAP = {
    "liability_exposure":    "Limitation of Liability",
    "restriction_clause":    "Restrictive Covenants",
    "ip_risk":               "Intellectual Property",
    "financial_obligation":  "Payment and Financial Terms",
    "termination_risk":      "Term and Termination",
    "governance_risk":       "Governance and Control",
    "compliance_obligation": "Compliance and Regulatory",
    "dispute_resolution":    "Dispute Resolution",
    "confidentiality_risk":  "Confidentiality",
    "warranty_and_insurance":"Warranties and Insurance",
    "jurisdictional_risk":   "Governing Law and Jurisdiction",
    "representation_risk":   "Representations and Warranties",
    "third_party_risk":      "Third Party and Subcontracting",
}

SEVERITY_RISK_PRESENT = {"medium", "high", "critical"}


# ── I/O helpers ───────────────────────────────────────────────────────────────

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


# ── Field helpers ─────────────────────────────────────────────────────────────

def clean_contract_title(contract_id: str) -> str:
    """Extract a readable title from contract_id strings like 'ACME_01_01_2000-EX-10-AGREEMENT'."""
    if not contract_id:
        return ""
    # Strip file-path prefix pattern: UPPERCASE_DIGITS_DATE-EX-NN-
    title = re.sub(r'^[A-Z0-9]+_\d{2}_\d{2}_\d{4}-EX-\d+-', '', contract_id).strip()
    title = title.replace("_", " ").replace("-", " ").strip()
    return title or contract_id.strip()


def resolve_branch(row: dict) -> str:
    """Determine branch using explicit branch field with issue_type fallback."""
    branch = str(row.get("branch", "")).lower()
    if branch in ("harvey", "kira"):
        return branch
    issue = str(row.get("issue_type", ""))
    if issue in HARVEY_ISSUES:
        return "harvey"
    if issue in KIRA_ISSUES:
        return "kira"
    return "harvey"  # safe default


# ── Row normalizers ───────────────────────────────────────────────────────────

def normalize_reviewer_row(row: dict) -> dict:
    source     = str(row.get("source", ""))
    issue_type = str(row.get("issue_type", ""))
    severity   = str(row.get("severity", "")).lower()
    clause_text = str(row.get("clause_text", "")).strip()
    contract_id = str(row.get("contract_id", "")).strip()

    row.setdefault("contract_title",     clean_contract_title(contract_id))
    row.setdefault("document_type",      DOCUMENT_TYPE_MAP.get(source, "Contract"))
    row.setdefault("section_heading",    SECTION_HEADING_MAP.get(issue_type, "General Terms"))
    row.setdefault("left_context",       "")
    row.setdefault("right_context",      "")
    row.setdefault("full_local_context", clause_text)
    row["risk_present"]      = severity in SEVERITY_RISK_PRESENT
    row.setdefault("evidence_text",  "")
    row["mapped_issue_type"] = issue_type
    return row


def normalize_validator_row(row: dict) -> dict:
    premise = str(row.get("premise", "")).strip()
    row.setdefault("document_type",      DOCUMENT_TYPE_MAP.get(row.get("source", "contractnli"), "Confidentiality Agreement"))
    row.setdefault("contract_title",     "")
    row.setdefault("section_heading",    "Confidentiality")
    row.setdefault("left_context",       "")
    row.setdefault("right_context",      "")
    row.setdefault("full_local_context", premise)
    row.setdefault("evidence_text",      "")
    return row


def normalize_maud_row(row: dict) -> dict:
    passage    = str(row.get("passage", "")).strip()
    issue_type = str(row.get("issue_type", "representation_risk"))
    contract_id = str(row.get("contract_id", "")).strip()

    row.setdefault("contract_title",     contract_id.replace("_", " ").title())
    row["document_type"]      = "Merger Agreement"
    row.setdefault("section_heading",    str(row.get("category", "")))
    row["left_context"]       = ""
    row["right_context"]      = ""
    row["full_local_context"] = passage
    row["risk_present"]       = True   # all MAUD rows are meaningful deal points
    row.setdefault("evidence_text",  "")
    row["mapped_issue_type"]  = issue_type
    return row


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Normalize Schema")
    print("=" * 60)

    harvey:    dict[str, list[dict]] = {s: [] for s in SPLITS}
    kira:      dict[str, list[dict]] = {s: [] for s in SPLITS}
    validator: dict[str, list[dict]] = {s: [] for s in SPLITS}
    maud:      dict[str, list[dict]] = {s: [] for s in SPLITS}

    # ── Reviewer (dataset_a) ──────────────────────────────────────────────────
    print("\n[Reviewer — dataset_a]")
    for split in SPLITS:
        path = CURATED_DIR / "dataset_a" / f"reviewer_{split}.jsonl"
        rows = load_jsonl(path)
        h_count = k_count = 0
        for row in rows:
            row = normalize_reviewer_row(row)
            branch = resolve_branch(row)
            row["branch"] = branch
            if branch == "harvey":
                harvey[split].append(row)
                h_count += 1
            else:
                kira[split].append(row)
                k_count += 1
        print(f"  {split:5}: {len(rows):>7,} rows  harvey:{h_count:,}  kira:{k_count:,}")

    # ── Validator (dataset_b) ─────────────────────────────────────────────────
    print("\n[Validator — dataset_b]")
    for split in SPLITS:
        path = CURATED_DIR / "dataset_b" / f"validator_{split}.jsonl"
        rows = load_jsonl(path)
        for row in rows:
            validator[split].append(normalize_validator_row(row))
        print(f"  {split:5}: {len(rows):>7,} rows")

    # ── MAUD (dataset_c) ──────────────────────────────────────────────────────
    print("\n[MAUD — dataset_c]")
    for split in SPLITS:
        path = CURATED_DIR / "dataset_c" / f"maud_{split}.jsonl"
        rows = load_jsonl(path)
        for row in rows:
            maud[split].append(normalize_maud_row(row))
        print(f"  {split:5}: {len(rows):>7,} rows")

    # ── Write outputs ─────────────────────────────────────────────────────────
    print("\n[Writing]")
    total = 0
    for split in SPLITS:
        for name, bucket in [("harvey", harvey), ("kira", kira),
                              ("validator", validator), ("maud", maud)]:
            out = NORM_DIR / f"{name}_{split}.jsonl"
            write_jsonl(bucket[split], out)
            print(f"  {out.name}: {len(bucket[split]):,}")
            total += len(bucket[split])

    print(f"\n  Total rows written: {total:,}")
    print(f"  Output: {NORM_DIR}")
    print("\nDone. Run build_context_windows.py next.")


if __name__ == "__main__":
    main()
