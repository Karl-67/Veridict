#!/usr/bin/env python3
"""
train_gemma.py — Fine-tune Gemma 4 on the distillation dataset.

Reads:  data/distillation/gemma/train.jsonl
        data/distillation/gemma/val.jsonl
Writes: data/distillation/checkpoints/   (per-epoch checkpoints)
        data/distillation/model/          (final merged model)

Uses LoRA (PEFT) for memory-efficient fine-tuning. All hyperparameters
are in config.py — change GEMMA_MODEL_ID to swap model size.

Requirements (in addition to requirements.txt):
  pip install transformers trl peft accelerate bitsandbytes datasets

Usage:
  python -m scripts.distill.train_gemma
  python -m scripts.distill.train_gemma --epochs 1 --batch 1   # quick test
  python -m scripts.distill.train_gemma --model google/gemma-4-26B-A4B-it
"""

import argparse
import json
import sys
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def check_deps() -> None:
    missing = []
    for pkg in ("transformers", "trl", "peft", "accelerate", "datasets"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        sys.exit(
            f"Missing packages: {', '.join(missing)}\n"
            f"Run: pip install {' '.join(missing)}"
        )


ROLES = ("harvey", "kira", "validator")


def resolve_role_paths(role: str | None, cfg: object) -> tuple:
    """Return (train_file, val_file, output_dir, checkpoints_dir) for the given role."""
    if role == "harvey":
        return (
            cfg.HARVEY_FT_DIR / "train.jsonl",
            cfg.HARVEY_FT_DIR / "val.jsonl",
            cfg.HARVEY_OUTPUT_DIR,
            cfg.HARVEY_CHECKPOINTS,
        )
    elif role == "kira":
        return (
            cfg.KIRA_FT_DIR / "train.jsonl",
            cfg.KIRA_FT_DIR / "val.jsonl",
            cfg.KIRA_OUTPUT_DIR,
            cfg.KIRA_CHECKPOINTS,
        )
    elif role == "validator":
        return (
            cfg.VALIDATOR_FT_DIR / "train.jsonl",
            cfg.VALIDATOR_FT_DIR / "val.jsonl",
            cfg.VALIDATOR_OUTPUT_DIR,
            cfg.VALIDATOR_CHECKPOINTS,
        )
    else:
        # Legacy single-model path
        return (
            cfg.GEMMA_DIR / "train.jsonl",
            cfg.GEMMA_DIR / "val.jsonl",
            cfg.GEMMA_OUTPUT_DIR,
            cfg.GEMMA_CHECKPOINTS,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role",    choices=[*ROLES, "legacy"], default=None,
                        help="Which model to train: harvey | kira | validator | legacy")
    parser.add_argument("--model",   default=None, help="HuggingFace model ID (overrides config)")
    parser.add_argument("--epochs",  type=int, default=None)
    parser.add_argument("--batch",   type=int, default=None)
    parser.add_argument("--lr",      type=float, default=None)
    parser.add_argument("--lora-rank", type=int, default=None)
    parser.add_argument("--no-lora", action="store_true", help="Full fine-tune (needs large VRAM)")
    parser.add_argument("--load-4bit", action="store_true", help="Load model in 4-bit (QLoRA)")
    args = parser.parse_args()

    check_deps()

    from . import config as cfg
    from .config import (
        GRAD_ACCUM_STEPS,
        LEARNING_RATE,
        LORA_ALPHA,
        LORA_RANK,
        MAX_SEQ_LENGTH,
        TRAIN_BATCH_SIZE,
        TRAIN_EPOCHS,
        GEMMA_MODEL_ID,
    )

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, TaskType
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    role       = args.role if args.role != "legacy" else None
    model_id   = args.model  or GEMMA_MODEL_ID
    epochs     = args.epochs or TRAIN_EPOCHS
    batch_size = args.batch  or TRAIN_BATCH_SIZE
    lr         = args.lr     or LEARNING_RATE
    lora_rank  = args.lora_rank or LORA_RANK

    train_file, val_file, output_dir, checkpoints_dir = resolve_role_paths(role, cfg)

    if not train_file.exists():
        sys.exit(
            f"Training data not found at {train_file}.\n"
            f"Run export_branch.py --role {role or 'legacy'} first."
        )

    role_label = role.upper() if role else "LEGACY"
    print("=" * 60)
    print(f"Train Gemma 4  [{role_label}]")
    print("=" * 60)
    print(f"\n  Role:        {role_label}")
    print(f"  Model:       {model_id}")
    print(f"  Epochs:      {epochs}")
    print(f"  Batch size:  {batch_size}  (grad accum: {GRAD_ACCUM_STEPS})")
    print(f"  LR:          {lr}")
    print(f"  LoRA:        {'disabled' if args.no_lora else f'rank={lora_rank} alpha={LORA_ALPHA}'}")
    print(f"  4-bit:       {args.load_4bit}")
    print(f"  Train file:  {train_file}")
    print(f"  Output:      {output_dir}")

    # ── Load datasets ─────────────────────────────────────────────────────────
    print("\nLoading datasets...")
    train_rows = load_jsonl(train_file)
    val_rows   = load_jsonl(val_file) if val_file.exists() else []
    print(f"  Train: {len(train_rows):,}  Val: {len(val_rows):,}")

    train_ds = Dataset.from_list(train_rows)
    val_ds   = Dataset.from_list(val_rows) if val_rows else None

    # ── Tokenizer ─────────────────────────────────────────────────────────────
    print(f"\nLoading tokenizer from {model_id} ...")
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id

    # ── Model ─────────────────────────────────────────────────────────────────
    print(f"Loading model...")
    bnb_config = None
    if args.load_4bit:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )

    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_config,
        torch_dtype=torch.bfloat16 if not args.load_4bit else None,
        device_map="auto",
        trust_remote_code=True,
    )
    model.config.use_cache = False

    # ── LoRA ──────────────────────────────────────────────────────────────────
    if not args.no_lora:
        lora_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=lora_rank,
            lora_alpha=LORA_ALPHA,
            lora_dropout=0.05,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                            "gate_proj", "up_proj", "down_proj"],
            bias="none",
        )
        model = get_peft_model(model, lora_config)
        model.print_trainable_parameters()

    # ── Training config ───────────────────────────────────────────────────────
    sft_config = SFTConfig(
        output_dir=str(checkpoints_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=GRAD_ACCUM_STEPS,
        learning_rate=lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        bf16=True,
        logging_steps=50,
        eval_strategy="epoch" if val_ds else "no",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=bool(val_ds),
        metric_for_best_model="eval_loss" if val_ds else None,
        report_to="none",
        max_seq_length=MAX_SEQ_LENGTH,
        dataset_text_field=None,   # use messages format directly
        packing=False,
    )

    # ── Trainer ───────────────────────────────────────────────────────────────
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        args=sft_config,
        train_dataset=train_ds,
        eval_dataset=val_ds,
    )

    print("\nStarting training...")
    trainer.train()

    # ── Save final model ──────────────────────────────────────────────────────
    print(f"\nSaving final model → {output_dir}")
    if not args.no_lora:
        merged = trainer.model.merge_and_unload()
        merged.save_pretrained(str(output_dir))
    else:
        trainer.model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    print(f"\nDone. Fine-tuned model [{role_label}] saved to {output_dir}")
    print(f"Load it with: AutoModelForCausalLM.from_pretrained('{output_dir}')")


if __name__ == "__main__":
    main()
