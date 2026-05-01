"""
MLflow Model Promotion Script — Staging → Production

Checks eval gate thresholds against a model version's logged metrics,
then promotes it to Production (and archives the previous Production version).
Also patches configs/models.yaml to enable the newly promoted model.

Usage:
  python scripts/promote_model.py --model kira --version 3
  python scripts/promote_model.py --model kira          # latest Staging version
  python scripts/promote_model.py --model kira --dry-run

Environment variables:
  MLFLOW_TRACKING_URI   required — e.g. https://mlflow.yourdomain.com
  MLFLOW_MODEL_NAME     override for the registered model name (default: kira)
  VLLM_ENDPOINT         vLLM endpoint to write into configs/models.yaml on success
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Thresholds — must match eval_gate.py
# ---------------------------------------------------------------------------
THRESHOLDS: dict[str, tuple[str, float]] = {
    "live_eval.json_validity_rate":  (">=", 0.95),
    "live_eval.issue_type_f1":       (">=", 0.70),
    "live_eval.false_positive_rate": ("<=", 0.30),
    "live_eval.hallucination_rate":  ("<=", 0.05),
}

CONFIGS_PATH = Path("configs/models.yaml")
MODEL_KEY_MAP = {
    "kira":      "gemma_26b_finetuned",
    "harvey":    "gemma_26b_finetuned",
    "validator": "gemma_26b_finetuned",
}


def _log(msg: str) -> None:
    print(msg, flush=True)


def _fail(reason: str) -> None:
    _log(f"\nFAIL  {reason}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# MLflow helpers
# ---------------------------------------------------------------------------

def _mlflow_client():
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()
    if not tracking_uri:
        _fail("MLFLOW_TRACKING_URI is not set.")
    try:
        import mlflow
        mlflow.set_tracking_uri(tracking_uri)
        return mlflow.tracking.MlflowClient()
    except ImportError:
        _fail("mlflow package not installed. Run: pip install mlflow")


def _find_staging_version(client, model_name: str, version: str | None):
    """Return the target ModelVersion object."""
    try:
        if version:
            mv = client.get_model_version(model_name, version)
            if mv.current_stage not in ("Staging", "None"):
                _fail(
                    f"Version {version} is in stage '{mv.current_stage}', not Staging. "
                    "Only Staging versions can be promoted."
                )
            return mv
        # Latest Staging version
        versions = client.get_latest_versions(model_name, stages=["Staging"])
        if not versions:
            _fail(f"No versions of '{model_name}' are currently in Staging.")
        return sorted(versions, key=lambda v: int(v.version), reverse=True)[0]
    except Exception as exc:
        if "RESOURCE_DOES_NOT_EXIST" in str(exc):
            _fail(
                f"Registered model '{model_name}' not found in MLflow. "
                "Register a training run first:\n"
                "  mlflow.register_model(run_uri, model_name)"
            )
        raise


def _check_metrics(client, run_id: str, dry_run: bool) -> bool:
    """Verify all eval gate thresholds pass for the given run."""
    _log("\n[ Threshold Check ]")
    run = client.get_run(run_id)
    metrics = run.data.metrics

    all_pass = True
    for metric_key, (op, threshold) in THRESHOLDS.items():
        value = metrics.get(metric_key)
        if value is None:
            _log(f"  WARN  {metric_key}: not logged — skipping (run may predate eval gate)")
            continue
        ok = (value >= threshold) if op == ">=" else (value <= threshold)
        symbol = "PASS" if ok else "FAIL"
        _log(f"  {metric_key}: {value:.3f} (threshold {op} {threshold}) {symbol}")
        if not ok:
            all_pass = False

    return all_pass


# ---------------------------------------------------------------------------
# configs/models.yaml patch
# ---------------------------------------------------------------------------

def _patch_configs(model_role: str, version: str, endpoint: str) -> None:
    """Enable the promoted model in configs/models.yaml."""
    if not CONFIGS_PATH.exists():
        _log(f"  WARN  {CONFIGS_PATH} not found — skipping config patch")
        return

    config = yaml.safe_load(CONFIGS_PATH.read_text(encoding="utf-8")) or {}
    key = MODEL_KEY_MAP.get(model_role.lower(), "gemma_26b_finetuned")

    if key not in config.get("models", {}):
        _log(f"  WARN  key '{key}' not in models.yaml — skipping config patch")
        return

    config["models"][key]["enabled"] = True
    config["models"][key]["provider_url"] = endpoint or None
    config["models"][key]["mlflow_version"] = version
    config["models"][key]["notes"] = f"Promoted to Production (version {version})"

    CONFIGS_PATH.write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    _log(f"  Patched {CONFIGS_PATH}: {key} enabled=true, provider_url={endpoint or 'null'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Promote an MLflow model version from Staging to Production.")
    parser.add_argument("--model",   default=os.getenv("MLFLOW_MODEL_NAME", "kira"),
                        help="Registered model name in MLflow (default: kira)")
    parser.add_argument("--version", default=None,
                        help="Model version number. Defaults to latest Staging version.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check thresholds and print plan without making any changes.")
    args = parser.parse_args()

    vllm_endpoint = os.getenv("VLLM_ENDPOINT", "").strip()

    _log("=" * 60)
    _log(f"Veridict Model Promotion  |  model: {args.model}")
    _log(f"Dry run: {args.dry_run}")
    _log("=" * 60)

    client = _mlflow_client()

    # 1. Find version to promote
    mv = _find_staging_version(client, args.model, args.version)
    _log(f"\nTarget:  {args.model} v{mv.version}  (stage: {mv.current_stage})")
    _log(f"Run ID:  {mv.run_id}")
    _log(f"Source:  {mv.source}")

    # 2. Check eval gate thresholds
    metrics_ok = _check_metrics(client, mv.run_id, args.dry_run)

    if not metrics_ok:
        _fail("Threshold check failed — promotion blocked. Fix the model and re-run eval gate.")

    _log("\n  All thresholds met.")

    if args.dry_run:
        _log("\n[DRY RUN] Would promote to Production and archive previous version.")
        _log("  Re-run without --dry-run to apply changes.")
        sys.exit(0)

    # 3. Archive current Production version(s)
    _log("\n[ Archiving current Production version(s) ]")
    current_prod = client.get_latest_versions(args.model, stages=["Production"])
    for old in current_prod:
        client.transition_model_version_stage(
            name=args.model,
            version=old.version,
            stage="Archived",
            archive_existing_versions=False,
        )
        _log(f"  Archived {args.model} v{old.version}")

    # 4. Promote to Production
    _log(f"\n[ Promoting {args.model} v{mv.version} → Production ]")
    client.transition_model_version_stage(
        name=args.model,
        version=mv.version,
        stage="Production",
        archive_existing_versions=False,
    )
    client.set_model_version_tag(args.model, mv.version, "promoted_by", "promote_model.py")
    _log(f"  PASS  {args.model} v{mv.version} is now Production")

    # 5. Patch configs/models.yaml
    _log("\n[ Patching configs/models.yaml ]")
    _patch_configs(args.model, mv.version, vllm_endpoint)

    # 6. Done
    _log("\n" + "=" * 60)
    _log(f"PASS  Promotion complete: {args.model} v{mv.version} is Production")
    if vllm_endpoint:
        _log(f"  Endpoint: {vllm_endpoint}")
    else:
        _log("  Set VLLM_ENDPOINT env var to auto-patch configs/models.yaml with endpoint URL")
    _log("=" * 60)


if __name__ == "__main__":
    main()
