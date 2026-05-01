"""
Veridict Rollback Script

Rolls back one or all deployment layers after a bad push or failed smoke test.

Scopes:
  api       — kubectl rollout undo verdict-api (rolling update, instant)
  worker    — kubectl rollout undo verdict-worker (rolling update, instant)
  frontend  — kubectl rollout undo verdict-frontend (rolling update, instant)
  vllm      — blue-green switch back to the inactive slot (the old good version)
  mlflow    — restore the most recently archived Production model version
  all       — all of the above (default)

Usage:
  python scripts/rollback.py                        # roll back everything
  python scripts/rollback.py --scope api worker     # partial rollback
  python scripts/rollback.py --scope vllm           # just swap vLLM slot
  python scripts/rollback.py --scope mlflow --model kira
  python scripts/rollback.py --dry-run              # print plan only

Environment:
  MLFLOW_TRACKING_URI   required only for --scope mlflow
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

NAMESPACE = "verdict"
VALID_SCOPES = ("api", "worker", "frontend", "vllm", "mlflow")
ROLLING_DEPLOYMENTS = {
    "api":      "verdict-api",
    "worker":   "verdict-worker",
    "frontend": "verdict-frontend",
}
VLLM_SERVICE   = "verdict-vllm-kira"
SLOTS          = ("blue", "green")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _fail(reason: str) -> None:
    _log(f"\nFAIL  {reason}")
    sys.exit(1)


def _run(cmd: list[str], capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if capture else ""
        _fail(f"Command failed: {' '.join(cmd)}\n{stderr}")
    return result


def _kubectl(*args: str, capture: bool = True, check: bool = True) -> str:
    result = _run(["kubectl", *args, "-n", NAMESPACE], capture=capture, check=check)
    return result.stdout.strip() if capture else ""


# ---------------------------------------------------------------------------
# Rolling update rollback (api / worker / frontend)
# ---------------------------------------------------------------------------

def rollback_rolling(scope: str, dry_run: bool) -> bool:
    deploy = ROLLING_DEPLOYMENTS[scope]
    _log(f"\n[ {scope.upper()} ] kubectl rollout undo deployment/{deploy}")

    # Show what revision we're rolling back to
    history = _kubectl(
        "rollout", "history", f"deployment/{deploy}",
        capture=True, check=False,
    )
    if history:
        lines = [l for l in history.splitlines() if l.strip()]
        _log(f"  Revision history (last 2 shown):")
        for line in lines[-3:]:
            _log(f"    {line}")

    if dry_run:
        _log(f"  [DRY RUN] Would run: kubectl rollout undo deployment/{deploy} -n {NAMESPACE}")
        return True

    _kubectl("rollout", "undo", f"deployment/{deploy}")
    _log(f"  Waiting for {deploy} to stabilize ...")
    result = _run(
        ["kubectl", "rollout", "status", f"deployment/{deploy}",
         "-n", NAMESPACE, "--timeout=3m"],
        capture=True, check=False,
    )
    ok = result.returncode == 0
    _log(f"  {'PASS' if ok else 'FAIL'}  {deploy} rollout {'complete' if ok else 'did not stabilize in 3m'}")
    return ok


# ---------------------------------------------------------------------------
# vLLM blue-green rollback (swap back to the inactive slot)
# ---------------------------------------------------------------------------

def _active_vllm_slot() -> str:
    raw = _kubectl(
        "get", "service", VLLM_SERVICE,
        "-o", "jsonpath={.spec.selector.slot}",
        capture=True, check=False,
    )
    return raw if raw in SLOTS else "blue"


def rollback_vllm(dry_run: bool) -> bool:
    active = _active_vllm_slot()
    previous = "green" if active == "blue" else "blue"
    _log(f"\n[ VLLM ] Switching back from slot={active} to slot={previous}")

    if dry_run:
        _log(f"  [DRY RUN] Would call: blue_green_switch.py --to {previous}")
        return True

    # Delegate to blue_green_switch.py — it handles scale-up, readiness wait, and selector patch
    script = str(__import__("pathlib").Path(__file__).parent / "blue_green_switch.py")
    result = _run(
        [sys.executable, script, "--to", previous],
        capture=False, check=False,
    )
    ok = result.returncode == 0
    _log(f"  {'PASS' if ok else 'FAIL'}  vLLM rollback {'complete' if ok else 'failed — check logs above'}")
    return ok


# ---------------------------------------------------------------------------
# MLflow model rollback
# ---------------------------------------------------------------------------

def rollback_mlflow(model_name: str, dry_run: bool) -> bool:
    _log(f"\n[ MLFLOW ] Restoring previous Production version of '{model_name}'")

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()
    if not tracking_uri:
        _log("  WARN  MLFLOW_TRACKING_URI not set — skipping MLflow rollback")
        return True

    try:
        import mlflow
        mlflow.set_tracking_uri(tracking_uri)
        client = mlflow.tracking.MlflowClient()
    except ImportError:
        _log("  WARN  mlflow not installed — skipping MLflow rollback")
        return True

    # Find the current Production version
    current_prod = client.get_latest_versions(model_name, stages=["Production"])
    if not current_prod:
        _log("  WARN  No Production version found — nothing to roll back")
        return True

    current = sorted(current_prod, key=lambda v: int(v.version), reverse=True)[0]
    _log(f"  Current Production: v{current.version}")

    # Find the most recently archived version (the one we demoted during the last promotion)
    archived = client.get_latest_versions(model_name, stages=["Archived"])
    if not archived:
        _log("  WARN  No Archived versions found — cannot determine previous Production")
        return False

    # Sort by version number descending; the highest archived version is the previous Production
    previous_prod = sorted(archived, key=lambda v: int(v.version), reverse=True)[0]
    _log(f"  Restoring:          v{previous_prod.version}")

    if dry_run:
        _log(f"  [DRY RUN] Would: Production v{current.version} → Archived")
        _log(f"  [DRY RUN] Would: Archived  v{previous_prod.version} → Production")
        return True

    client.transition_model_version_stage(
        name=model_name, version=current.version,
        stage="Archived", archive_existing_versions=False,
    )
    client.transition_model_version_stage(
        name=model_name, version=previous_prod.version,
        stage="Production", archive_existing_versions=False,
    )
    client.set_model_version_tag(model_name, previous_prod.version, "rolled_back_by", "rollback.py")

    _log(f"  PASS  v{previous_prod.version} is now Production")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Roll back one or all Veridict deployment layers.")
    parser.add_argument(
        "--scope", nargs="+", choices=list(VALID_SCOPES) + ["all"],
        default=["all"],
        help="Which layers to roll back (default: all)",
    )
    parser.add_argument("--model", default="kira",
                        help="MLflow registered model name (used for --scope mlflow, default: kira)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without making changes")
    args = parser.parse_args()

    scopes: set[str] = set(VALID_SCOPES) if "all" in args.scope else set(args.scope)

    _log("=" * 60)
    _log(f"Veridict Rollback  |  scopes: {', '.join(sorted(scopes))}")
    _log(f"Dry run: {args.dry_run}")
    _log("=" * 60)

    results: dict[str, bool] = {}

    # Rolling deployments first (fast, no GPU wait)
    for scope in ("api", "worker", "frontend"):
        if scope in scopes:
            results[scope] = rollback_rolling(scope, args.dry_run)

    # vLLM blue-green swap (slow — GPU warmup)
    if "vllm" in scopes:
        results["vllm"] = rollback_vllm(args.dry_run)

    # MLflow stage transition
    if "mlflow" in scopes:
        results["mlflow"] = rollback_mlflow(args.model, args.dry_run)

    # Summary
    _log("\n" + "=" * 60)
    all_ok = all(results.values())
    for scope, ok in results.items():
        _log(f"  {'PASS' if ok else 'FAIL'}  {scope}")
    _log("=" * 60)

    if all_ok:
        _log("PASS  Rollback complete")
    else:
        _log("FAIL  One or more rollbacks failed — check output above")
        sys.exit(1)


if __name__ == "__main__":
    main()
