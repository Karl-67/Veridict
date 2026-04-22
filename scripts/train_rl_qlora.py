#!/usr/bin/env python3
"""
train_rl_qlora.py — GRPO Reinforcement Learning with QLoRA

Fine-tunes Gemma 4 27B (or any causal LM) on contract review data using:
  - QLoRA: 4-bit quantization + LoRA adapters (fits 26B in ~16GB VRAM)
  - GRPO: Group Relative Policy Optimization (no critic model needed)

Tasks trained jointly:
  1. Reviewer  — given a clause, output JSON with issue_type / severity / description / recommendation
  2. Validator — given a clause + hypothesis, output retain / reject / uncertain

Reward signals:
  Reviewer:
    +1.0  correct issue_type (exact match)
    +0.5  correct severity
    +0.3  valid JSON with all required fields
    +0.2  non-empty description AND recommendation
  Validator:
    +1.0  correct verdict (retain / reject / uncertain)
    +0.0  wrong but parseable verdict
    -0.5  unparseable / empty output

Usage:
  1. Set HF_MODEL_ID to your Gemma 4 HuggingFace model ID (gated — needs HF login)
  2. Run: python scripts/train_rl_qlora.py
  3. Adapter saved to: outputs/rl_qlora_adapter/
"""

import json
import os
import re
import random
from pathlib import Path
from typing import Optional

import torch
from datasets import Dataset
from peft import LoraConfig
from transformers import AutoTokenizer, BitsAndBytesConfig
from trl import GRPOConfig, GRPOTrainer

# ── Configuration ─────────────────────────────────────────────────────────────

# Set this to your HuggingFace model ID for Gemma 4 27B.
# Run `huggingface-cli login` first if the model is gated.
HF_MODEL_ID = os.environ.get("HF_MODEL_ID", "google/gemma-3-27b-it")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "curated"
OUTPUT_DIR = ROOT / "outputs" / "rl_qlora_adapter"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Training knobs — tuned for RTX 4000 Ada (20 GB VRAM) with a 26B model
MAX_PROMPT_LENGTH = 512       # tokens — reviewer clause + system prompt
MAX_COMPLETION_LENGTH = 384   # tokens — JSON reviewer output or single verdict word
NUM_GENERATIONS = 4           # GRPO samples this many completions per prompt
TRAIN_BATCH_SIZE = 1          # per-device (VRAM limited)
GRAD_ACCUM_STEPS = 8          # effective batch = 8
LEARNING_RATE = 5e-6
NUM_TRAIN_EPOCHS = 1
MAX_TRAIN_STEPS = 2000        # override epochs for long datasets
LORA_RANK = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
REVIEWER_SAMPLE_SIZE = 8000   # rows from Dataset A to keep (full 172k is very slow)
VALIDATOR_SAMPLE_SIZE = 4000  # rows from Dataset B train split

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

REQUIRED_REVIEWER_FIELDS = {"issue_type", "severity", "description", "recommendation"}
VALID_VERDICTS = {"retain", "reject", "uncertain"}
VALID_ISSUE_TYPES = {
    "liability_exposure", "restriction_clause", "ip_risk", "financial_obligation",
    "termination_risk", "governance_risk", "compliance_obligation", "dispute_resolution",
    "confidentiality_risk", "warranty_and_insurance", "jurisdictional_risk",
    "representation_risk", "third_party_risk",
}
VALID_SEVERITIES = {"low", "medium", "high"}

# ── Prompts ───────────────────────────────────────────────────────────────────

REVIEWER_SYSTEM = (
    "You are a senior legal analyst performing contract risk review. "
    "Given a contract clause, identify the legal risk it presents and output a JSON object "
    "with exactly these fields: issue_type, severity, description, recommendation. "
    "issue_type must be one of: liability_exposure, restriction_clause, ip_risk, "
    "financial_obligation, termination_risk, governance_risk, compliance_obligation, "
    "dispute_resolution, confidentiality_risk, warranty_and_insurance, jurisdictional_risk, "
    "representation_risk, third_party_risk. "
    "severity must be one of: low, medium, high. "
    "Output ONLY the JSON object, no other text."
)

VALIDATOR_SYSTEM = (
    "You are a legal clause validator. "
    "Given a contract clause and a proposed legal finding, determine whether the finding "
    "is supported by the clause. "
    "Output exactly one word: retain (finding is grounded), reject (finding contradicts the clause), "
    "or uncertain (insufficient information). "
    "Output ONLY the single word, nothing else."
)


def build_reviewer_prompt(clause_text: str) -> str:
    return (
        f"<start_of_turn>system\n{REVIEWER_SYSTEM}<end_of_turn>\n"
        f"<start_of_turn>user\nReview this contract clause:\n\n{clause_text.strip()}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


def build_validator_prompt(premise: str, hypothesis: str) -> str:
    return (
        f"<start_of_turn>system\n{VALIDATOR_SYSTEM}<end_of_turn>\n"
        f"<start_of_turn>user\n"
        f"Contract clause: {premise.strip()}\n\n"
        f"Proposed finding: {hypothesis.strip()}\n\n"
        f"Is this finding supported?<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


# ── Reward functions ──────────────────────────────────────────────────────────

def reviewer_reward(completions: list[str], issue_types: list[str], severities: list[str]) -> list[float]:
    """Score reviewer completions. Called by GRPOTrainer per batch."""
    rewards = []
    for completion, gt_issue, gt_severity in zip(completions, issue_types, severities):
        score = 0.0
        text = completion.strip()

        # Strip any trailing <end_of_turn> tokens the model might add
        text = re.sub(r"<end_of_turn>.*", "", text, flags=re.DOTALL).strip()

        # Try to extract JSON (model might wrap in ```json ... ```)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not json_match:
            rewards.append(-0.5)
            continue

        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            rewards.append(-0.3)
            continue

        # All required fields present
        if REQUIRED_REVIEWER_FIELDS.issubset(parsed.keys()):
            score += 0.3

        # Correct issue_type
        predicted_issue = str(parsed.get("issue_type", "")).lower().strip()
        if predicted_issue == gt_issue:
            score += 1.0
        elif predicted_issue in VALID_ISSUE_TYPES:
            score += 0.1  # partial credit for valid but wrong type

        # Correct severity
        predicted_severity = str(parsed.get("severity", "")).lower().strip()
        if predicted_severity == gt_severity:
            score += 0.5
        elif predicted_severity in VALID_SEVERITIES:
            score += 0.1

        # Non-empty description and recommendation
        desc = str(parsed.get("description", "")).strip()
        rec = str(parsed.get("recommendation", "")).strip()
        if len(desc) > 20 and len(rec) > 20:
            score += 0.2

        rewards.append(score)

    return rewards


def validator_reward(completions: list[str], verdicts: list[str]) -> list[float]:
    """Score validator completions."""
    rewards = []
    for completion, gt_verdict in zip(completions, verdicts):
        text = completion.strip().lower()
        text = re.sub(r"<end_of_turn>.*", "", text, flags=re.DOTALL).strip()

        # Extract first word that matches a valid verdict
        found = None
        for word in text.split():
            word_clean = re.sub(r"[^\w]", "", word)
            if word_clean in VALID_VERDICTS:
                found = word_clean
                break

        if found is None:
            rewards.append(-0.5)
        elif found == gt_verdict:
            rewards.append(1.0)
        else:
            rewards.append(0.0)

    rewards_list = rewards
    return rewards_list


def combined_reward_fn(completions, **kwargs):
    """
    Unified reward function dispatched by task type.
    GRPO passes completions + all dataset columns from the prompt batch.
    """
    task_types = kwargs.get("task_type", [])
    issue_types = kwargs.get("issue_type", [])
    severities = kwargs.get("severity", [])
    verdicts = kwargs.get("verdict", [])

    rewards = []
    for i, (completion, task) in enumerate(zip(completions, task_types)):
        if task == "reviewer":
            r = reviewer_reward(
                [completion],
                [issue_types[i] if i < len(issue_types) else ""],
                [severities[i] if i < len(severities) else ""],
            )[0]
        else:  # validator
            r = validator_reward(
                [completion],
                [verdicts[i] if i < len(verdicts) else ""],
            )[0]
        rewards.append(r)

    return rewards


# ── Dataset loading ───────────────────────────────────────────────────────────

def load_reviewer_examples(n: int) -> list[dict]:
    path = DATA_DIR / "dataset_a" / "reviewer_train.jsonl"
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    random.shuffle(rows)
    rows = rows[:n]

    examples = []
    for r in rows:
        clause = str(r.get("clause_text", "")).strip()
        issue = str(r.get("issue_type", "")).strip()
        severity = str(r.get("severity", "medium")).strip()
        if not clause or issue not in VALID_ISSUE_TYPES:
            continue
        examples.append({
            "prompt": build_reviewer_prompt(clause),
            "task_type": "reviewer",
            "issue_type": issue,
            "severity": severity,
            "verdict": "",           # unused for reviewer
        })
    print(f"[Data] Loaded {len(examples)} reviewer training examples")
    return examples


def load_validator_examples(n: int) -> list[dict]:
    path = DATA_DIR / "dataset_b" / "validator_train.jsonl"
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    random.shuffle(rows)
    rows = rows[:n]

    examples = []
    for r in rows:
        premise = str(r.get("premise", "")).strip()
        hypothesis = str(r.get("hypothesis", "")).strip()
        verdict = str(r.get("verdict", "")).strip()
        if not premise or not hypothesis or verdict not in VALID_VERDICTS:
            continue
        examples.append({
            "prompt": build_validator_prompt(premise, hypothesis),
            "task_type": "validator",
            "issue_type": "",        # unused for validator
            "severity": "",
            "verdict": verdict,
        })
    print(f"[Data] Loaded {len(examples)} validator training examples")
    return examples


# ── QLoRA + model setup ───────────────────────────────────────────────────────

def get_bnb_config() -> BitsAndBytesConfig:
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",           # Normal Float 4 — best quality for NLP
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,      # extra ~0.4 bpw saving from second quantization
    )


def get_lora_config() -> LoraConfig:
    return LoraConfig(
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type="CAUSAL_LM",
        # Target the attention projections and feed-forward layers for best coverage
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("GRPO RL QLoRA Training — Veridict Contract Review")
    print("=" * 60)
    print(f"Model: {HF_MODEL_ID}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    # ── Verify CUDA ───────────────────────────────────────────────────────────
    if not torch.cuda.is_available():
        raise RuntimeError("No CUDA GPU found. This script requires a CUDA GPU.")
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"GPU: {torch.cuda.get_device_name(0)}  ({vram_gb:.1f} GB VRAM)")
    print()

    # ── Load datasets ─────────────────────────────────────────────────────────
    print("[1/4] Loading training data...")
    reviewer_examples = load_reviewer_examples(REVIEWER_SAMPLE_SIZE)
    validator_examples = load_validator_examples(VALIDATOR_SAMPLE_SIZE)

    all_examples = reviewer_examples + validator_examples
    random.shuffle(all_examples)
    dataset = Dataset.from_list(all_examples)
    print(f"[Data] Total training examples: {len(dataset)}")
    print()

    # ── Load tokenizer ────────────────────────────────────────────────────────
    print("[2/4] Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(HF_MODEL_ID, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"   # required for causal LM generation
    print(f"[Tokenizer] Vocab size: {tokenizer.vocab_size}")
    print()

    # ── GRPO config ───────────────────────────────────────────────────────────
    grpo_config = GRPOConfig(
        output_dir=str(OUTPUT_DIR),
        num_train_epochs=NUM_TRAIN_EPOCHS,
        max_steps=MAX_TRAIN_STEPS,
        per_device_train_batch_size=TRAIN_BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM_STEPS,
        learning_rate=LEARNING_RATE,
        max_prompt_length=MAX_PROMPT_LENGTH,
        max_completion_length=MAX_COMPLETION_LENGTH,
        num_generations=NUM_GENERATIONS,
        # Memory optimizations
        gradient_checkpointing=True,
        bf16=True,
        optim="paged_adamw_8bit",     # 8-bit optimizer saves ~4GB vs Adam
        dataloader_num_workers=0,      # Windows: no multiprocessing in DataLoader
        # Logging
        logging_steps=10,
        save_steps=200,
        save_total_limit=3,
        report_to="none",             # set to "wandb" if you have wandb
        seed=RANDOM_SEED,
        # GRPO-specific
        temperature=0.8,
        top_p=0.95,
    )

    # ── Load model in 4-bit ───────────────────────────────────────────────────
    print("[3/4] Loading model in 4-bit QLoRA mode...")
    print("      (This downloads ~14 GB of weights on first run — may take several minutes)")
    from transformers import AutoModelForCausalLM
    model = AutoModelForCausalLM.from_pretrained(
        HF_MODEL_ID,
        quantization_config=get_bnb_config(),
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        attn_implementation="eager",  # flash_attention_2 requires specific build; eager is safe
    )
    model.config.use_cache = False   # required for gradient checkpointing
    print(f"[Model] Loaded. Parameters: {sum(p.numel() for p in model.parameters()) / 1e9:.1f}B")
    print()

    # ── Train ─────────────────────────────────────────────────────────────────
    print("[4/4] Starting GRPO training...")
    trainer = GRPOTrainer(
        model=model,
        args=grpo_config,
        train_dataset=dataset,
        reward_funcs=combined_reward_fn,
        peft_config=get_lora_config(),
        processing_class=tokenizer,
    )

    trainer.train()

    # ── Save adapter ──────────────────────────────────────────────────────────
    print(f"\nSaving LoRA adapter to {OUTPUT_DIR} ...")
    trainer.save_model(str(OUTPUT_DIR))
    tokenizer.save_pretrained(str(OUTPUT_DIR))
    print("Done.")

    # ── Quick eval on golden set ──────────────────────────────────────────────
    print("\nRunning quick evaluation on golden edge-case set...")
    run_golden_eval(model, tokenizer)


def run_golden_eval(model, tokenizer):
    """Score the trained adapter on a sample of golden edge cases."""
    golden_path = DATA_DIR / "golden" / "golden_edge_cases.jsonl"
    if not golden_path.exists():
        print("[Eval] golden_edge_cases.jsonl not found — skipping eval")
        return

    examples = []
    with open(golden_path, encoding="utf-8") as f:
        for line in f:
            try:
                examples.append(json.loads(line))
            except Exception:
                pass

    # Only eval contradiction + false_positive_trap categories (have clear verdicts)
    eval_rows = [r for r in examples if r.get("category") in ("contradiction", "false_positive_trap")][:20]
    if not eval_rows:
        print("[Eval] No suitable eval rows found")
        return

    model.eval()
    correct = 0
    for row in eval_rows:
        clause = str(row.get("clause_text", ""))
        hypothesis = str(row.get("hypothesis") or "")
        expected_verdict = row.get("expected_behavior", {}).get("validator_verdict")

        if row["category"] == "contradiction" and hypothesis and expected_verdict:
            prompt = build_validator_prompt(clause, hypothesis)
            inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512).to(model.device)
            with torch.no_grad():
                outputs = model.generate(**inputs, max_new_tokens=10, do_sample=False)
            decoded = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
            predicted = decoded.strip().lower().split()[0] if decoded.strip() else ""
            if predicted == expected_verdict:
                correct += 1

    total = len([r for r in eval_rows if r["category"] == "contradiction"])
    if total > 0:
        print(f"[Eval] Contradiction detection accuracy: {correct}/{total} = {correct/total:.1%}")
    print("[Eval] Done.")


if __name__ == "__main__":
    main()
