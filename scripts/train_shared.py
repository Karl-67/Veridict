"""
train_shared.py — Shared utilities for Harvey, Kira, and Admin GRPO QLoRA training.

Provides:
  - Prompt builders (one per model)
  - Reward functions
  - QLoRA / LoRA config builders
  - Data loaders (harvey, kira, admin synthesis)
  - Evaluation (metrics + sample completions)
"""

import gc
import json
import logging
import os
import random
import re
import shutil
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import torch
from datasets import Dataset
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import GRPOConfig

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "curated"
OUTPUT_ROOT = ROOT / "outputs"

# ── Model ─────────────────────────────────────────────────────────────────────

HF_MODEL_ID = os.environ.get("HF_MODEL_ID", "google/gemma-3-27b-it")

# ── Training hyper-parameters (tuned for RTX 4000 Ada, 21.5 GB VRAM) ─────────

MAX_PROMPT_LEN = 640
MAX_COMPLETION_LEN = 256
NUM_GENERATIONS = 4
TRAIN_BATCH = 1
GRAD_ACCUM = 8            # effective batch = 8
LR = 2e-4
MAX_STEPS = int(os.environ.get("MAX_STEPS", 2000))
LORA_RANK = 16
LORA_ALPHA = 32
SEED = 42

# Rows sampled per model (keeps each training run ≤ ~2 h on a single GPU)
HARVEY_TRAIN_N = 10_000
KIRA_TRAIN_N   =  4_000   # kira has 3× less data
ADMIN_TRAIN_N  = 12_000   # admin sees both branches

random.seed(SEED)

# ── Taxonomy ─────────────────────────────────────────────────────────────────

HARVEY_ISSUE_TYPES = {
    "liability_exposure", "restriction_clause", "ip_risk",
    "financial_obligation", "termination_risk", "governance_risk",
    "warranty_and_insurance", "dispute_resolution", "third_party_risk",
}
KIRA_ISSUE_TYPES = {
    "compliance_obligation", "jurisdictional_risk",
    "representation_risk", "confidentiality_risk",
}
ALL_ISSUE_TYPES = HARVEY_ISSUE_TYPES | KIRA_ISSUE_TYPES

SEVERITY_MAP = {
    "liability_exposure": "high", "ip_risk": "high",
    "termination_risk": "high", "governance_risk": "high",
    "restriction_clause": "medium", "financial_obligation": "medium",
    "compliance_obligation": "medium", "confidentiality_risk": "medium",
    "representation_risk": "medium", "warranty_and_insurance": "medium",
    "dispute_resolution": "low", "jurisdictional_risk": "low",
    "third_party_risk": "low",
}
VALID_SEVERITIES = {"low", "medium", "high"}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}

# ── System prompts ────────────────────────────────────────────────────────────

_ISSUE_TYPE_LIST = ", ".join(sorted(ALL_ISSUE_TYPES))
_SEVERITY_LIST = "low, medium, high"

HARVEY_SYSTEM = (
    "You are Harvey, a senior internal policy reviewer at a law firm. "
    "You specialise in commercial contract risk: liability exposure, IP ownership, "
    "financial obligations, termination rights, governance and assignment, "
    "warranty and insurance, dispute resolution, non-compete restrictions, and third-party rights. "
    "Given a contract clause, output a JSON object with exactly these fields:\n"
    "  issue_type      — one of: " + ", ".join(sorted(HARVEY_ISSUE_TYPES)) + "\n"
    "  severity        — one of: low, medium, high\n"
    "  description     — what the risk is and why it matters\n"
    "  recommendation  — the specific change or protection needed to fix this clause\n"
    "Output ONLY the JSON object, no other text."
)

KIRA_SYSTEM = (
    "You are Kira, a senior compliance and regulatory reviewer at a law firm. "
    "You specialise in regulatory obligations, jurisdictional risk, representation accuracy, "
    "and confidentiality protection. "
    "Given a contract clause, output a JSON object with exactly these fields:\n"
    "  issue_type      — one of: " + ", ".join(sorted(KIRA_ISSUE_TYPES)) + "\n"
    "  severity        — one of: low, medium, high\n"
    "  description     — what the compliance or regulatory risk is\n"
    "  recommendation  — the specific change needed to bring this clause into compliance\n"
    "Output ONLY the JSON object, no other text."
)

ADMIN_SYSTEM = (
    "You are a senior supervising partner (Admin) at a law firm. "
    "You receive findings from two specialists — Harvey (internal policy) and Kira (compliance) — "
    "who have each reviewed the same contract clause. "
    "Your job is to produce a single consensus finding that captures the most important risk. "
    "Rules:\n"
    "  1. If both specialists found an issue, surface the higher-severity one as primary; "
    "     incorporate the other in the recommendation.\n"
    "  2. If only one specialist found an issue, use that finding.\n"
    "  3. If neither found an issue, output {\"issue_type\": null, \"severity\": null, "
    "     \"description\": \"No material risk identified.\", \"recommendation\": \"No action required.\"}\n"
    "Output a JSON object with fields: issue_type, severity, description, recommendation. "
    "Output ONLY the JSON object, no other text."
)

# ── Prompt builders ───────────────────────────────────────────────────────────

def _gemma_chat(system: str, user: str) -> str:
    """Format a single-turn conversation for Gemma chat-tuned models.

    Gemma has no system role; fold system content into the first user turn.
    """
    return (
        f"<start_of_turn>user\n{system}\n\n{user}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


def harvey_prompt(clause_text: str) -> str:
    return _gemma_chat(
        HARVEY_SYSTEM,
        f"Review this contract clause and identify the internal policy risk:\n\n{clause_text.strip()}",
    )


def kira_prompt(clause_text: str) -> str:
    return _gemma_chat(
        KIRA_SYSTEM,
        f"Review this contract clause and identify the compliance or regulatory risk:\n\n{clause_text.strip()}",
    )


def admin_prompt(clause_text: str, harvey_finding: Optional[dict], kira_finding: Optional[dict]) -> str:
    h_str = json.dumps(harvey_finding, ensure_ascii=False) if harvey_finding else '{"status": "no_policy_issue_detected"}'
    k_str = json.dumps(kira_finding, ensure_ascii=False) if kira_finding else '{"status": "no_compliance_issue_detected"}'
    user_text = (
        f"Contract clause:\n{clause_text.strip()}\n\n"
        f"Harvey's finding (internal policy):\n{h_str}\n\n"
        f"Kira's finding (compliance):\n{k_str}\n\n"
        "Produce the consensus finding."
    )
    return _gemma_chat(ADMIN_SYSTEM, user_text)


# ── JSON parsing helper ───────────────────────────────────────────────────────

_REQUIRED_FIELDS = {"issue_type", "severity", "description", "recommendation"}


def parse_finding(text: str) -> Optional[dict]:
    """Extract and validate a finding JSON from model output. Returns None on failure."""
    text = re.sub(r"<end_of_turn>.*", "", text, flags=re.DOTALL).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group())
        return parsed if _REQUIRED_FIELDS.issubset(parsed.keys()) else None
    except json.JSONDecodeError:
        return None


# ── Reward functions ──────────────────────────────────────────────────────────

def _score_finding(completion: str, gt_issue: str, gt_severity: str, valid_issues: set) -> float:
    """Common scoring logic for Harvey and Kira completions."""
    parsed = parse_finding(completion)
    if parsed is None:
        return 0.0

    score = 0.3  # base: valid JSON with all fields

    pred_issue = str(parsed.get("issue_type", "")).lower().strip()
    if pred_issue == gt_issue:
        score += 1.0
    elif pred_issue in valid_issues:
        score += 0.1  # valid type, wrong answer

    pred_sev = str(parsed.get("severity", "")).lower().strip()
    if pred_sev == gt_severity:
        score += 0.5
    elif pred_sev in VALID_SEVERITIES:
        score += 0.1

    desc = str(parsed.get("description", "")).strip()
    rec  = str(parsed.get("recommendation", "")).strip()
    if len(desc) > 30 and len(rec) > 30:
        score += 0.2  # substantive text, not just template filler

    return score


def harvey_reward_fn(completions: list[str], **kwargs) -> list[float]:
    issue_types = kwargs.get("issue_type", [""] * len(completions))
    severities  = kwargs.get("severity",   [""] * len(completions))
    return [
        _score_finding(c, str(it).lower(), str(sv).lower(), HARVEY_ISSUE_TYPES)
        for c, it, sv in zip(completions, issue_types, severities)
    ]


def kira_reward_fn(completions: list[str], **kwargs) -> list[float]:
    issue_types = kwargs.get("issue_type", [""] * len(completions))
    severities  = kwargs.get("severity",   [""] * len(completions))
    return [
        _score_finding(c, str(it).lower(), str(sv).lower(), KIRA_ISSUE_TYPES)
        for c, it, sv in zip(completions, issue_types, severities)
    ]


def admin_reward_fn(completions: list[str], **kwargs) -> list[float]:
    """
    Admin must produce a valid consensus finding.
    Ground truth is the higher-severity of the two input findings.
    """
    gt_issues     = kwargs.get("gt_issue_type", [""] * len(completions))
    gt_severities = kwargs.get("gt_severity",   [""] * len(completions))
    rewards = []
    for c, gt_issue, gt_sev in zip(completions, gt_issues, gt_severities):
        if not gt_issue:
            # null finding expected
            parsed = parse_finding(c)
            if parsed and parsed.get("issue_type") is None:
                rewards.append(1.0)
            else:
                rewards.append(0.0)
            continue
        rewards.append(
            _score_finding(c, str(gt_issue).lower(), str(gt_sev).lower(), ALL_ISSUE_TYPES)
        )
    return rewards


# ── Data loading ──────────────────────────────────────────────────────────────

def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def load_harvey_dataset(n: int) -> Dataset:
    rows = _read_jsonl(DATA_DIR / "dataset_a" / "reviewer_train.jsonl")
    harvey = [
        r for r in rows
        if r.get("branch") == "harvey"
        and r.get("issue_type") in HARVEY_ISSUE_TYPES
        and r.get("agent_role") == "issue_discovery"
    ]
    random.shuffle(harvey)
    harvey = harvey[:n]

    examples = []
    for r in harvey:
        clause = str(r.get("clause_text", "")).strip()
        if len(clause.split()) < 5:
            continue
        examples.append({
            "prompt":     harvey_prompt(clause),
            "issue_type": r["issue_type"],
            "severity":   r.get("severity", SEVERITY_MAP.get(r["issue_type"], "medium")),
        })

    print(f"[Harvey] {len(examples):,} training examples")
    return Dataset.from_list(examples)


def load_kira_dataset(n: int) -> Dataset:
    rows = _read_jsonl(DATA_DIR / "dataset_a" / "reviewer_train.jsonl")
    kira = [
        r for r in rows
        if r.get("branch") == "kira"
        and r.get("issue_type") in KIRA_ISSUE_TYPES
        and r.get("agent_role") == "issue_discovery"
    ]
    random.shuffle(kira)
    kira = kira[:n]

    examples = []
    for r in kira:
        clause = str(r.get("clause_text", "")).strip()
        if len(clause.split()) < 5:
            continue
        examples.append({
            "prompt":     kira_prompt(clause),
            "issue_type": r["issue_type"],
            "severity":   r.get("severity", SEVERITY_MAP.get(r["issue_type"], "medium")),
        })

    print(f"[Kira] {len(examples):,} training examples")
    return Dataset.from_list(examples)


def load_admin_dataset(n: int) -> Dataset:
    """
    Synthesise admin training examples from Dataset A.

    For each clause in the dataset we build an admin prompt showing:
      - Harvey's finding (real JSON from dataset, or null placeholder)
      - Kira's finding  (real JSON from dataset, or null placeholder)
    Ground truth is the higher-severity finding.

    Synthesis strategy:
      1. Natural pairs  — same clause_text appears in both harvey and kira indexes
         (rare: possible when issue type varies by annotation pass)
      2. Harvey-primary — real harvey finding; synthetic "Kira: no compliance issue"
      3. Kira-primary   — real kira finding; synthetic "Harvey: no policy issue"
    """
    rows = _read_jsonl(DATA_DIR / "dataset_a" / "reviewer_train.jsonl")

    def to_finding(r: dict) -> dict:
        return {
            "issue_type":     r["issue_type"],
            "severity":       r.get("severity", SEVERITY_MAP.get(r["issue_type"], "medium")),
            "description":    r.get("description", ""),
            "recommendation": r.get("recommendation", ""),
        }

    harvey_rows = {
        r["clause_text"]: to_finding(r) for r in rows
        if r.get("branch") == "harvey"
        and r.get("issue_type") in HARVEY_ISSUE_TYPES
        and r.get("agent_role") == "issue_discovery"
    }
    kira_rows = {
        r["clause_text"]: to_finding(r) for r in rows
        if r.get("branch") == "kira"
        and r.get("issue_type") in KIRA_ISSUE_TYPES
        and r.get("agent_role") == "issue_discovery"
    }

    harvey_clauses = list(harvey_rows.keys())
    kira_clauses   = list(kira_rows.keys())
    natural_clauses = set(harvey_clauses) & set(kira_clauses)

    examples = []

    # 1. Natural pairs
    for clause in natural_clauses:
        hf = harvey_rows[clause]
        kf = kira_rows[clause]
        # ground truth = higher severity finding
        gt = hf if SEVERITY_RANK.get(hf["severity"], 0) >= SEVERITY_RANK.get(kf["severity"], 0) else kf
        examples.append({
            "prompt":       admin_prompt(clause, hf, kf),
            "gt_issue_type": gt["issue_type"],
            "gt_severity":   gt["severity"],
        })

    # 2. Harvey-primary (kira null)
    for clause in random.sample(harvey_clauses, min(len(harvey_clauses), n // 3)):
        hf = harvey_rows[clause]
        examples.append({
            "prompt":       admin_prompt(clause, hf, None),
            "gt_issue_type": hf["issue_type"],
            "gt_severity":   hf["severity"],
        })

    # 3. Kira-primary (harvey null)
    for clause in random.sample(kira_clauses, min(len(kira_clauses), n // 3)):
        kf = kira_rows[clause]
        examples.append({
            "prompt":       admin_prompt(clause, None, kf),
            "gt_issue_type": kf["issue_type"],
            "gt_severity":   kf["severity"],
        })

    random.shuffle(examples)
    examples = examples[:n]
    print(f"[Admin] {len(examples):,} training examples  "
          f"(natural={len(natural_clauses)}, "
          f"harvey-primary~{n//3}, kira-primary~{n//3})")
    return Dataset.from_list(examples)


# ── Model / LoRA / BnB builders ───────────────────────────────────────────────

def get_bnb_config() -> BitsAndBytesConfig:
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )


def get_lora_config() -> LoraConfig:
    return LoraConfig(
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )


def get_grpo_config(output_dir: Path, extra_tag: str = "", num_generations: int = NUM_GENERATIONS) -> GRPOConfig:
    return GRPOConfig(
        output_dir=str(output_dir),
        max_steps=MAX_STEPS,
        per_device_train_batch_size=TRAIN_BATCH,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LR,
        max_prompt_length=MAX_PROMPT_LEN,
        max_completion_length=MAX_COMPLETION_LEN,
        num_generations=num_generations,
        gradient_checkpointing=True,
        bf16=True,
        optim="paged_adamw_8bit",
        dataloader_num_workers=0,
        logging_steps=10,
        save_steps=100,
        save_total_limit=3,
        max_grad_norm=1.0,
        beta=0.02,
        report_to="none",
        seed=SEED,
        temperature=0.8,
        top_p=0.95,
    )


def load_base_model(model_id: str = HF_MODEL_ID):
    print(f"  Loading {model_id} in 4-bit NF4 ...")
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=get_bnb_config(),
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
    except Exception as e:
        print(f"  SDPA attention failed ({e}); falling back to eager attention.")
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=get_bnb_config(),
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
            attn_implementation="eager",
        )
    model.config.use_cache = False
    # Required for 4-bit + gradient checkpointing so gradients actually flow
    # through the quantized weights into the LoRA adapters.
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model.enable_input_require_grads()
    return model


def load_tokenizer(model_id: str = HF_MODEL_ID) -> AutoTokenizer:
    tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"
    return tok


# ── Evaluation ────────────────────────────────────────────────────────────────

def _build_eval_rows(model_name: str, rows: list[dict]):
    """Filter rows for a given model and return (rows, prompt_fn)."""
    if model_name == "harvey":
        rows = [r for r in rows if r.get("branch") == "harvey"
                and r.get("agent_role") == "issue_discovery"]
        return rows, lambda r: harvey_prompt(r["clause_text"])
    if model_name == "kira":
        rows = [r for r in rows if r.get("branch") == "kira"
                and r.get("agent_role") == "issue_discovery"]
        return rows, lambda r: kira_prompt(r["clause_text"])

    # admin
    rows = [r for r in rows if r.get("agent_role") == "issue_discovery"]

    def build_p(r):
        branch = r.get("branch", "harvey")
        finding = {
            "issue_type": r["issue_type"],
            "severity": r.get("severity", "medium"),
            "description": r.get("description", ""),
            "recommendation": r.get("recommendation", ""),
        }
        if branch == "harvey":
            return admin_prompt(r["clause_text"], finding, None)
        return admin_prompt(r["clause_text"], None, finding)

    return rows, build_p


def _run_eval_batch(
    model,
    tokenizer,
    rows: list[dict],
    build_p,
    n_samples_to_print: int = 0,
    label: str = "",
) -> dict:
    model.eval()
    issue_correct = 0
    severity_correct = 0
    valid_json = 0
    truncated = 0
    printed = 0

    for r in rows:
        prompt = build_p(r)
        gt_issue = r.get("issue_type", "")
        gt_sev   = r.get("severity", "")

        raw = tokenizer(prompt, return_tensors="pt")
        if raw["input_ids"].shape[1] > MAX_PROMPT_LEN:
            truncated += 1
        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_PROMPT_LEN,
        ).to(model.device)

        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=MAX_COMPLETION_LEN,
                do_sample=False,
                temperature=1.0,
            )
        new_tokens = out[0][inputs["input_ids"].shape[1]:]
        completion = tokenizer.decode(new_tokens, skip_special_tokens=True)

        parsed = parse_finding(completion)
        if parsed:
            valid_json += 1
            pred_issue = str(parsed.get("issue_type", "")).lower().strip()
            pred_sev   = str(parsed.get("severity", "")).lower().strip()
            if pred_issue == gt_issue:
                issue_correct += 1
            if pred_sev == gt_sev:
                severity_correct += 1

        if printed < n_samples_to_print:
            clause_preview = textwrap.shorten(r.get("clause_text", ""), width=120)
            print(f"\n--- {label} Sample {printed + 1} ---")
            print(f"Clause:       {clause_preview}")
            print(f"Ground truth: issue_type={gt_issue}, severity={gt_sev}")
            print(f"Model output: {completion.strip()[:300]}")
            printed += 1

    n = max(len(rows), 1)
    return {
        "n": len(rows),
        "valid_json_pct": valid_json / n,
        "issue_type_acc": issue_correct / n,
        "severity_acc":   severity_correct / n,
        "truncated":      truncated,
        "truncated_pct":  truncated / n,
    }


def evaluate_model(
    model,
    tokenizer: AutoTokenizer,
    model_name: str,
    dataset_split: str = "test",
    n_eval: int = 200,
    n_samples_to_print: int = 5,
):
    """
    Run the model on the test split (plus golden edge-case set), report metrics,
    and print sample outputs. Works for Harvey, Kira, and Admin.
    """
    print(f"\n{'='*60}")
    print(f"EVALUATION - {model_name.upper()}")
    print(f"{'='*60}")

    # Main test split
    test_rows = _read_jsonl(DATA_DIR / "dataset_a" / f"reviewer_{dataset_split}.jsonl")
    test_rows, build_p = _build_eval_rows(model_name, test_rows)
    random.shuffle(test_rows)
    test_rows = test_rows[:n_eval]
    if not test_rows:
        print("  No evaluation rows found in test split.")
        return {}

    metrics = _run_eval_batch(
        model, tokenizer, test_rows, build_p,
        n_samples_to_print=n_samples_to_print, label="Test",
    )

    n = metrics["n"]
    print(f"\n{'-'*40}")
    print(f"Test-split results over {n} examples:")
    print(f"  Valid JSON:           {metrics['valid_json_pct']:.1%}")
    print(f"  issue_type accuracy:  {metrics['issue_type_acc']:.1%}")
    print(f"  severity accuracy:    {metrics['severity_acc']:.1%}")
    print(f"  prompt truncations:   {metrics['truncated']}/{n} ({metrics['truncated_pct']:.1%})")
    print(f"{'-'*40}")

    # Golden edge-case eval
    golden_path = DATA_DIR / "golden" / "golden_edge_cases.jsonl"
    golden_metrics = {}
    if golden_path.exists():
        golden_rows = _read_jsonl(golden_path)
        golden_rows, golden_build = _build_eval_rows(model_name, golden_rows)
        if golden_rows:
            golden_metrics = _run_eval_batch(
                model, tokenizer, golden_rows, golden_build,
                n_samples_to_print=0, label="Golden",
            )
            gn = golden_metrics["n"]
            print(f"\nGolden edge-case results over {gn} examples:")
            print(f"  Valid JSON:           {golden_metrics['valid_json_pct']:.1%}")
            print(f"  issue_type accuracy:  {golden_metrics['issue_type_acc']:.1%}")
            print(f"  severity accuracy:    {golden_metrics['severity_acc']:.1%}")
            print(f"  prompt truncations:   {golden_metrics['truncated']}/{gn} ({golden_metrics['truncated_pct']:.1%})")
            print(f"{'-'*40}\n")
        else:
            print(f"  Golden set present but no rows matched {model_name}.\n")
    else:
        print(f"  Golden set not found at {golden_path}; skipping.\n")

    model.train()  # restore for any subsequent training
    result = {
        "valid_json_pct": metrics["valid_json_pct"],
        "issue_type_acc": metrics["issue_type_acc"],
        "severity_acc":   metrics["severity_acc"],
        "truncated":      metrics["truncated"],
        "n_test":         metrics["n"],
    }
    if golden_metrics:
        result.update({
            "golden_valid_json_pct": golden_metrics["valid_json_pct"],
            "golden_issue_type_acc": golden_metrics["issue_type_acc"],
            "golden_severity_acc":   golden_metrics["severity_acc"],
            "n_golden":              golden_metrics["n"],
        })
    return result


# ── Operational helpers (unattended-run scaffolding) ─────────────────────────

STATE_PATH     = OUTPUT_ROOT / "run_state.json"
HEARTBEAT_PATH = OUTPUT_ROOT / "heartbeat.txt"
LOG_PATH       = OUTPUT_ROOT / "training_run.log"


def preflight_checks() -> list[str]:
    """Return a list of fatal issues that would block an unattended run.

    Checks: HF auth, tokenizer reachable, ≥65 GB free disk, ≥18 GB VRAM,
    curated data present, key packages importable, output dir writable.
    """
    problems: list[str] = []

    # HF auth
    try:
        from huggingface_hub import whoami
        try:
            whoami()
        except Exception as e:
            problems.append(f"HuggingFace auth failed ({e}). Run `huggingface-cli login` or set HF_TOKEN.")
    except Exception as e:
        problems.append(f"huggingface_hub not importable: {e}")

    # Tokenizer probe (catches gated/nonexistent repo before 55 GB download starts)
    try:
        AutoTokenizer.from_pretrained(HF_MODEL_ID, trust_remote_code=True)
    except Exception as e:
        problems.append(f"Cannot load tokenizer for {HF_MODEL_ID}: {e}")

    # Disk space
    try:
        free_bytes = shutil.disk_usage(str(ROOT)).free
        if free_bytes < 65 * 1024 ** 3:
            problems.append(f"Only {free_bytes/1e9:.1f} GB free on {ROOT.drive or ROOT}; need ≥65 GB.")
    except Exception as e:
        problems.append(f"Disk check failed: {e}")

    # GPU VRAM
    if not torch.cuda.is_available():
        problems.append("No CUDA GPU detected.")
    else:
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        if vram < 18.0:
            problems.append(f"GPU {torch.cuda.get_device_name(0)} has only {vram:.1f} GB VRAM; need ≥18 GB.")

    # Data files
    required_files = [
        DATA_DIR / "dataset_a" / "reviewer_train.jsonl",
        DATA_DIR / "dataset_a" / "reviewer_test.jsonl",
        DATA_DIR / "dataset_b" / "validator_train.jsonl",
        DATA_DIR / "golden"    / "golden_edge_cases.jsonl",
    ]
    for p in required_files:
        if not p.exists():
            problems.append(f"Missing curated data file: {p}")

    # Key packages importable
    for pkg in ("torch", "transformers", "trl", "peft", "bitsandbytes", "accelerate", "datasets"):
        try:
            __import__(pkg)
        except Exception as e:
            problems.append(f"Package `{pkg}` not importable: {e}")

    # Output dir writable
    try:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        probe = OUTPUT_ROOT / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as e:
        problems.append(f"OUTPUT_ROOT {OUTPUT_ROOT} is not writable: {e}")

    return problems


class _TeeStream:
    """Duplicate writes to both the original stream and a logger."""
    def __init__(self, stream, logger, level):
        self._stream = stream
        self._logger = logger
        self._level = level
        self._buf = ""

    def write(self, data):
        self._stream.write(data)
        self._stream.flush()
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._logger.log(self._level, line)

    def flush(self):
        self._stream.flush()
        if self._buf.strip():
            self._logger.log(self._level, self._buf.strip())
            self._buf = ""

    def isatty(self):
        return getattr(self._stream, "isatty", lambda: False)()


def setup_logging(log_path: Path = LOG_PATH) -> logging.Logger:
    """Tee stdout + stderr to a rolling log file and install an uncaught-exception hook."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("veridict.training")
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.propagate = False

    sys.stdout = _TeeStream(sys.stdout, logger, logging.INFO)
    sys.stderr = _TeeStream(sys.stderr, logger, logging.ERROR)

    def _excepthook(exc_type, exc, tb):
        logger.error("Uncaught exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook
    logger.info("=" * 60)
    logger.info("Training session started at %s", datetime.now().isoformat(timespec="seconds"))
    logger.info("HF_MODEL_ID=%s  MAX_STEPS=%s  LR=%s", HF_MODEL_ID, MAX_STEPS, LR)
    return logger


def free_vram():
    """Release GPU memory between models. Windows sticks allocations otherwise."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass
        try:
            torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass


def _atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def write_heartbeat(model_name: str, step: int, reward_mean: float = 0.0,
                    reward_std: float = 0.0, extra: str = ""):
    """Emit a one-page status file consumable from a phone via OneDrive sync."""
    body = (
        f"model:        {model_name}\n"
        f"step:         {step} / {MAX_STEPS}\n"
        f"reward_mean:  {reward_mean:.4f}\n"
        f"reward_std:   {reward_std:.4f}\n"
        f"updated_at:   {datetime.now().isoformat(timespec='seconds')}\n"
    )
    if extra:
        body += f"\n{extra}\n"
    try:
        _atomic_write(HEARTBEAT_PATH, body)
    except Exception:
        pass  # never abort training over a failed heartbeat


def update_state(name: str, **fields):
    """Merge `fields` into outputs/run_state.json under key `name`."""
    try:
        state = {}
        if STATE_PATH.exists():
            try:
                state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        entry = state.get(name, {})
        entry.update(fields)
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        state[name] = entry
        _atomic_write(STATE_PATH, json.dumps(state, indent=2))
    except Exception:
        pass


def _windows_toast(title: str, body: str):
    if os.environ.get("DISABLE_TOASTS") == "1":
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes
        MB_ICONINFORMATION = 0x40
        MB_SYSTEMMODAL = 0x1000
        ctypes.windll.user32.MessageBoxW(
            0, body[:500], title[:100], MB_ICONINFORMATION | MB_SYSTEMMODAL
        )
    except Exception:
        pass


def _webhook_post(title: str, body: str):
    url = os.environ.get("TRAINING_WEBHOOK_URL")
    if not url:
        return
    try:
        import urllib.request
        payload = json.dumps({"title": title, "body": body, "content": f"{title}\n\n{body}"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def _email_send(title: str, body: str):
    to = os.environ.get("TRAINING_EMAIL")
    host = os.environ.get("SMTP_HOST")
    if not (to and host):
        return
    try:
        import smtplib
        from email.message import EmailMessage
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ.get("SMTP_USER")
        pw   = os.environ.get("SMTP_PASS")
        msg = EmailMessage()
        msg["Subject"] = f"[Veridict] {title}"
        msg["From"] = user or to
        msg["To"] = to
        msg.set_content(body)
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            if user and pw:
                s.login(user, pw)
            s.send_message(msg)
    except Exception:
        pass


def notify(title: str, body: str, level: str = "info"):
    """Best-effort: Windows toast + optional webhook + optional email.
    Any individual channel can fail without aborting training.
    """
    try:
        _windows_toast(title, body)
    except Exception:
        pass
    try:
        _webhook_post(title, body)
    except Exception:
        pass
    try:
        _email_send(title, body)
    except Exception:
        pass
