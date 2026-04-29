#!/usr/bin/env python3
"""Kira QLoRA fine-tune - Gemma 4 26B."""
import os
import json
import shutil
import torch
import torch._inductor.config
import torch.nn as nn

# Backport set_submodule (added in torch 2.5, missing in 2.4.1)
if not hasattr(nn.Module, "set_submodule"):
    def _set_submodule(self, target, module):
        parts = target.split(".")
        parent = self.get_submodule(".".join(parts[:-1])) if len(parts) > 1 else self
        setattr(parent, parts[-1], module)
    nn.Module.set_submodule = _set_submodule

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

# Direct path to snapshot — bypasses HF Hub cache lookup entirely
MODEL_PATH = "/workspace/hf_cache/hub/models--unsloth--gemma-4-26b-a4b-it/snapshots/cd98c13581a9d4ad061cb85d983232ca4edb1343"
DATA_DIR   = "/workspace/verdict_training/data/ft"
OUTPUT_DIR = "/tmp/kira_adapter"
LOG_DIR    = "/tmp/kira_logs"
FINAL_DIR  = "/workspace/verdict_training/kira_adapter"

from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from datasets import Dataset
from trl import SFTTrainer, SFTConfig

# transformers 5.7 passes _is_hf_initialized to Params4bit but bitsandbytes 0.49 doesn't accept it
from bitsandbytes.nn import Params4bit as _P4b
_orig_p4b_new = _P4b.__new__
def _patched_p4b_new(cls, *args, **kwargs):
    kwargs.pop("_is_hf_initialized", None)
    return _orig_p4b_new(cls, *args, **kwargs)
_P4b.__new__ = _patched_p4b_new

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
    llm_int8_enable_fp32_cpu_offload=True,
)

print("Loading model from local path...", flush=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    quantization_config=bnb_config,
    device_map="auto",
    torch_dtype=torch.bfloat16,
    attn_implementation="eager",
    local_files_only=True,
)

print("Loading tokenizer...", flush=True)
tokenizer = AutoTokenizer.from_pretrained(
    MODEL_PATH,
    local_files_only=True,
)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

print("Preparing LoRA...", flush=True)
model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
model.gradient_checkpointing_enable()

lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def format_sample(ex):
    parts = []
    for m in ex["messages"]:
        parts.append("<|" + m["role"] + "|>")
        parts.append(m["content"])
        parts.append("<|end|>")
    parts.append("<|endoftext|>")
    return "\n".join(parts)


print("Loading data...", flush=True)
train_data = Dataset.from_list([{"text": format_sample(x)} for x in load_jsonl(DATA_DIR + "/train.jsonl")])
val_data   = Dataset.from_list([{"text": format_sample(x)} for x in load_jsonl(DATA_DIR + "/val.jsonl")])
print("Train: " + str(len(train_data)) + "  Val: " + str(len(val_data)), flush=True)

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_data,
    eval_dataset=val_data,
    args=SFTConfig(
        output_dir=OUTPUT_DIR,
        num_train_epochs=3,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        warmup_ratio=0.03,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        bf16=True,
        optim="adamw_8bit",
        logging_steps=20,
        eval_strategy="steps",
        eval_steps=200,
        save_strategy="steps",
        save_steps=500,
        save_total_limit=2,
        logging_dir=LOG_DIR,
        dataset_text_field="text",
        max_seq_length=768,
        report_to="none",
    ),
)

print("Starting training...", flush=True)
trainer.train()

model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)

os.makedirs(FINAL_DIR, exist_ok=True)
shutil.copytree(OUTPUT_DIR, FINAL_DIR, dirs_exist_ok=True)
print("Done. Adapter at " + FINAL_DIR, flush=True)
