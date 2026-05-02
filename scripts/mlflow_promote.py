#!/usr/bin/env python3
"""
mlflow_promote.py — Register and promote a deployed Kira model version to Production.

Called automatically by the CI deploy job after a successful blue-green switch
and passing smoke test.  Can also be run manually after a RunPod training +
manual deploy.

Usage:
  python scripts/mlflow_promote.py --model kira --image-tag <git-sha>
  python scripts/mlflow_promote.py --model kira --image-tag abc123 --dry-run

Environment:
  MLFLOW_TRACKING_URI   Azure ML workspace MLflow URI (required)
  MLFLOW_EXPERIMENT     experiment name (default: veridict-deployments)
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time


def _log(msg: str) -> None:
    print(msg, flush=True)


def _fail(reason: str) -> None:
    _log(f"\nFAIL  {reason}")
    sys.exit(1)


def promote(model_name: str, image_tag: str, dry_run: bool) -> None:
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()
    if not tracking_uri:
        _fail("MLFLOW_TRACKING_URI is not set.")

    try:
        import mlflow
    except ImportError:
        _fail("mlflow is not installed.  Run: pip install mlflow")

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT", "veridict-deployments"))

    client = mlflow.tracking.MlflowClient()

    # Ensure the registered model exists
    try:
        client.create_registered_model(
            model_name,
            description="Kira LoRA fine-tuned contract review model.",
        )
        _log(f"  Created registered model '{model_name}'")
    except Exception:
        _log(f"  Registered model '{model_name}' already exists")

    if dry_run:
        _log(f"\n[DRY RUN] Would register and promote '{model_name}' image_tag={image_tag}")
        _log("  Re-run without --dry-run to apply.")
        return

    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Start a lightweight traceability run so the version has provenance
    with mlflow.start_run(run_name=f"promote-{model_name}-{image_tag[:8]}") as run:
        mlflow.log_param("model_name", model_name)
        mlflow.log_param("image_tag", image_tag)
        mlflow.set_tag("llmops.phase", "promotion")
        mlflow.set_tag("deployed_at", timestamp)
        mlflow.log_dict(
            {"model_name": model_name, "image_tag": image_tag, "promoted_at": timestamp},
            "promotion_manifest.json",
        )
        run_id = run.info.run_id

    # Create the model version linked to the promotion run
    version = client.create_model_version(
        name=model_name,
        source=f"runs:/{run_id}/promotion_manifest.json",
        run_id=run_id,
        tags={"image_tag": image_tag, "promoted_at": timestamp},
    )
    _log(f"  Created model version v{version.version}  (run_id={run_id[:8]})")

    # Wait for READY status (Azure ML registers async)
    deadline = time.time() + 60
    while time.time() < deadline:
        v = client.get_model_version(model_name, version.version)
        if v.status == "READY":
            break
        time.sleep(3)
    else:
        _fail(f"Model version v{version.version} did not reach READY within 60s")

    # Promote to Production — archive_existing_versions handles the old Production
    client.transition_model_version_stage(
        name=model_name,
        version=version.version,
        stage="Production",
        archive_existing_versions=True,
    )
    _log(f"  PASS  v{version.version} is now Production for '{model_name}'")
    _log(f"  To rollback: python scripts/rollback.py --scope mlflow --model {model_name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register and promote a Kira model version to Production in MLflow."
    )
    parser.add_argument("--model", default="kira",
                        help="MLflow registered model name (default: kira)")
    parser.add_argument("--image-tag", required=True,
                        help="Docker image tag / git SHA being promoted")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without making changes")
    args = parser.parse_args()

    _log("=" * 60)
    _log(f"MLflow Promote  |  model: {args.model}  |  image: {args.image_tag}")
    _log(f"Dry run: {args.dry_run}")
    _log("=" * 60)

    promote(args.model, args.image_tag, args.dry_run)

    _log("\n" + "=" * 60)
    _log("PASS  Promotion complete")
    _log("=" * 60)


if __name__ == "__main__":
    main()
