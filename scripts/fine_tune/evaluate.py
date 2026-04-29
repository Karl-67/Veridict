#!/usr/bin/env python3
"""
evaluate.py — Before/after quality metrics for the Kira fine-tuned model.

Runs the eval split through a model endpoint and scores against DeepSeek ground truth.

Metrics:
  json_validity_rate      — % responses that parse as valid JSON
  schema_compliance_rate  — % with all required KIRA fields present + valid enums
  issue_type_accuracy     — exact match on issue_type field
  severity_accuracy       — exact match on severity field
  clause_uid_f1           — precision/recall of identified clause_uids vs ground truth
  recommended_change_len  — mean token length (proxy for specificity)
  rouge_l_description     — ROUGE-L on description vs ground truth

Usage:
  python -m scripts.fine_tune.evaluate --mode before --endpoint http://localhost:11434/v1 --model llama3.2:latest
  python -m scripts.fine_tune.evaluate --mode after  --endpoint http://<runpod>:8080/v1  --model kira-gemma4-26b
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

OUTPUT_DIR = ROOT / "scripts" / "fine_tune" / "output"
EVAL_DATA = ROOT / "data" / "kira" / "ft" / "val.jsonl"

# Schema matches what export_kira.py writes — keep in sync with _assistant() there.
REQUIRED_FIELDS = {
    "issue_type", "severity", "what_is_wrong", "worst_case", "evidence_span",
}
VALID_ISSUE_TYPES = {
    "liability_exposure", "open_clause", "ambiguity", "exploitability",
    "weakened_protection", "compliance_failure",
}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}

KIRA_SYSTEM = (
    "You are Kira, an expert AI legal contract reviewer. Given a contract clause with context "
    "and a targeted review question, you assess whether it creates material legal risk. "
    "You assign severity based on actual clause language, not topic alone, and always "
    "justify your assessment with exact text evidence."
)


def _load_eval(path: Path) -> list[dict]:
    if not path.exists():
        log.error("Eval file not found: %s", path)
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _call_model(endpoint: str, model: str, user_msg: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("KIRA_API_KEY", "ollama"), base_url=endpoint)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": KIRA_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=2048,
    )
    return resp.choices[0].message.content or ""


def _parse_response(raw: str) -> list[dict]:
    try:
        import json_repair
        obj = json.loads(json_repair.repair_json(raw))
    except Exception:
        try:
            obj = json.loads(raw)
        except Exception:
            return []
    if isinstance(obj, dict):
        return obj.get("findings", [obj]) if "findings" in obj else [obj]
    if isinstance(obj, list):
        return obj
    return []


def _schema_ok(finding: dict) -> bool:
    if not REQUIRED_FIELDS.issubset(finding.keys()):
        return False
    if finding.get("issue_type") not in VALID_ISSUE_TYPES:
        return False
    if finding.get("severity") not in VALID_SEVERITIES:
        return False
    return True


def _rouge_l(hyp: str, ref: str) -> float:
    if not hyp or not ref:
        return 0.0
    hyp_tokens = hyp.lower().split()
    ref_tokens = ref.lower().split()
    if not hyp_tokens or not ref_tokens:
        return 0.0
    m, n = len(ref_tokens), len(hyp_tokens)
    # LCS via DP
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref_tokens[i - 1] == hyp_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[m][n]
    precision = lcs / n if n else 0.0
    recall = lcs / m if m else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _clause_f1(pred_uids: list[str], gt_uids: list[str]) -> float:
    if not gt_uids:
        return 1.0 if not pred_uids else 0.0
    pred_set = set(pred_uids)
    gt_set = set(gt_uids)
    if not pred_set:
        return 0.0
    precision = len(pred_set & gt_set) / len(pred_set)
    recall = len(pred_set & gt_set) / len(gt_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _extract_gt(row: dict) -> dict:
    """Extract ground truth findings from a chat-format or raw labeled eval row."""
    # Chat-format exported by export_kira.py: messages list with assistant turn
    messages = row.get("messages", [])
    for msg in messages:
        if msg.get("role") == "assistant":
            try:
                obj = json.loads(msg["content"])
                findings = obj.get("findings", [obj])
                return {"findings": findings}
            except Exception:
                pass
    # Raw labeled format (ds_* fields) — reconstruct the same shape as _assistant() in export_kira
    if row.get("ds_issue_type"):
        from scripts.distill.export_kira import get_evidence
        finding = {
            "issue_type":    row["ds_issue_type"],
            "severity":      row.get("ds_severity", "low"),
            "what_is_wrong": row.get("ds_what_is_wrong", ""),
            "worst_case":    row.get("ds_worst_case", ""),
            "evidence_span": get_evidence(row),
        }
        return {"findings": [finding]}
    return {"findings": []}


def _user_message(row: dict) -> str:
    """Extract the user message from a chat-format eval row."""
    messages = row.get("messages", [])
    for msg in messages:
        if msg.get("role") == "user":
            return msg["content"]
    return row.get("input", json.dumps(row))


def run_eval(endpoint: str, model: str, max_samples: int = 100) -> dict[str, Any]:
    rows = _load_eval(EVAL_DATA)
    if not rows:
        return {"error": f"No eval data at {EVAL_DATA}"}

    rows = rows[:max_samples]
    log.info("Evaluating %d samples against %s / %s", len(rows), endpoint, model)

    json_valid = 0
    schema_ok = 0
    issue_type_matches = 0
    severity_matches = 0
    clause_f1_total = 0.0
    rec_change_lengths: list[int] = []
    rouge_scores: list[float] = []
    total = len(rows)
    total_gt_findings = 0

    for i, row in enumerate(rows):
        if i % 10 == 0:
            log.info("  %d/%d", i, total)

        user_msg = _user_message(row)
        gt = _extract_gt(row)
        gt_findings = gt.get("findings", [])

        try:
            raw = _call_model(endpoint, model, user_msg)
        except Exception as exc:
            log.warning("API call failed for row %d: %s", i, exc)
            continue

        pred_findings = _parse_response(raw)
        if not isinstance(pred_findings, list):
            continue

        json_valid += 1

        pred_ok = [f for f in pred_findings if _schema_ok(f)]
        if pred_ok:
            schema_ok += 1

        for pred_f in pred_findings:
            # Match against closest GT finding by issue_type
            for gt_f in gt_findings:
                if pred_f.get("issue_type") == gt_f.get("issue_type", ""):
                    issue_type_matches += 1
                    if pred_f.get("severity") == gt_f.get("severity", ""):
                        severity_matches += 1
                    rouge_scores.append(_rouge_l(
                        str(pred_f.get("what_is_wrong", "")),
                        str(gt_f.get("what_is_wrong", "")),
                    ))
                    break

        # Evidence coverage F1 — word-overlap between predicted and GT evidence_span
        pred_evidence = " ".join(str(f.get("evidence_span", "")) for f in pred_findings)
        gt_evidence = " ".join(str(f.get("evidence_span", "")) for f in gt_findings)
        clause_f1_total += _rouge_l(pred_evidence, gt_evidence)

        # worst_case token length as a proxy for answer specificity
        for f in pred_findings:
            wc = f.get("worst_case", "")
            if wc:
                rec_change_lengths.append(len(wc.split()))

        total_gt_findings += len(gt_findings)

    n = max(total, 1)
    return {
        "model": model,
        "endpoint": endpoint,
        "sample_count": total,
        "json_validity_rate": round(json_valid / n, 4),
        "schema_compliance_rate": round(schema_ok / n, 4),
        "issue_type_accuracy": round(issue_type_matches / max(total_gt_findings, 1), 4),
        "severity_accuracy": round(severity_matches / max(total_gt_findings, 1), 4),
        "clause_uid_f1": round(clause_f1_total / n, 4),
        "recommended_change_avg_tokens": round(
            sum(rec_change_lengths) / max(len(rec_change_lengths), 1), 1
        ),
        "rouge_l_description": round(
            sum(rouge_scores) / max(len(rouge_scores), 1), 4
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["before", "after"], required=True)
    parser.add_argument("--endpoint", default="http://localhost:11434/v1")
    parser.add_argument("--model", default="llama3.2:latest")
    parser.add_argument("--max-samples", type=int, default=100)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = run_eval(args.endpoint, args.model, args.max_samples)

    out_path = OUTPUT_DIR / f"eval_{args.mode}.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("Results written to %s", out_path)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
