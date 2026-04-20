#!/usr/bin/env python3
"""
run_training_sequence.py — Sequential GRPO QLoRA training: Harvey → Kira → Admin.

Unattended-run design:
  • preflight_checks before any downloads
  • rolling log file + stdout/stderr tee
  • run_state.json + heartbeat.txt (OneDrive-syncable)
  • TRL checkpoint resume on restart
  • per-model retry wrapper (OOM shrinks NUM_GENERATIONS, network waits)
  • .training_complete sentinel = robust skip-if-done
  • Windows toast / webhook / email notifications on each model completion
  • graceful SIGINT/SIGTERM: current trainer saves before exit

Adapters saved to:
  outputs/harvey_adapter/
  outputs/kira_adapter/
  outputs/admin_adapter/
"""

import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import torch

from train_shared import (
    HF_MODEL_ID,
    OUTPUT_ROOT,
    MAX_STEPS,
    NUM_GENERATIONS,
    HARVEY_TRAIN_N,
    KIRA_TRAIN_N,
    ADMIN_TRAIN_N,
    get_grpo_config,
    get_lora_config,
    load_base_model,
    load_tokenizer,
    load_harvey_dataset,
    load_kira_dataset,
    load_admin_dataset,
    harvey_reward_fn,
    kira_reward_fn,
    admin_reward_fn,
    evaluate_model,
    # operational helpers
    preflight_checks,
    setup_logging,
    free_vram,
    write_heartbeat,
    update_state,
    notify,
    STATE_PATH,
    LOG_PATH,
)

from trl import GRPOTrainer
from transformers import TrainerCallback

# ── Output directories ────────────────────────────────────────────────────────

HARVEY_OUT = OUTPUT_ROOT / "harvey_adapter"
KIRA_OUT   = OUTPUT_ROOT / "kira_adapter"
ADMIN_OUT  = OUTPUT_ROOT / "admin_adapter"

REPORT_PATH = OUTPUT_ROOT / "TRAINING_REPORT.md"

# ── Shutdown flag (set by signal handler) ─────────────────────────────────────

_shutdown = {"requested": False}


def _install_signal_handlers():
    def handler(signum, frame):
        _shutdown["requested"] = True
        print(f"\n[SIGNAL] Received signal {signum}; will save checkpoint and exit after current step.")
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except Exception:
            pass  # some platforms disallow (e.g. SIGTERM on Windows is limited)


# ── Heartbeat + graceful-exit callback ────────────────────────────────────────

class HeartbeatCallback(TrainerCallback):
    """Writes heartbeat.txt every few steps and requests shutdown on SIGINT."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.last_reward_mean = 0.0
        self.last_reward_std = 0.0

    def on_log(self, args, state, control, logs=None, **kwargs):
        logs = logs or {}
        if "reward" in logs:
            self.last_reward_mean = float(logs.get("reward", 0.0))
        if "reward_std" in logs:
            self.last_reward_std = float(logs.get("reward_std", 0.0))
        if state.global_step % 10 == 0 or state.global_step == 1:
            write_heartbeat(
                self.model_name, state.global_step,
                self.last_reward_mean, self.last_reward_std,
            )
            update_state(
                self.model_name,
                status="training",
                step=state.global_step,
                reward_mean=self.last_reward_mean,
                reward_std=self.last_reward_std,
            )

    def on_step_end(self, args, state, control, **kwargs):
        if _shutdown["requested"]:
            control.should_save = True
            control.should_training_stop = True
        return control


# ── Per-model training function ───────────────────────────────────────────────

def _train_attempt(
    name: str,
    dataset,
    reward_fn,
    output_dir: Path,
    tokenizer,
    num_generations: int,
) -> dict:
    """Single attempt. Raises on failure so the caller can decide retry strategy."""
    print(f"\n{'#'*60}")
    print(f"  TRAINING: {name.upper()}  (num_generations={num_generations})")
    print(f"  Examples: {len(dataset):,}")
    print(f"  Output:   {output_dir}")
    print(f"{'#'*60}\n")

    output_dir.mkdir(parents=True, exist_ok=True)
    update_state(name, status="starting", num_generations=num_generations,
                 started_at=datetime.now().isoformat(timespec="seconds"))
    t0 = time.time()

    model = load_base_model(HF_MODEL_ID)
    print(f"  Model loaded in {time.time()-t0:.0f}s. "
          f"VRAM used: {torch.cuda.memory_allocated()/1e9:.1f} GB\n")

    config = get_grpo_config(output_dir, num_generations=num_generations)

    trainer = GRPOTrainer(
        model=model,
        args=config,
        train_dataset=dataset,
        reward_funcs=reward_fn,
        peft_config=get_lora_config(),
        processing_class=tokenizer,
    )
    trainer.add_callback(HeartbeatCallback(name))

    # Resume from latest checkpoint if one exists in output_dir.
    has_checkpoint = any(output_dir.glob("checkpoint-*"))
    print(f"  Starting GRPO training ({config.max_steps} steps, "
          f"resume={has_checkpoint})...\n")
    trainer.train(resume_from_checkpoint=has_checkpoint)

    # If shutdown was requested mid-step, save & bail without eval.
    if _shutdown["requested"]:
        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))
        update_state(name, status="interrupted")
        raise KeyboardInterrupt("graceful shutdown")

    print(f"\n  Saving adapter to {output_dir} ...")
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    elapsed = time.time() - t0
    print(f"  Training finished in {elapsed/60:.1f} min")

    # Evaluate
    print(f"\n  Evaluating {name} on test split...")
    metrics = evaluate_model(
        model=trainer.model,
        tokenizer=tokenizer,
        model_name=name,
        dataset_split="test",
        n_eval=200,
        n_samples_to_print=5,
    ) or {}
    metrics["elapsed_min"] = round(elapsed / 60, 1)

    # Free GPU memory before the next model loads
    del trainer
    del model
    free_vram()
    print(f"  GPU memory freed. Ready for next model.\n")

    # Mark complete only after save + eval both succeed
    (output_dir / ".training_complete").write_text(
        datetime.now().isoformat(timespec="seconds"), encoding="utf-8"
    )
    update_state(name, status="complete", metrics=metrics,
                 finished_at=datetime.now().isoformat(timespec="seconds"))
    return metrics


def train_one_with_retries(name, dataset, reward_fn, output_dir, tokenizer) -> dict:
    """Wrap a single model's training with OOM / transient-error retries."""
    num_gen = NUM_GENERATIONS
    for attempt in range(3):
        try:
            return _train_attempt(name, dataset, reward_fn, output_dir, tokenizer, num_gen)
        except KeyboardInterrupt:
            raise
        except torch.cuda.OutOfMemoryError:
            free_vram()
            new_gen = max(2, num_gen - 1)
            print(f"\n[{name.upper()}] CUDA OOM on attempt {attempt+1}. "
                  f"Reducing num_generations {num_gen} → {new_gen} and retrying.")
            update_state(name, status="retrying_oom", attempt=attempt + 1,
                         num_generations=new_gen)
            num_gen = new_gen
            time.sleep(5)
        except (ConnectionError, OSError) as e:
            print(f"\n[{name.upper()}] Transient I/O error ({e}); sleeping 60s and retrying.")
            update_state(name, status="retrying_io", attempt=attempt + 1, error=str(e))
            free_vram()
            time.sleep(60)
        except Exception:
            traceback.print_exc()
            update_state(name, status="failed", error=traceback.format_exc(limit=5))
            notify(f"Veridict: {name} FAILED",
                   f"Non-transient error during {name} training. See training_run.log.")
            return {"error": True}

    update_state(name, status="failed_after_retries")
    notify(f"Veridict: {name} FAILED",
           f"{name} exhausted 3 retry attempts. See training_run.log.")
    return {"error": True}


# ── Report ────────────────────────────────────────────────────────────────────

def write_report(all_metrics: dict, wall_clock_min: float):
    lines = []
    lines.append(f"# Veridict Training Report")
    lines.append(f"")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Base model: `{HF_MODEL_ID}`")
    lines.append(f"Total wall-clock: {wall_clock_min:.1f} min")
    lines.append(f"")
    lines.append(f"## Metrics")
    lines.append(f"")
    lines.append(f"| Model | Status | Valid JSON | Issue Type Acc | Severity Acc | Golden Issue Acc | Elapsed (min) |")
    lines.append(f"|-------|--------|-----------:|---------------:|-------------:|-----------------:|--------------:|")
    for name in ("harvey", "kira", "admin"):
        m = all_metrics.get(name, {})
        if m.get("skipped"):
            status = "SKIPPED"
        elif m.get("error"):
            status = "ERROR"
        else:
            status = "OK"
        vj  = f"{m.get('valid_json_pct', 0):.1%}" if "valid_json_pct" in m else "—"
        it  = f"{m.get('issue_type_acc', 0):.1%}" if "issue_type_acc" in m else "—"
        sv  = f"{m.get('severity_acc',   0):.1%}" if "severity_acc"   in m else "—"
        gi  = f"{m.get('golden_issue_type_acc', 0):.1%}" if "golden_issue_type_acc" in m else "—"
        el  = f"{m.get('elapsed_min', 0)}" if "elapsed_min" in m else "—"
        lines.append(f"| {name} | {status} | {vj} | {it} | {sv} | {gi} | {el} |")

    lines.append(f"")
    lines.append(f"## Adapter checkpoints")
    lines.append(f"")
    for out in (HARVEY_OUT, KIRA_OUT, ADMIN_OUT):
        exists = (out / ".training_complete").exists()
        mark = "[x]" if exists else "[ ]"
        lines.append(f"- {mark} `{out}`")

    lines.append(f"")
    lines.append(f"## Files")
    lines.append(f"")
    lines.append(f"- Run state: `{STATE_PATH}`")
    lines.append(f"- Full log: `{LOG_PATH}`")
    lines.append(f"")
    lines.append(f"## Next step")
    lines.append(f"")
    lines.append(f"Wire the adapters into `app/backend/agents/reviewer.py` and `app/backend/agents/admin.py`.")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")


# ── Main sequence ─────────────────────────────────────────────────────────────

def main():
    setup_logging(LOG_PATH)
    _install_signal_handlers()

    print("=" * 60)
    print("VERIDICT — SEQUENTIAL GRPO QLORA TRAINING")
    print(f"Base model: {HF_MODEL_ID}")
    print(f"MAX_STEPS:  {MAX_STEPS}")
    print("=" * 60)

    # Preflight
    print("\nRunning preflight checks...")
    problems = preflight_checks()
    if problems:
        print("\n!!! PREFLIGHT FAILED !!!")
        for p in problems:
            print(f"  - {p}")
        notify("Veridict: preflight failed",
               "\n".join(problems[:5]) + ("\n..." if len(problems) > 5 else ""))
        sys.exit(2)
    print("Preflight OK.\n")

    vram = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"GPU: {torch.cuda.get_device_name(0)}  ({vram:.1f} GB VRAM)")

    print(f"\nLoading tokenizer once (shared across all three models)...")
    tokenizer = load_tokenizer(HF_MODEL_ID)
    print(f"Tokenizer loaded. Vocab size: {tokenizer.vocab_size}\n")

    print("Loading and preparing all three datasets...\n")
    harvey_ds = load_harvey_dataset(HARVEY_TRAIN_N)
    kira_ds   = load_kira_dataset(KIRA_TRAIN_N)
    admin_ds  = load_admin_dataset(ADMIN_TRAIN_N)

    all_metrics: dict = {}
    sequence = [
        ("harvey", harvey_ds, harvey_reward_fn, HARVEY_OUT),
        ("kira",   kira_ds,   kira_reward_fn,   KIRA_OUT),
        ("admin",  admin_ds,  admin_reward_fn,  ADMIN_OUT),
    ]

    t_start = time.time()
    notify("Veridict: training started",
           f"Base={HF_MODEL_ID}\nSteps/model={MAX_STEPS}\nSequence=harvey → kira → admin")

    for name, dataset, reward_fn, output_dir in sequence:
        if _shutdown["requested"]:
            print(f"\nShutdown requested; skipping remaining models.")
            break

        sentinel = output_dir / ".training_complete"
        if sentinel.exists():
            print(f"\n[{name.upper()}] .training_complete exists at {output_dir}. Skipping.")
            print(f"  Delete {sentinel} to force a retrain.")
            all_metrics[name] = {"skipped": True}
            update_state(name, status="skipped")
            continue

        metrics = train_one_with_retries(name, dataset, reward_fn, output_dir, tokenizer)
        all_metrics[name] = metrics

        if metrics.get("error"):
            print(f"\n[{name.upper()}] Marked failed; continuing to next model.")
        else:
            notify(f"Veridict: {name} complete",
                   f"valid_json={metrics.get('valid_json_pct', 0):.1%}  "
                   f"issue_type={metrics.get('issue_type_acc', 0):.1%}  "
                   f"severity={metrics.get('severity_acc', 0):.1%}")

    wall_clock_min = (time.time() - t_start) / 60

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("TRAINING SEQUENCE COMPLETE — SUMMARY")
    print(f"{'='*60}")
    print(f"{'Model':<10} {'JSON Valid':>12} {'Issue Type':>12} {'Severity':>12} {'Status':>10}")
    print(f"{'-'*10} {'-'*12} {'-'*12} {'-'*12} {'-'*10}")
    for name, m in all_metrics.items():
        if m.get("skipped"):
            status = "SKIPPED"
            print(f"{name.upper():<10} {'-':>12} {'-':>12} {'-':>12} {status:>10}")
        elif m.get("error"):
            status = "ERROR"
            print(f"{name.upper():<10} {'-':>12} {'-':>12} {'-':>12} {status:>10}")
        else:
            jv  = f"{m.get('valid_json_pct', 0):.1%}"
            ita = f"{m.get('issue_type_acc', 0):.1%}"
            sa  = f"{m.get('severity_acc',   0):.1%}"
            print(f"{name.upper():<10} {jv:>12} {ita:>12} {sa:>12} {'OK':>10}")

    write_report(all_metrics, wall_clock_min)

    summary_lines = []
    for n, m in all_metrics.items():
        if m.get("skipped"):
            summary_lines.append(f"{n}: SKIPPED")
        elif m.get("error"):
            summary_lines.append(f"{n}: ERROR")
        else:
            summary_lines.append(f"{n}: json={m.get('valid_json_pct', 0):.0%} "
                                 f"type={m.get('issue_type_acc', 0):.0%} "
                                 f"sev={m.get('severity_acc', 0):.0%}")
    notify("Veridict: ALL TRAINING COMPLETE",
           f"Wall clock: {wall_clock_min:.0f} min\n" + "\n".join(summary_lines))

    print(f"\nTotal wall-clock: {wall_clock_min:.1f} min")
    print(f"Report: {REPORT_PATH}")
    print()


if __name__ == "__main__":
    main()
