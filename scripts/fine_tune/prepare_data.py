#!/usr/bin/env python3
"""
prepare_data.py — Normalize DeepSeek labels and export to Gemma 4 chat format.
Runs on RunPod at /workspace/verdict_training/.

Input:  /workspace/verdict_training/data/raw/{train,val,test}.jsonl  (raw DeepSeek labels)
Output: /workspace/verdict_training/data/ft/{train,val,test}.jsonl   (chat-format, ready to train)

ALL rows are kept — issue types are remapped to Kira's 6 categories, nothing discarded.
"""
import json, logging
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RAW_DIR = Path("/workspace/verdict_training/data/raw")
FT_DIR  = Path("/workspace/verdict_training/data/ft")

VALID_TYPES = {
    "liability_exposure", "open_clause", "ambiguity",
    "exploitability", "weakened_protection", "compliance_failure",
}

ISSUE_TYPE_MAP = {
    # Already canonical
    "liability_exposure":          "liability_exposure",
    "open_clause":                 "open_clause",
    "ambiguity":                   "ambiguity",
    "Ambiguity":                   "ambiguity",
    "exploitability":              "exploitability",
    "weakened_protection":         "weakened_protection",
    "compliance_failure":          "compliance_failure",
    # Financial / liability
    "ip_risk":                     "liability_exposure",
    "financial_obligation":        "liability_exposure",
    "warranty_and_insurance":      "liability_exposure",
    "third_party_risk":            "liability_exposure",
    "Termination Fee":             "liability_exposure",
    "Termination Fee Trigger":     "liability_exposure",
    "Liquidated Damages":          "liability_exposure",
    "Representations and Warranties": "liability_exposure",
    "Remedies":                    "liability_exposure",
    "Payment Terms":               "liability_exposure",
    "Material Adverse Effect":     "liability_exposure",
    # Weakened protection
    "termination_risk":            "weakened_protection",
    "termination":                 "weakened_protection",
    "Termination":                 "weakened_protection",
    "Termination Rights":          "weakened_protection",
    "Deal Protection":             "weakened_protection",
    "Deal Protection and Related Provisions": "weakened_protection",
    "Deal Protection Provisions":  "weakened_protection",
    "Fiduciary Out":               "weakened_protection",
    "Fiduciary Out Limitation":    "weakened_protection",
    "Fiduciary Out Limitations":   "weakened_protection",
    "Fiduciary Exception":         "weakened_protection",
    "Fiduciary Termination Right": "weakened_protection",
    "Fiduciary Termination Right Limitations": "weakened_protection",
    "No-Shop":                     "weakened_protection",
    "Materiality Scrape":          "weakened_protection",
    "Materiality/MAE Scrape":      "weakened_protection",
    "Specific Performance":        "weakened_protection",
    "Consent Rights":              "weakened_protection",
    # Exploitability
    "restriction_clause":          "exploitability",
    "Conditions to Closing":       "exploitability",
    "Closing Conditions":          "exploitability",
    "Closing Condition":           "exploitability",
    "Matching Rights":             "exploitability",
    "Matching Rights Period":      "exploitability",
    "Operating and Efforts Covenant": "exploitability",
    "Operating Covenant":          "exploitability",
    "Negative Interim Covenant":   "exploitability",
    "Ordinary Course Covenant":    "exploitability",
    "Acquisition Proposal Timing": "exploitability",
    "Unilateral Termination":      "exploitability",
    "Change of Control":           "exploitability",
    "Conditions Precedent":        "exploitability",
    "Covenants":                   "exploitability",
    "Limitations on FTR Exercise": "exploitability",
    # Ambiguity
    "governance_risk":             "ambiguity",
    "Knowledge Definition":        "ambiguity",
    "Knowledge":                   "ambiguity",
    "Knowledge Qualifier":         "ambiguity",
    "Bringdown Standard":          "ambiguity",
    "Intervening Event Definition":"ambiguity",
    "Intervening Event":           "ambiguity",
    "Definitions":                 "ambiguity",
    "Fiduciary Out Standard":      "ambiguity",
    "Material Adverse Effect Definition": "ambiguity",
    "Material Adverse Effect definition": "ambiguity",
    "MAE Definition":              "ambiguity",
    # Open clause
    "Tail Period Length":          "open_clause",
    "Tail Period":                 "open_clause",
    # Compliance
    "compliance_obligation":       "compliance_failure",
    "jurisdictional_risk":         "compliance_failure",
    "Accuracy of Representations": "compliance_failure",
}


def _fallback_type(issue_type_raw: str, what_is_wrong: str) -> str:
    text = ((issue_type_raw or "") + " " + (what_is_wrong or "")).lower()
    if any(k in text for k in ("liabilit", "damage", "penalty", "fine", "compensat", "indemni", "ip ", "patent", "copyright")):
        return "liability_exposure"
    if any(k in text for k in ("terminat", "cancel", "exit", "withdraw")):
        return "weakened_protection"
    if any(k in text for k in ("ambig", "unclear", "vague", "undefined", "defin", "unknown", "subjective")):
        return "ambiguity"
    if any(k in text for k in ("compliance", "regulat", "statute", "gdpr", "tax")):
        return "compliance_failure"
    if any(k in text for k in ("restrict", "prohibit", "limit", "block", "prevent", "lock")):
        return "exploitability"
    if any(k in text for k in ("protect", "waiv", "reduc", "weaken", "right", "remedy")):
        return "weakened_protection"
    return "open_clause"


def normalize_issue_type(raw, what_is_wrong: str):
    if not raw:
        return None
    normalized = ISSUE_TYPE_MAP.get(raw)
    if normalized:
        return normalized
    result = _fallback_type(raw, what_is_wrong)
    log.debug("Unmapped %r -> %s", raw, result)
    return result


def get_evidence(row: dict) -> str:
    if row.get("ds_evidence_valid"):
        return (row.get("ds_evidence_span") or "")[:300]
    gt = row.get("ground_truth_spans") or []
    if gt:
        return max(gt, key=len)[:300]
    return row.get("clause_text", "")[:200]


SYSTEM_KIRA = (
    "You are Kira, an expert AI legal contract reviewer. Given a contract clause with context "
    "and a targeted review question, you assess whether it creates material legal risk. "
    "You assign severity based on actual clause language, not topic alone, and always "
    "justify your assessment with exact text evidence."
)


def build_user_message(row: dict) -> str:
    if row.get("source") == "maud":
        return "\n".join([
            f"Contract: {row.get('contract_id', '')}",
            f"M&A category: {row.get('maud_category', '')}",
            f"Deal-point question: {row.get('maud_question', '')}",
            f"Attorney-verified answer: {row.get('maud_answer', '')}",
            "",
            f"--- CLAUSE ---\n{row.get('clause_text', '')}\n--- END CLAUSE ---",
        ])
    parts = [
        f"Contract: {row.get('contract_id', '')}",
        f"Clause type: {row.get('clause_type', '')}",
        f"Review question: {row.get('cuad_question', '')}",
        "",
    ]
    if row.get("left_context"):
        parts.append(f"Context before:\n{row['left_context']}")
    parts.append(f"--- CLAUSE ---\n{row.get('clause_text', '')}\n--- END CLAUSE ---")
    if row.get("right_context"):
        parts.append(f"Context after:\n{row['right_context']}")
    return "\n".join(parts)


def build_assistant_message(row: dict, normalized_type) -> str:
    if not normalized_type:
        return json.dumps({"findings": []}, ensure_ascii=False)
    finding = {
        "issue_type":    normalized_type,
        "severity":      row.get("ds_severity", "medium"),
        "what_is_wrong": row.get("ds_what_is_wrong", ""),
        "worst_case":    row.get("ds_worst_case", ""),
        "evidence_span": get_evidence(row),
    }
    return json.dumps({"findings": [finding]}, ensure_ascii=False)


def process_split(split: str) -> None:
    src = RAW_DIR / f"{split}.jsonl"
    dst = FT_DIR / f"{split}.jsonl"
    if not src.exists():
        log.warning("Missing %s - skipping", src)
        return

    rows = []
    with open(src, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    log.info("%s: %d raw rows", split, len(rows))

    type_counter = Counter()
    out_rows = []
    for row in rows:
        raw_type = row.get("ds_issue_type")
        normalized = normalize_issue_type(raw_type, row.get("ds_what_is_wrong", ""))
        type_counter[normalized or "no_risk"] += 1
        out_rows.append({
            "messages": [
                {"role": "system",    "content": SYSTEM_KIRA},
                {"role": "user",      "content": build_user_message(row)},
                {"role": "assistant", "content": build_assistant_message(row, normalized)},
            ]
        })

    FT_DIR.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    log.info("%s: wrote %d rows to %s", split, len(out_rows), dst)
    log.info("  Distribution: %s", dict(type_counter.most_common()))


if __name__ == "__main__":
    log.info("=== Kira data normalization + export ===")
    for split in ("train", "val", "test"):
        process_split(split)
    log.info("=== Done. FT data at %s ===", FT_DIR)
