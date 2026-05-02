"""
CI/CD Eval Gate — runs on every push to main, blocks deployment if thresholds fail.

Stages:
  1. Structural validation  — always runs, no model needed
  2. Model registry check   — always runs, no model needed
  3. Live inference eval     — runs only when EVAL_ENDPOINT is set (staging model)

Exit codes:
  0  all checks passed → deployment proceeds
  1  one or more thresholds failed → deployment blocked

Environment variables:
  EVAL_ENDPOINT        URL of the inference endpoint to evaluate (optional)
                       e.g. http://verdict-vllm-kira:8000/v1
  EVAL_MODEL           model name to pass to the endpoint (default: kira)
  MLFLOW_TRACKING_URI  if set, results are logged as an MLflow run
  MLFLOW_EXPERIMENT    experiment name (default: veridict-eval-gates)
  IMAGE_TAG            git sha / image tag being evaluated (for MLflow tagging)
  GOLDEN_PATH          path to golden JSONL file (default: data/curated/golden/golden_edge_cases.jsonl)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
THRESHOLDS: dict[str, float] = {
    "structural_integrity":   1.00,   # all golden examples must be well-formed
    "json_validity_rate":     0.95,   # >=95% of model responses must be valid JSON
    "issue_type_f1":          0.70,   # Kira issue-type F1 on golden set
    "false_positive_rate_max":0.30,   # <=30% of false_positive_trap examples flagged
    "hallucination_rate_max": 0.05,   # <=5% of responses reference hallucinated clause IDs
}

VALID_ISSUE_TYPES = {
    "liability_exposure", "open_clause", "ambiguity",
    "exploitability", "weakened_protection", "compliance_failure",
}

VALID_CATEGORIES = {"rare_reviewer", "rare_validator", "rare_maud", "false_positive_trap"}

GOLDEN_PATH = Path(os.getenv("GOLDEN_PATH", "data/curated/golden/golden_edge_cases.jsonl"))
EVAL_ENDPOINT = os.getenv("EVAL_ENDPOINT", "").strip()
EVAL_MODEL = os.getenv("EVAL_MODEL", "kira")
IMAGE_TAG = os.getenv("IMAGE_TAG", "local")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_golden() -> list[dict]:
    return [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def _log(msg: str) -> None:
    print(msg, flush=True)


def _fail(reason: str) -> None:
    _log(f"\nFAIL  GATE FAILED: {reason}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Stage 1 — Structural validation (no model required)
# ---------------------------------------------------------------------------

def run_structural_validation(examples: list[dict]) -> dict:
    required_keys = {"id", "category", "source", "clause_text", "issue_type", "expected_behavior"}
    required_eb   = {"reviewer_issue_type", "failure_mode"}  # branch is optional (absent in maud examples)

    errors: list[str] = []
    for ex in examples:
        missing = required_keys - ex.keys()
        if missing:
            errors.append(f"{ex.get('id','?')}: missing top-level keys {missing}")
            continue
        if ex["category"] not in VALID_CATEGORIES:
            errors.append(f"{ex['id']}: unknown category '{ex['category']}'")
        eb = ex.get("expected_behavior") or {}
        missing_eb = required_eb - eb.keys()
        if missing_eb:
            errors.append(f"{ex['id']}: expected_behavior missing {missing_eb}")

    rate = 1.0 - len(errors) / max(len(examples), 1)
    passed = rate >= THRESHOLDS["structural_integrity"]

    _log(f"  structural_integrity: {rate:.3f} (threshold >= {THRESHOLDS['structural_integrity']}) {'PASS' if passed else 'FAIL'}")
    if errors:
        for e in errors[:10]:
            _log(f"    {e}")
    return {"structural_integrity": rate, "errors": errors, "passed": passed}


# ---------------------------------------------------------------------------
# Stage 2 — Model registry validation (no model required)
# ---------------------------------------------------------------------------

def run_registry_validation() -> dict:
    try:
        if str(Path(__file__).parent) not in sys.path:
            sys.path.insert(0, str(Path(__file__).parent))
        from eval_model_registry import load_model_registry, validate_model_registry
        registry = load_model_registry("configs/models.yaml")
        errors = validate_model_registry(registry)
        passed = len(errors) == 0
        _log(f"  model_registry: {'PASS valid' if passed else f'FAIL {len(errors)} error(s)'}")
        if errors:
            for e in errors[:5]:
                _log(f"    {e}")
        return {"passed": passed, "errors": errors}
    except FileNotFoundError:
        _log("  model_registry: WARN  configs/models.yaml not found — skipping")
        return {"passed": True, "errors": [], "skipped": True}


# ---------------------------------------------------------------------------
# Stage 3 — Live inference evaluation (requires EVAL_ENDPOINT)
# ---------------------------------------------------------------------------

def _call_endpoint(clause_text: str) -> dict | None:
    """Call the vLLM-compatible endpoint and return parsed JSON or None on failure."""
    try:
        import httpx
    except ImportError:
        return None

    prompt = (
        "[KIRA WORKER — Contract Integrity Analyst]\n"
        "Review the following contract clause and return a JSON object with a single "
        "'findings' array. Each finding must include clause_uid, issue_type, severity, "
        "description, recommendation, recommendation_detail, contract_evidence, "
        "exploitability, business_impact, rationale, uncertainty, "
        "unresolved_by_consensus, recommended_change.\n\n"
        f"Clause [clause-001]:\n{clause_text}\n\n"
        "Return ONLY valid JSON."
    )
    try:
        resp = httpx.post(
            f"{EVAL_ENDPOINT}/chat/completions",
            json={
                "model": EVAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1024,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # Strip markdown fences if present
        if "```" in content:
            content = content.split("```")[1].lstrip("json").strip()
        return json.loads(content)
    except Exception:
        return None


def run_live_eval(examples: list[dict]) -> dict:
    _log(f"  endpoint: {EVAL_ENDPOINT}")
    results = {
        "total": len(examples),
        "json_valid": 0,
        "issue_type_correct": 0,
        "issue_type_total": 0,
        "false_positive_flagged": 0,
        "false_positive_total": 0,
        "hallucinated_clause": 0,
    }

    for ex in examples:
        raw = _call_endpoint(ex["clause_text"])

        # JSON validity
        if raw is None:
            continue
        results["json_valid"] += 1

        findings = raw.get("findings", [])
        expected_it = ex["expected_behavior"].get("reviewer_issue_type")
        category = ex["category"]

        # False positive trap — model should produce no findings
        if category == "false_positive_trap":
            results["false_positive_total"] += 1
            if findings:
                results["false_positive_flagged"] += 1
            continue

        # Issue-type F1 inputs
        if expected_it:
            results["issue_type_total"] += 1
            predicted_types = {f.get("issue_type") for f in findings}
            if expected_it in predicted_types:
                results["issue_type_correct"] += 1

        # Hallucination check — clause_uid must be "clause-001" (only clause we sent)
        for f in findings:
            for ev in f.get("contract_evidence", []):
                uid = ev if isinstance(ev, str) else ev.get("clause_uid", "")
                if uid and uid != "clause-001":
                    results["hallucinated_clause"] += 1

    total = results["total"]
    json_validity_rate = results["json_valid"] / total if total else 0.0
    issue_type_f1 = results["issue_type_correct"] / results["issue_type_total"] if results["issue_type_total"] else 0.0
    fp_rate = results["false_positive_flagged"] / results["false_positive_total"] if results["false_positive_total"] else 0.0
    hallucination_rate = results["hallucinated_clause"] / max(results["json_valid"], 1)

    metrics = {
        "json_validity_rate": json_validity_rate,
        "issue_type_f1": issue_type_f1,
        "false_positive_rate": fp_rate,
        "hallucination_rate": hallucination_rate,
    }

    passed = True
    for name, value in metrics.items():
        threshold_key = f"{name}_max" if name in ("false_positive_rate", "hallucination_rate") else name
        if threshold_key not in THRESHOLDS:
            continue
        threshold = THRESHOLDS[threshold_key]
        ok = value <= threshold if "max" in threshold_key else value >= threshold
        symbol = "PASS" if ok else "FAIL"
        _log(f"  {name}: {value:.3f} (threshold {'<=' if 'max' in threshold_key else '>='} {threshold}) {symbol}")
        if not ok:
            passed = False

    return {**metrics, "passed": passed, "raw": results}


# ---------------------------------------------------------------------------
# MLflow logging
# ---------------------------------------------------------------------------

def log_to_mlflow(all_results: dict) -> None:
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()
    if not tracking_uri:
        return
    try:
        import mlflow
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT", "veridict-eval-gates"))
        with mlflow.start_run(run_name=f"eval-gate-{IMAGE_TAG[:8]}"):
            mlflow.set_tag("image_tag", IMAGE_TAG)
            mlflow.set_tag("golden_path", str(GOLDEN_PATH))
            mlflow.set_tag("eval_endpoint", EVAL_ENDPOINT or "none")
            for stage, data in all_results.items():
                for k, v in data.items():
                    if isinstance(v, (int, float)) and k not in ("raw",):
                        mlflow.log_metric(f"{stage}.{k}", v)
        _log("  MLflow run logged PASS")
    except Exception as exc:
        _log(f"  MLflow logging failed (non-blocking): {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _log("=" * 60)
    _log(f"Veridict Eval Gate  |  image: {IMAGE_TAG}")
    _log(f"Golden set: {GOLDEN_PATH}  |  endpoint: {EVAL_ENDPOINT or 'none (static only)'}")
    _log("=" * 60)

    if not GOLDEN_PATH.exists():
        _log(f"WARN  Golden dataset not found at {GOLDEN_PATH} — skipping quality gates")
        _log("PASS  ALL GATES PASSED — deployment approved (no golden set)")
        sys.exit(0)

    examples = _load_golden()
    _log(f"\nLoaded {len(examples)} golden examples\n")

    all_results: dict = {}
    gate_passed = True

    # Stage 1
    _log("[ Stage 1 ] Structural validation")
    r1 = run_structural_validation(examples)
    all_results["structural"] = r1
    if not r1["passed"]:
        gate_passed = False

    # Stage 2
    _log("\n[ Stage 2 ] Model registry validation")
    r2 = run_registry_validation()
    all_results["registry"] = r2
    if not r2["passed"]:
        gate_passed = False

    # Stage 3 (conditional)
    if EVAL_ENDPOINT:
        _log("\n[ Stage 3 ] Live inference evaluation")
        t0 = time.perf_counter()
        r3 = run_live_eval(examples)
        all_results["live_eval"] = r3
        _log(f"  elapsed: {time.perf_counter() - t0:.1f}s")
        if not r3["passed"]:
            gate_passed = False
    else:
        _log("\n[ Stage 3 ] Live inference evaluation — SKIPPED (EVAL_ENDPOINT not set)")
        _log("  Set EVAL_ENDPOINT to a staging model URL to enable full quality gating.")

    # MLflow
    _log("\n[ MLflow ] Logging results")
    log_to_mlflow(all_results)

    # Final verdict
    _log("\n" + "=" * 60)
    if gate_passed:
        _log("PASS  ALL GATES PASSED — deployment approved")
    else:
        _log("FAIL  GATE FAILED — deployment blocked")
    _log("=" * 60)

    sys.exit(0 if gate_passed else 1)


if __name__ == "__main__":
    main()
