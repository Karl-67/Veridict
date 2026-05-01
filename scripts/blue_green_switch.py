"""
Blue-Green Switch — vLLM Kira Deployment

Promotes traffic from the current active slot to the other slot with zero downtime.

Steps:
  1. Detect current active slot from Service selector
  2. Scale up the inactive (target) slot — optionally patch image tag first
  3. Wait for target pod to pass readiness (5-10 min for GPU warmup)
  4. Patch Service selector to target slot → traffic switches instantly
  5. Scale down old slot → release GPU

Rollback:
  Run the same script again — it swaps back to whichever slot is not currently active.
  Or use --to blue/green explicitly.

Usage:
  python scripts/blue_green_switch.py                    # auto-detect and switch
  python scripts/blue_green_switch.py --to green         # promote green
  python scripts/blue_green_switch.py --to blue          # rollback to blue
  python scripts/blue_green_switch.py --to green --image verdictacr.azurecr.io/verdict-vllm-kira:abc123
  python scripts/blue_green_switch.py --dry-run          # print plan, no changes

Requirements:
  kubectl configured and pointing at the correct AKS cluster (az aks get-credentials)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

NAMESPACE = "verdict"
SERVICE = "verdict-vllm-kira"
SLOTS = ("blue", "green")
READY_TIMEOUT = 600   # seconds — vLLM takes ~5 min to load 26B model
READY_POLL    = 15    # poll interval


def _log(msg: str) -> None:
    print(msg, flush=True)


def _fail(reason: str) -> None:
    _log(f"\nFAIL  {reason}")
    sys.exit(1)


def _run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip() if capture else ""
        _fail(f"Command failed: {' '.join(cmd)}\n{stderr}")
    return result


def _kubectl(*args: str, capture: bool = True) -> str:
    result = _run(["kubectl", *args, "-n", NAMESPACE], capture=capture)
    return result.stdout.strip() if capture else ""


# ---------------------------------------------------------------------------
# Slot detection
# ---------------------------------------------------------------------------

def _active_slot() -> str:
    """Read current Service selector to find active slot."""
    raw = _kubectl(
        "get", "service", SERVICE,
        "-o", "jsonpath={.spec.selector.slot}",
    )
    if raw not in SLOTS:
        _fail(
            f"Service '{SERVICE}' selector.slot is '{raw}' — expected 'blue' or 'green'.\n"
            "Run: kubectl apply -k k8s/ to restore the service definition."
        )
    return raw


def _inactive_slot(active: str) -> str:
    return "green" if active == "blue" else "blue"


def _deployment(slot: str) -> str:
    return f"verdict-vllm-kira-{slot}"


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------

def _wait_for_ready(slot: str, timeout: int) -> bool:
    """Poll until the target slot deployment has >=1 ready replica or timeout."""
    deploy = _deployment(slot)
    deadline = time.time() + timeout
    _log(f"  Waiting for {deploy} to become ready (timeout: {timeout}s) ...")

    while time.time() < deadline:
        raw = _kubectl(
            "get", "deployment", deploy,
            "-o", "jsonpath={.status.readyReplicas}",
        )
        ready = int(raw) if raw.isdigit() else 0
        if ready >= 1:
            return True
        elapsed = int(time.time() - (deadline - timeout))
        _log(f"  [{elapsed:>4}s] ready replicas: {ready} — waiting ...")
        time.sleep(READY_POLL)

    return False


# ---------------------------------------------------------------------------
# Image patching
# ---------------------------------------------------------------------------

def _patch_image(slot: str, image: str, dry_run: bool) -> None:
    deploy = _deployment(slot)
    _log(f"  Patching image: {deploy} → {image}")
    if not dry_run:
        _kubectl(
            "set", "image",
            f"deployment/{deploy}",
            f"vllm={image}",
        )


# ---------------------------------------------------------------------------
# Scale helpers
# ---------------------------------------------------------------------------

def _scale(slot: str, replicas: int, dry_run: bool) -> None:
    deploy = _deployment(slot)
    _log(f"  Scale {deploy} → {replicas} replica(s)")
    if not dry_run:
        _kubectl("scale", "deployment", deploy, f"--replicas={replicas}")


# ---------------------------------------------------------------------------
# Service switch
# ---------------------------------------------------------------------------

def _switch_service(to_slot: str, dry_run: bool) -> None:
    _log(f"  Patching Service selector: slot={to_slot}")
    if not dry_run:
        patch = json.dumps({"spec": {"selector": {"slot": to_slot}}})
        _kubectl("patch", "service", SERVICE, "--type=merge", f"--patch={patch}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Switch Kira vLLM traffic between blue and green slots.")
    parser.add_argument("--to",      choices=["blue", "green"], default=None,
                        help="Target slot. Default: whichever is not currently active.")
    parser.add_argument("--image",   default=None,
                        help="New container image to deploy into the target slot before switching.")
    parser.add_argument("--timeout", type=int, default=READY_TIMEOUT,
                        help=f"Readiness wait timeout in seconds (default: {READY_TIMEOUT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without making any changes.")
    args = parser.parse_args()

    _log("=" * 60)
    _log(f"Veridict Blue-Green Switch  |  service: {SERVICE}")
    _log(f"Dry run: {args.dry_run}")
    _log("=" * 60)

    # 1. Detect current state
    active = _active_slot()
    target = args.to or _inactive_slot(active)

    if target == active:
        _log(f"\nINFO  '{target}' is already the active slot — nothing to do.")
        sys.exit(0)

    _log(f"\n  Active slot : {active}  (verdict-vllm-kira-{active})")
    _log(f"  Target slot : {target}  (verdict-vllm-kira-{target})")

    if args.dry_run:
        _log("\n[DRY RUN] Would perform:")
        if args.image:
            _log(f"  1. Patch image on {_deployment(target)}: {args.image}")
        _log(f"  {'2' if args.image else '1'}. Scale {_deployment(target)} → 1 replica")
        _log(f"  {'3' if args.image else '2'}. Wait up to {args.timeout}s for readiness")
        _log(f"  {'4' if args.image else '3'}. Patch Service selector → slot={target}")
        _log(f"  {'5' if args.image else '4'}. Scale {_deployment(active)} → 0 replicas")
        _log("\n  Re-run without --dry-run to apply.")
        sys.exit(0)

    # 2. Optionally update image
    if args.image:
        _log(f"\n[ Step 1 ] Patch image on {_deployment(target)}")
        _patch_image(target, args.image, dry_run=False)

    # 3. Scale up target
    step = 2 if args.image else 1
    _log(f"\n[ Step {step} ] Scale up {_deployment(target)}")
    _scale(target, 1, dry_run=False)

    # 4. Wait for readiness
    step += 1
    _log(f"\n[ Step {step} ] Wait for {_deployment(target)} readiness")
    ready = _wait_for_ready(target, args.timeout)
    if not ready:
        _log(f"\nFAIL  {_deployment(target)} did not become ready within {args.timeout}s")
        _log("  Rolling back: scaling target back to 0 ...")
        _scale(target, 0, dry_run=False)
        _fail("Switch aborted — active slot unchanged.")

    _log(f"  PASS  {_deployment(target)} is ready")

    # 5. Switch Service
    step += 1
    _log(f"\n[ Step {step} ] Switch Service traffic → slot={target}")
    _switch_service(target, dry_run=False)
    _log(f"  PASS  Traffic now flowing to {target}")

    # 6. Scale down old slot
    step += 1
    _log(f"\n[ Step {step} ] Scale down {_deployment(active)} (release GPU)")
    _scale(active, 0, dry_run=False)

    # Done
    _log("\n" + "=" * 60)
    _log(f"PASS  Blue-green switch complete: {active} → {target}")
    _log(f"  Active deployment: verdict-vllm-kira-{target}")
    _log(f"  To rollback:  python scripts/blue_green_switch.py --to {active}")
    _log("=" * 60)


if __name__ == "__main__":
    main()
