#!/usr/bin/env python3
"""
launch.py — One-command RunPod training orchestrator for Kira (Gemma 4 26B).

Steps:
  1. Download labeled data from Google Drive → data/kira/labeled/
  2. Export to fine-tuning format → data/kira/ft/
  3. Baseline evaluation (current model, saved to output/eval_before.json)
  4. SSH into RunPod, upload data + training scripts
  5. Install deps and run training (stream logs live)
  6. Download adapter weights → output/kira_adapter/
  7. After-training evaluation (new endpoint, saved to output/eval_after.json)
  8. Write final status to output/training_status.json

Environment variables (set in .env or export before running):
  RUNPOD_HOST          — e.g. ssh.runpod.io or user@host
  RUNPOD_SSH_KEY_PATH  — path to your SSH private key
  RUNPOD_PORT          — SSH port (default: 22)
  RUNPOD_USER          — SSH username (default: root)

  BASELINE_ENDPOINT    — endpoint for before-eval (default: http://localhost:11434/v1)
  BASELINE_MODEL       — model name for before-eval (default: llama3.2:latest)

  HF_TOKEN             — HuggingFace token (required on RunPod to pull gated Gemma 4)
  GDRIVE_FOLDER_ID     — override the default Drive folder ID

Usage:
  python -m scripts.fine_tune.launch
  python -m scripts.fine_tune.launch --skip-gdrive   # skip download if data already present
  python -m scripts.fine_tune.launch --skip-eval     # skip before/after eval (faster)
  python -m scripts.fine_tune.launch --dry-run       # print plan, no SSH calls
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.llmops_mlflow import dataset_version, log_artifact, log_dict, log_metrics, log_params, start_run

OUTPUT_DIR = ROOT / "scripts" / "fine_tune" / "output"
STATUS_FILE = OUTPUT_DIR / "training_status.json"
LOG_FILE = OUTPUT_DIR / "training_log.txt"
ADAPTER_DIR = OUTPUT_DIR / "kira_adapter"

REMOTE_WORK_DIR = "/root/verdict_train"

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _env(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if not val:
        return default
    return val


def _write_status(status: str, **kwargs) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if STATUS_FILE.exists():
        try:
            existing = json.loads(STATUS_FILE.read_text())
        except Exception:
            pass
    existing.update({"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **kwargs})
    STATUS_FILE.write_text(json.dumps(existing, indent=2))


def _append_log(line: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Step 1: Google Drive sync ─────────────────────────────────────────────────

def step_gdrive_sync() -> None:
    log.info("=== Step 1: Syncing data from Google Drive ===")
    _append_log("[launch] Downloading labeled data from Google Drive...")
    from scripts.distill.gdrive_sync import sync
    folder_id = _env("GDRIVE_FOLDER_ID", "1FWhdw0eM2a3iyc_c3hpCCiWnFmBHvfgL")
    n = sync(folder_id)
    _append_log(f"[launch] Downloaded {n} JSONL file(s) from Drive.")
    log.info("Drive sync complete: %d file(s)", n)


# ── Step 2: Export to fine-tuning format ─────────────────────────────────────

def step_export() -> None:
    log.info("=== Step 2: Exporting to fine-tuning format ===")
    _append_log("[launch] Exporting labeled data to fine-tuning format...")
    from scripts.distill.export_kira import main as export_main
    import sys as _sys
    old_argv = _sys.argv
    _sys.argv = ["export_kira"]
    try:
        export_main()
    finally:
        _sys.argv = old_argv
    _append_log("[launch] Export complete.")


# ── Step 3: Baseline evaluation ───────────────────────────────────────────────

def step_eval_before() -> None:
    log.info("=== Step 3: Baseline evaluation ===")
    _append_log("[launch] Running baseline evaluation...")
    from scripts.fine_tune.evaluate import log_eval_to_mlflow, run_eval
    endpoint = _env("BASELINE_ENDPOINT", "http://localhost:11434/v1")
    model = _env("BASELINE_MODEL", "llama3.2:latest")
    results = run_eval(endpoint, model)
    out = OUTPUT_DIR / "eval_before.json"
    out.write_text(json.dumps(results, indent=2))
    log_eval_to_mlflow("before", endpoint, model, 100, results, out)
    _append_log(f"[launch] Baseline eval: json_valid={results.get('json_validity_rate')} schema={results.get('schema_compliance_rate')}")
    log.info("Baseline eval saved to %s", out)


# ── Steps 4–6: RunPod SSH training ───────────────────────────────────────────

def _build_ssh_config() -> dict:
    host = _env("RUNPOD_HOST")
    if not host:
        sys.exit("RUNPOD_HOST not set. Add it to .env or export it.")
    return {
        "host": host,
        "port": int(_env("RUNPOD_PORT", "22")),
        "user": _env("RUNPOD_USER", "root"),
        "key_path": _env("RUNPOD_SSH_KEY_PATH"),
    }


def _get_ssh_client(cfg: dict):
    try:
        import paramiko
    except ImportError:
        sys.exit("paramiko not installed. Run: pip install paramiko")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs: dict = {
        "hostname": cfg["host"],
        "port": cfg["port"],
        "username": cfg["user"],
        "timeout": 30,
    }
    if cfg["key_path"]:
        connect_kwargs["key_filename"] = cfg["key_path"]
    else:
        import getpass
        connect_kwargs["password"] = getpass.getpass(f"SSH password for {cfg['user']}@{cfg['host']}: ")
    client.connect(**connect_kwargs)
    return client


def _run_remote(client, cmd: str, stream: bool = True) -> int:
    """Run a command on the remote host, streaming output to log file and stdout."""
    log.info("Remote: %s", cmd)
    _append_log(f"[remote] $ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, get_pty=True)
    exit_code = 0
    for line in stdout:
        line = line.rstrip("\n")
        _append_log(line)
        if stream:
            print(line, flush=True)
    exit_code = stdout.channel.recv_exit_status()
    for line in stderr:
        line = line.rstrip("\n")
        _append_log(f"[stderr] {line}")
    return exit_code


def _upload_files(client, local_paths: list[Path], remote_dir: str) -> None:
    try:
        import paramiko
    except ImportError:
        sys.exit("paramiko not installed.")
    sftp = client.open_sftp()
    try:
        try:
            sftp.mkdir(remote_dir)
        except IOError:
            pass
        for local_path in local_paths:
            remote_path = f"{remote_dir}/{local_path.name}"
            log.info("Uploading %s → %s", local_path, remote_path)
            _append_log(f"[launch] Uploading {local_path.name}...")
            sftp.put(str(local_path), remote_path)
    finally:
        sftp.close()


def _download_dir(client, remote_dir: str, local_dir: Path) -> None:
    try:
        import paramiko
    except ImportError:
        sys.exit("paramiko not installed.")
    sftp = client.open_sftp()
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        for item in sftp.listdir_attr(remote_dir):
            remote_path = f"{remote_dir}/{item.filename}"
            local_path = local_dir / item.filename
            import stat
            if stat.S_ISDIR(item.st_mode):
                _download_dir(client, remote_path, local_path)
            else:
                log.info("Downloading %s", item.filename)
                sftp.get(remote_path, str(local_path))
    finally:
        sftp.close()


def _build_remote_train_script() -> str:
    """Generate the remote bootstrap + training shell script."""
    hf_token = _env("HF_TOKEN")
    return f"""#!/bin/bash
set -e
echo "=== Kira fine-tune bootstrap ==="
pip install -q transformers trl peft accelerate bitsandbytes datasets torch gdown 2>&1 | tail -5
pip install -q huggingface_hub 2>&1 | tail -2
{"export HF_TOKEN=" + hf_token if hf_token else "# HF_TOKEN not set — model must be pre-cached"}
echo "=== Starting Kira QLoRA training ==="
python train_gemma_kira.py
echo "=== Training complete ==="
"""


def step_runpod_train(dry_run: bool = False) -> None:
    log.info("=== Steps 4–6: RunPod training ===")
    _append_log("[launch] Connecting to RunPod...")

    cfg = _build_ssh_config()

    if dry_run:
        log.info("[dry-run] Would SSH to %s@%s:%d", cfg["user"], cfg["host"], cfg["port"])
        _append_log("[launch] [dry-run] Skipping SSH.")
        return

    # Build self-contained training script to upload
    train_ft_dir = ROOT / "data" / "kira" / "ft"
    train_jsonl = train_ft_dir / "train.jsonl"
    val_jsonl = train_ft_dir / "val.jsonl"

    if not train_jsonl.exists():
        sys.exit(f"Training data not found at {train_jsonl}. Run export step first.")

    # Write a self-contained training script referencing uploaded data paths
    remote_train_py = OUTPUT_DIR / "train_gemma_kira.py"
    _write_remote_train_script(remote_train_py)

    bootstrap_sh = OUTPUT_DIR / "bootstrap.sh"
    bootstrap_sh.write_text(_build_remote_train_script())

    upload_files = [train_jsonl, val_jsonl, remote_train_py, bootstrap_sh]
    existing_uploads = [f for f in upload_files if f.exists()]

    client = _get_ssh_client(cfg)
    try:
        _append_log(f"[launch] Connected to {cfg['host']}.")
        _write_status("running", started_at=datetime.now(timezone.utc).isoformat())

        # Upload data and scripts
        _run_remote(client, f"mkdir -p {REMOTE_WORK_DIR}")
        _upload_files(client, existing_uploads, REMOTE_WORK_DIR)

        # Run bootstrap + training
        rc = _run_remote(client, f"cd {REMOTE_WORK_DIR} && bash bootstrap.sh 2>&1")
        if rc != 0:
            _write_status("failed", error=f"Training exited with code {rc}")
            sys.exit(f"Training failed (exit code {rc})")

        # Download adapter weights
        log.info("=== Step 6: Downloading adapter weights ===")
        _append_log("[launch] Downloading adapter weights...")
        ADAPTER_DIR.mkdir(parents=True, exist_ok=True)
        _download_dir(client, f"{REMOTE_WORK_DIR}/kira_adapter", ADAPTER_DIR)
        _append_log(f"[launch] Adapter saved to {ADAPTER_DIR}")

    finally:
        client.close()

    # Step 6b: Upload adapter to the vllm-kira K8s PVC and trigger a rolling restart.
    # Requires kubectl configured with AKS credentials in the current shell.
    # Skip if KUBECONFIG is not set or kubectl is not available.
    step_upload_adapter_to_k8s()


def step_upload_adapter_to_k8s() -> None:
    """Copy LoRA adapter weights into the vllm-kira pod's PVC and restart the deployment."""
    log.info("=== Step 6b: Uploading adapter to K8s vllm-kira pod ===")
    _append_log("[launch] Uploading LoRA adapter to Kubernetes...")

    if not ADAPTER_DIR.exists() or not any(ADAPTER_DIR.iterdir()):
        log.warning("Adapter directory is empty — skipping K8s upload.")
        _append_log("[launch] Adapter directory empty, skipping K8s upload.")
        return

    # Find the vllm-kira pod name
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", "verdict",
         "-l", "app=verdict-vllm-kira",
         "--field-selector=status.phase=Running",
         "-o", "jsonpath={.items[0].metadata.name}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        log.warning("Could not find running vllm-kira pod — skipping K8s upload.")
        _append_log("[launch] vllm-kira pod not found, skipping upload.")
        return

    pod_name = result.stdout.strip()
    log.info("Copying adapter to pod %s:/mnt/kira-adapter/", pod_name)
    _append_log(f"[launch] Copying to pod {pod_name}...")

    cp_result = subprocess.run(
        ["kubectl", "cp", str(ADAPTER_DIR) + "/.",
         f"verdict/{pod_name}:/mnt/kira-adapter/"],
        capture_output=True, text=True,
    )
    if cp_result.returncode != 0:
        log.error("kubectl cp failed: %s", cp_result.stderr)
        _append_log(f"[launch] kubectl cp failed: {cp_result.stderr}")
        return

    _append_log("[launch] Adapter uploaded. Triggering rolling restart of verdict-vllm-kira...")
    log.info("Triggering rolling restart of verdict-vllm-kira...")
    subprocess.run(
        ["kubectl", "rollout", "restart", "deployment/verdict-vllm-kira", "-n", "verdict"],
        check=True,
    )
    _append_log("[launch] Rolling restart triggered. Monitor with: kubectl rollout status deployment/verdict-vllm-kira -n verdict")


def _write_remote_train_script(out_path: Path) -> None:
    """Write a trimmed training script that runs on RunPod with uploaded data."""
    script = '''\
#!/usr/bin/env python3
"""Auto-generated Kira fine-tune script for RunPod."""
import json, sys
from pathlib import Path
from datasets import Dataset

ROOT = Path(__file__).parent

def load_jsonl(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTConfig, SFTTrainer

MODEL_ID = "google/gemma-4-26B-A4B-it"
LORA_RANK = 16
LORA_ALPHA = 32
TRAIN_EPOCHS = 3
BATCH_SIZE = 1
GRAD_ACCUM = 8
LR = 2e-4
MAX_SEQ = 2048

print(f"Loading tokenizer from {MODEL_ID}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.pad_token_id = tokenizer.eos_token_id

print("Loading model in 4-bit...")
bnb_cfg = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, quantization_config=bnb_cfg, device_map="auto",
    trust_remote_code=True,
)
model.config.use_cache = False

lora_cfg = LoraConfig(
    task_type=TaskType.CAUSAL_LM, r=LORA_RANK, lora_alpha=LORA_ALPHA,
    lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    bias="none",
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

print("Loading datasets...")
train_rows = load_jsonl(ROOT / "train.jsonl")
val_rows = load_jsonl(ROOT / "val.jsonl") if (ROOT / "val.jsonl").exists() else []
train_ds = Dataset.from_list(train_rows)
val_ds = Dataset.from_list(val_rows) if val_rows else None
print(f"  Train: {len(train_rows)}  Val: {len(val_rows)}")

sft_cfg = SFTConfig(
    output_dir="./kira_checkpoints",
    num_train_epochs=TRAIN_EPOCHS,
    per_device_train_batch_size=BATCH_SIZE,
    per_device_eval_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM,
    learning_rate=LR, lr_scheduler_type="cosine", warmup_ratio=0.05,
    bf16=True, logging_steps=50,
    eval_strategy="epoch" if val_ds else "no",
    save_strategy="epoch", save_total_limit=1,
    load_best_model_at_end=bool(val_ds),
    metric_for_best_model="eval_loss" if val_ds else None,
    report_to="none",
    max_seq_length=MAX_SEQ, packing=False,
)

trainer = SFTTrainer(
    model=model, tokenizer=tokenizer, args=sft_cfg,
    train_dataset=train_ds, eval_dataset=val_ds,
)

print("Training...")
trainer.train()

print("Saving adapter to ./kira_adapter/")
trainer.model.save_pretrained("./kira_adapter")
tokenizer.save_pretrained("./kira_adapter")
print("Done.")
'''
    out_path.write_text(script, encoding="utf-8")


# ── Step 7: After evaluation ──────────────────────────────────────────────────

def step_eval_after() -> None:
    log.info("=== Step 7: Post-training evaluation ===")
    after_endpoint = _env("KIRA_MODEL_URL", "")
    after_model = _env("KIRA_MODEL_NAME", "kira-gemma4-26b")
    if not after_endpoint:
        _append_log("[launch] KIRA_MODEL_URL not set — skipping after-eval. Set it once the model is deployed.")
        log.info("KIRA_MODEL_URL not set; skipping after-eval.")
        return
    _append_log(f"[launch] Running after-eval against {after_endpoint}...")
    from scripts.fine_tune.evaluate import log_eval_to_mlflow, run_eval
    results = run_eval(after_endpoint, after_model)
    out = OUTPUT_DIR / "eval_after.json"
    out.write_text(json.dumps(results, indent=2))
    log_eval_to_mlflow("after", after_endpoint, after_model, 100, results, out)
    _append_log(f"[launch] After eval: json_valid={results.get('json_validity_rate')} schema={results.get('schema_compliance_rate')}")
    log.info("After eval saved to %s", out)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-gdrive", action="store_true")
    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("")  # reset log
    _write_status("starting")
    _append_log(f"[launch] Started at {datetime.now(timezone.utc).isoformat()}")

    train_data = ROOT / "data" / "kira" / "ft" / "train.jsonl"
    val_data = ROOT / "data" / "kira" / "ft" / "val.jsonl"
    mlflow_context = start_run(
        "kira-runpod-training-orchestration",
        tags={"llmops.phase": "training_orchestration", "role": "kira"},
    )
    mlflow_context.__enter__()
    log_params(
        {
            "baseline_endpoint": _env("BASELINE_ENDPOINT", "http://localhost:11434/v1"),
            "baseline_model": _env("BASELINE_MODEL", "llama3.2:latest"),
            "kira_model_url": _env("KIRA_MODEL_URL", ""),
            "kira_model_name": _env("KIRA_MODEL_NAME", "kira-gemma4-26b"),
            "hf_adapter_repo": _env("HF_ADAPTER_REPO", ""),
            "train_data_path": str(train_data),
            "val_data_path": str(val_data),
            "data_version": dataset_version([p for p in [train_data, val_data] if p.exists()]),
            "dry_run": args.dry_run,
            "skip_gdrive": args.skip_gdrive,
            "skip_export": args.skip_export,
            "skip_eval": args.skip_eval,
        }
    )

    try:
        if not args.skip_gdrive:
            step_gdrive_sync()

        if not args.skip_export:
            step_export()

        if not args.skip_eval:
            step_eval_before()

        step_runpod_train(dry_run=args.dry_run)

        if not args.skip_eval and not args.dry_run:
            step_eval_after()

        _write_status("completed", finished_at=datetime.now(timezone.utc).isoformat())
        _append_log("[launch] All steps complete.")
        if STATUS_FILE.exists():
            log_dict(json.loads(STATUS_FILE.read_text(encoding="utf-8")), "training/status.json")
        if LOG_FILE.exists():
            log_artifact(LOG_FILE, artifact_path="training")
        log_metrics({"completed": 1.0})
        log.info("Training pipeline complete.")
        mlflow_context.__exit__(None, None, None)

    except SystemExit as exc:
        _write_status("failed", error=str(exc))
        _append_log(f"[launch] Failed: {exc}")
        log_metrics({"failed": 1.0})
        if STATUS_FILE.exists():
            log_artifact(STATUS_FILE, artifact_path="training")
        if LOG_FILE.exists():
            log_artifact(LOG_FILE, artifact_path="training")
        mlflow_context.__exit__(type(exc), exc, exc.__traceback__)
        raise
    except Exception as exc:
        _write_status("failed", error=str(exc))
        _append_log(f"[launch] Unexpected error: {exc}")
        log.exception("Unexpected error")
        log_metrics({"failed": 1.0})
        if STATUS_FILE.exists():
            log_artifact(STATUS_FILE, artifact_path="training")
        if LOG_FILE.exists():
            log_artifact(LOG_FILE, artifact_path="training")
        mlflow_context.__exit__(type(exc), exc, exc.__traceback__)
        sys.exit(1)


if __name__ == "__main__":
    main()
