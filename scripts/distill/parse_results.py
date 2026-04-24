#!/usr/bin/env python3
"""
parse_results.py — Parse completed batch results and merge GPT annotations
back into the original curated rows.

Reads:
  data/distillation/results/*_results.jsonl   (OpenAI batch outputs)
  data/distillation/batches/manifest.json     (hash → meta mapping)
  data/curated/dataset_a/reviewer_*.jsonl
  data/curated/dataset_b/validator_*.jsonl

Writes:
  data/distillation/annotated/reviewer_annotated.jsonl
  data/distillation/annotated/validator_annotated.jsonl
  data/distillation/annotated/sec_annotated.jsonl
  data/distillation/annotated/parse_report.json

Schema versions
---------------
v1 (old, isolation-only):
  GPT returns: score (0-5), reason, action, issue_type, confidence
v2 (context-aware, current):
  GPT returns: contract_type, risk_score (1-10), legal_analysis,
               inconsistencies, severity, severity_confidence, recommendations

Both are handled transparently. Detection: presence of "risk_score" key → v2.

Mapping from v2 → fields that export_gemma.py expects (unchanged):
  gpt_score      = round((risk_score - 1) * 5 / 9)   [0-5]
  gpt_reason     = legal_analysis
  gpt_action     = derived from severity
  gpt_issue_type = original row's issue_type (teacher does not return this)
  gpt_confidence = "high" if severity_confidence=="strong" else "low"
"""

import json
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from .config import ANNOTATED_DIR, BATCHES_DIR, CURATED_DIR, RESULTS_DIR, TEACHER_CLAUSE, TEACHER_CONTRACT
from .build_batches import text_hash

MANIFEST_FILE = BATCHES_DIR / "manifest.json"
SEC_CHUNK_MAP_FILE = BATCHES_DIR / "sec_chunk_map.jsonl"

VALID_ACTIONS = {"accept", "note", "flag", "redline", "reject"}
VALID_VERDICTS = {"retain", "reject", "uncertain"}
VALID_CONFIDENCE = {"high", "medium", "low"}

# v2 schema constants
_V2_SEVERITY_TO_ACTION = {
    "critical": "reject",
    "high":     "redline",
    "medium":   "flag",
    "low":      "note",
}
_V2_SEVERITY_CONFIDENCE_TO_GPT = {
    "strong": "high",
    "weak":   "low",
}
_V2_VALID_SEVERITIES = {"critical", "high", "medium", "low"}
_V2_VALID_SEVERITY_CONF = {"strong", "weak"}


# ── Result loading ────────────────────────────────────────────────────────────


def load_batch_results(result_files: list[Path]) -> dict[str, dict]:
    """Load all batch result files into a dict keyed by custom_id."""
    results: dict[str, dict] = {}
    for path in result_files:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                custom_id = obj.get("custom_id", "")
                if not custom_id:
                    continue
                try:
                    content = (
                        obj["response"]["body"]["choices"][0]["message"]["content"]
                    )
                    parsed = json.loads(content)
                    results[custom_id] = {"raw": parsed, "error": None}
                except (KeyError, json.JSONDecodeError, TypeError) as e:
                    results[custom_id] = {"raw": None, "error": str(e)}
    return results


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(rows: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ── Annotation helpers ────────────────────────────────────────────────────────


def safe_score(val) -> int | None:
    try:
        s = int(val)
        return s if 0 <= s <= 5 else None
    except (TypeError, ValueError):
        return None


def safe_risk_score(val) -> int | None:
    try:
        s = int(val)
        return s if 1 <= s <= 10 else None
    except (TypeError, ValueError):
        return None


def _risk_score_to_gpt_score(risk_score: int) -> int:
    """Map teacher's 1-10 risk_score to the 0-5 gpt_score used by export_gemma.py."""
    return min(5, round((risk_score - 1) * 5 / 9))


def annotate_clause(row: dict, gpt: dict, model: str) -> dict:
    """Dispatch to the correct schema handler based on GPT response content."""
    if "risk_score" in gpt:
        return _annotate_clause_v2(row, gpt, model)
    return _annotate_clause_v1(row, gpt, model)


def _annotate_clause_v1(row: dict, gpt: dict, model: str) -> dict:
    """Handle old (isolation-only) GPT schema: score/reason/action/issue_type/confidence."""
    score = safe_score(gpt.get("score"))
    action = gpt.get("action", "").lower()
    confidence = gpt.get("confidence", "").lower()
    return {
        **row,
        "gpt_score":       score,
        "gpt_reason":      str(gpt.get("reason", "")).strip(),
        "gpt_action":      action if action in VALID_ACTIONS else None,
        "gpt_issue_type":  str(gpt.get("issue_type", row.get("issue_type", ""))).strip(),
        "gpt_confidence":  confidence if confidence in VALID_CONFIDENCE else None,
        "gpt_model":       model,
        "gpt_ts":          datetime.now(timezone.utc).isoformat(),
    }


def _annotate_clause_v2(row: dict, gpt: dict, model: str) -> dict:
    """Handle new (context-aware) GPT schema:
    contract_type / risk_score / legal_analysis / inconsistencies /
    severity / severity_confidence / recommendations.

    Populates all fields that export_gemma.py expects (gpt_score, gpt_reason,
    gpt_action, gpt_issue_type, gpt_confidence) plus new v2-only columns.
    Also overrides the row's heuristic severity and severity_confidence with
    the teacher model's output.
    """
    risk_score = safe_risk_score(gpt.get("risk_score"))
    gpt_score = _risk_score_to_gpt_score(risk_score) if risk_score is not None else None

    severity = str(gpt.get("severity", "")).lower().strip()
    severity_confidence = str(gpt.get("severity_confidence", "")).lower().strip()
    legal_analysis = str(gpt.get("legal_analysis", "")).strip()

    inconsistencies = gpt.get("inconsistencies", [])
    if not isinstance(inconsistencies, list):
        inconsistencies = [str(inconsistencies)] if inconsistencies else []

    # Derive action from severity for export_gemma compatibility
    gpt_action = _V2_SEVERITY_TO_ACTION.get(severity, "flag")

    # Map severity_confidence → gpt_confidence vocabulary (high/medium/low)
    gpt_confidence = _V2_SEVERITY_CONFIDENCE_TO_GPT.get(severity_confidence)

    return {
        **row,
        # ── Fields read by export_gemma.py (must remain populated) ───────────
        "gpt_score":            gpt_score,
        "gpt_reason":           legal_analysis,
        "gpt_action":           gpt_action,
        # Preserve original issue_type — teacher schema does not return this
        "gpt_issue_type":       str(row.get("issue_type", "")).strip(),
        "gpt_confidence":       gpt_confidence,
        # ── v2-only columns ───────────────────────────────────────────────────
        "gpt_risk_score":       risk_score,
        "gpt_legal_analysis":   legal_analysis,
        "gpt_inconsistencies":  inconsistencies,
        "gpt_contract_type":    str(gpt.get("contract_type", "")).strip(),
        "gpt_recommendations":  str(gpt.get("recommendations", "")).strip(),
        # Override heuristic severity labels with teacher output
        "severity":             severity if severity in _V2_VALID_SEVERITIES else row.get("severity"),
        "severity_confidence":  severity_confidence if severity_confidence in _V2_VALID_SEVERITY_CONF else row.get("severity_confidence"),
        "gpt_model":            model,
        "gpt_ts":               datetime.now(timezone.utc).isoformat(),
    }


def annotate_nli(row: dict, gpt: dict, model: str) -> dict:
    score = safe_score(gpt.get("score"))
    verdict = gpt.get("verdict", "").lower()
    confidence = gpt.get("confidence", "").lower()
    return {
        **row,
        "gpt_score":      score,
        "gpt_verdict":    verdict if verdict in VALID_VERDICTS else None,
        "gpt_reason":     str(gpt.get("reason", "")).strip(),
        "gpt_confidence": confidence if confidence in VALID_CONFIDENCE else None,
        "gpt_model":      model,
        "gpt_ts":         datetime.now(timezone.utc).isoformat(),
    }


def annotate_clause_finding(row: dict, gpt: dict, model: str) -> dict:
    """Handle multi-clause reviewer finding schema (from USER_MULTI_CLAUSE prompt).

    Fields: clause_index, contract_type, risk_score (1-10), risk_analysis,
            false_positive_note, exploitability, severity, severity_confidence,
            recommendation.
    """
    risk_score = safe_risk_score(gpt.get("risk_score"))
    gpt_score = _risk_score_to_gpt_score(risk_score) if risk_score is not None else None

    severity = str(gpt.get("severity", "")).lower().strip()
    severity_confidence = str(gpt.get("severity_confidence", "")).lower().strip()
    risk_analysis = str(gpt.get("risk_analysis", "")).strip()
    false_positive_note = str(gpt.get("false_positive_note", "")).strip()
    exploitability = str(gpt.get("exploitability", "")).strip()
    recommendation = str(gpt.get("recommendation", "")).strip()
    contract_type = str(gpt.get("contract_type", "")).strip()

    gpt_action = _V2_SEVERITY_TO_ACTION.get(severity, "flag")
    gpt_confidence = _V2_SEVERITY_CONFIDENCE_TO_GPT.get(severity_confidence)

    return {
        **row,
        # Fields read by export_gemma.py (backward-compat names)
        "gpt_score":               gpt_score,
        "gpt_reason":              risk_analysis,
        "gpt_action":              gpt_action,
        "gpt_issue_type":          str(row.get("issue_type", "")).strip(),
        "gpt_confidence":          gpt_confidence,
        # Rich v3 fields
        "gpt_risk_score":          risk_score,
        "gpt_risk_analysis":       risk_analysis,
        "gpt_false_positive_note": false_positive_note,
        "gpt_exploitability":      exploitability,
        "gpt_contract_type":       contract_type,
        "gpt_recommendation":      recommendation,
        # Override heuristic severity with teacher output
        "severity":                severity if severity in _V2_VALID_SEVERITIES else row.get("severity"),
        "severity_confidence":     severity_confidence if severity_confidence in _V2_VALID_SEVERITY_CONF else row.get("severity_confidence"),
        "gpt_model":               model,
        "gpt_ts":                  datetime.now(timezone.utc).isoformat(),
    }


def annotate_maud(row: dict, gpt: dict, model: str) -> dict:
    """Annotate a MAUD row with GPT risk analysis."""
    risk_score = safe_risk_score(gpt.get("risk_score"))
    severity = str(gpt.get("severity", "")).lower().strip()
    confidence = str(gpt.get("confidence", "")).lower().strip()
    return {
        **row,
        "gpt_risk_owner":    str(gpt.get("risk_owner", "")).strip(),
        "gpt_risk_score":    risk_score,
        "gpt_risk_analysis": str(gpt.get("risk_analysis", "")).strip(),
        "gpt_exploitability":str(gpt.get("exploitability", "")).strip(),
        "gpt_severity":      severity if severity in _V2_VALID_SEVERITIES else None,
        "gpt_recommendation":str(gpt.get("recommendation", "")).strip(),
        "gpt_confidence":    confidence if confidence in VALID_CONFIDENCE else None,
        "gpt_model":         model,
        "gpt_ts":            datetime.now(timezone.utc).isoformat(),
    }


def annotate_sec(custom_id: str, gpt: dict, model: str) -> dict:
    parts = custom_id.split("_")
    row_idx = int(parts[1]) if len(parts) > 1 else -1
    chunk_idx = int(parts[2]) if len(parts) > 2 else -1
    score = safe_score(gpt.get("score"))
    action = gpt.get("action", "").lower()
    confidence = gpt.get("confidence", "").lower()
    return {
        "custom_id":      custom_id,
        "source":         "sec",
        "row_idx":        row_idx,
        "chunk_idx":      chunk_idx,
        "gpt_score":      score,
        "gpt_issue_type": str(gpt.get("issue_type", "")).strip(),
        "gpt_key_clause": str(gpt.get("key_clause", "")).strip(),
        "gpt_reason":     str(gpt.get("reason", "")).strip(),
        "gpt_action":     action if action in VALID_ACTIONS else None,
        "gpt_confidence": confidence if confidence in VALID_CONFIDENCE else None,
        "gpt_model":      model,
        "gpt_ts":         datetime.now(timezone.utc).isoformat(),
    }


# ── Per-dataset parsers ───────────────────────────────────────────────────────


def parse_reviewer(results: dict[str, dict], manifest: dict, model: str) -> tuple[list[dict], dict]:
    """Parse reviewer results using the contract_clause_map from the manifest.

    build_batches creates one request per full contract (custom_id =
    rev_contract_{hash(contract_id)}) whose response is a JSON array of findings
    ordered to match the manifest's clause list for that contract.  We expand
    the array back to individual clause rows here.
    """
    all_rows: list[dict] = []
    for split in ("train", "val", "test"):
        all_rows.extend(load_jsonl(CURATED_DIR / "dataset_a" / f"reviewer_{split}.jsonl"))

    if not all_rows:
        return [], {"skipped": "no curated data"}

    # Build clause_hash → finding dict from contract-level results
    contract_clause_map: dict[str, list[dict]] = manifest.get("reviewer", {}).get("contract_clause_map", {})
    clause_finding: dict[str, dict] = {}
    contracts_found = contracts_missing = 0

    for custom_id, clause_list in contract_clause_map.items():
        result = results.get(custom_id)
        if result is None or result.get("error") or result.get("raw") is None:
            contracts_missing += 1
            continue
        findings = result["raw"]
        if not isinstance(findings, list):
            # Unexpected scalar response — skip
            contracts_missing += 1
            continue
        contracts_found += 1
        for i, clause_meta in enumerate(clause_list):
            if i < len(findings):
                clause_finding[clause_meta["clause_hash"]] = findings[i]

    print(f"    contract results: {contracts_found} found, {contracts_missing} missing")

    annotated = []
    stats = {"total": len(all_rows), "annotated": 0, "missing": 0, "parse_error": 0}

    for row in all_rows:
        clause = str(row.get("clause_text", "")).strip()
        contract_id = str(row.get("contract_id", "")).strip()
        # Hash must match build_batches.py: sha256(clause_text + contract_id)
        h = text_hash(clause + contract_id)
        finding = clause_finding.get(h)

        if finding is None:
            stats["missing"] += 1
            annotated.append(row)
            continue
        if not isinstance(finding, dict):
            stats["parse_error"] += 1
            annotated.append(row)
            continue

        annotated.append(annotate_clause_finding(row, finding, model))
        stats["annotated"] += 1

    return annotated, stats


def parse_validator(results: dict[str, dict], model: str) -> tuple[list[dict], dict]:
    all_rows: list[dict] = []
    for split in ("train", "val", "test"):
        all_rows.extend(load_jsonl(CURATED_DIR / "dataset_b" / f"validator_{split}.jsonl"))

    if not all_rows:
        return [], {"skipped": "no curated data"}

    annotated = []
    stats = {"total": len(all_rows), "annotated": 0, "missing": 0, "parse_error": 0}

    for row in all_rows:
        premise = str(row.get("premise", "")).strip()
        hypothesis = str(row.get("hypothesis", "")).strip()
        custom_id = f"val_{row.get('id', text_hash(premise + hypothesis))}"
        result = results.get(custom_id)

        if result is None:
            stats["missing"] += 1
            annotated.append(row)
            continue
        if result["error"] or result["raw"] is None:
            stats["parse_error"] += 1
            annotated.append(row)
            continue

        annotated.append(annotate_nli(row, result["raw"], model))
        stats["annotated"] += 1

    return annotated, stats


def load_sec_chunk_map() -> dict[str, str]:
    """Load custom_id → chunk_text mapping saved by build_batches."""
    chunk_map: dict[str, str] = {}
    if not SEC_CHUNK_MAP_FILE.exists():
        return chunk_map
    with open(SEC_CHUNK_MAP_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                chunk_map[obj["custom_id"]] = obj["chunk_text"]
    return chunk_map


def parse_sec(results: dict[str, dict], model: str) -> tuple[list[dict], dict]:
    sec_results = {k: v for k, v in results.items() if k.startswith("sec_")}
    chunk_map = load_sec_chunk_map()
    rows = []
    stats = {"total": len(sec_results), "annotated": 0, "parse_error": 0}

    for custom_id, result in sec_results.items():
        if result["error"] or result["raw"] is None:
            stats["parse_error"] += 1
            rows.append({"custom_id": custom_id, "error": result["error"]})
            continue
        row = annotate_sec(custom_id, result["raw"], model)
        row["chunk_text"] = chunk_map.get(custom_id, "")
        rows.append(row)
        stats["annotated"] += 1

    rows.sort(key=lambda r: (r.get("row_idx", -1), r.get("chunk_idx", -1)))
    return rows, stats


def parse_maud(results: dict[str, dict], model: str) -> tuple[list[dict], dict]:
    """Parse MAUD results: one GPT response per unique (passage, question) pair."""
    all_rows: list[dict] = []
    for split in ("train", "val", "test"):
        all_rows.extend(load_jsonl(CURATED_DIR / "dataset_c" / f"maud_{split}.jsonl"))

    if not all_rows:
        return [], {"skipped": "no curated data"}

    annotated = []
    stats = {"total": len(all_rows), "annotated": 0, "missing": 0, "parse_error": 0}

    for row in all_rows:
        passage  = str(row.get("passage",  "")).strip()
        question = str(row.get("question", "")).strip()
        key = text_hash(passage + question)
        custom_id = f"maud_{key}"
        result = results.get(custom_id)

        if result is None:
            stats["missing"] += 1
            annotated.append(row)
            continue
        if result["error"] or result["raw"] is None:
            stats["parse_error"] += 1
            annotated.append(row)
            continue

        annotated.append(annotate_maud(row, result["raw"], model))
        stats["annotated"] += 1

    return annotated, stats


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 60)
    print("Parse Results")
    print("=" * 60)

    if not MANIFEST_FILE.exists():
        print(f"Manifest not found at {MANIFEST_FILE}. Run build_batches.py first.")
        return

    with open(MANIFEST_FILE) as f:
        manifest = json.load(f)

    all_result_files = list(RESULTS_DIR.glob("*_results.jsonl"))
    if not all_result_files:
        print(f"No result files in {RESULTS_DIR}. Run run_calls.py first.")
        return

    print(f"\nLoading {len(all_result_files)} result file(s)...")
    results = load_batch_results(all_result_files)
    print(f"  {len(results):,} total responses loaded")

    report = {}

    # Reviewer
    print("\n[Reviewer]")
    rev_model = manifest.get("reviewer", {}).get("model", TEACHER_CLAUSE)
    rev_rows, rev_stats = parse_reviewer(results, manifest, rev_model)
    if rev_rows:
        out = ANNOTATED_DIR / "reviewer_annotated.jsonl"
        write_jsonl(rev_rows, out)
        print(f"  {out.name}: {len(rev_rows):,} rows  {rev_stats}")
        report["reviewer"] = rev_stats

    # Validator
    print("\n[Validator]")
    val_model = manifest.get("validator", {}).get("model", TEACHER_CLAUSE)
    val_rows, val_stats = parse_validator(results, val_model)
    if val_rows:
        out = ANNOTATED_DIR / "validator_annotated.jsonl"
        write_jsonl(val_rows, out)
        print(f"  {out.name}: {len(val_rows):,} rows  {val_stats}")
        report["validator"] = val_stats

    # MAUD
    print("\n[MAUD]")
    maud_model = manifest.get("maud", {}).get("model", TEACHER_CLAUSE)
    maud_rows, maud_stats = parse_maud(results, maud_model)
    if maud_rows:
        out = ANNOTATED_DIR / "maud_annotated.jsonl"
        write_jsonl(maud_rows, out)
        print(f"  {out.name}: {len(maud_rows):,} rows  {maud_stats}")
        report["maud"] = maud_stats

    # SEC
    print("\n[SEC]")
    sec_model = manifest.get("sec", {}).get("model", TEACHER_CONTRACT)
    sec_rows, sec_stats = parse_sec(results, sec_model)
    if sec_rows:
        out = ANNOTATED_DIR / "sec_annotated.jsonl"
        write_jsonl(sec_rows, out)
        print(f"  {out.name}: {len(sec_rows):,} rows  {sec_stats}")
        report["sec"] = sec_stats

    report_path = ANNOTATED_DIR / "parse_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nParse report → {report_path}")
    print("Next: python -m scripts.run_distill export")


if __name__ == "__main__":
    main()
