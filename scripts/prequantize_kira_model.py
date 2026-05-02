#!/usr/bin/env python3
"""One-shot: load Gemma-4 26B-A4B bf16 via unsloth, quantize to nf4, save to disk.

After this runs once, training loads the saved nf4 directory directly onto a single
GPU with device_map={"":0} — no streaming, no consolidation, no accelerate hooks
to fight.
"""
import os
os.environ["HF_HOME"] = "/workspace/hf_cache"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import unsloth  # MUST be first
from unsloth import FastLanguageModel

import torch
from transformers import BitsAndBytesConfig
from bitsandbytes.nn import Params4bit as _P4b

_orig = _P4b.__new__
def _patched(cls, *args, **kwargs):
    kwargs.pop("_is_hf_initialized", None)
    return _orig(cls, *args, **kwargs)
_P4b.__new__ = _patched

MODEL_PATH = "/workspace/hf_cache/hub/models--unsloth--gemma-4-26B-A4B-it/snapshots/cd98c13581a9d4ad061cb85d983232ca4edb1343"
SAVE_PATH  = "/workspace/hf_cache/gemma4-26b-a4b-nf4"

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=False,
    llm_int8_enable_fp32_cpu_offload=True,
)

print("[1/3] Loading bf16 source and quantizing to nf4 (CPU-streamed)...", flush=True)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name           = MODEL_PATH,
    max_seq_length       = 1024,
    dtype                = None,
    full_finetuning      = False,
    quantization_config  = bnb_config,
    max_memory           = {0: "40GiB", "cpu": "200GiB"},
)
print(f"  GPU memory after load: {torch.cuda.memory_allocated()/1e9:.1f} GB", flush=True)

print("[2/3] Saving nf4 model + tokenizer to disk...", flush=True)
model.save_pretrained(SAVE_PATH, safe_serialization=True)
tokenizer.save_pretrained(SAVE_PATH)

print(f"[3/3] Done. Reload from {SAVE_PATH} with device_map={{'': 0}}.", flush=True)
