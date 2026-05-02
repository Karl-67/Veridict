#!/usr/bin/env python3
import os
os.environ["HF_HOME"] = "/workspace/hf_cache"

import torch
print("CUDA:", torch.cuda.is_available(), torch.cuda.get_device_name(0))

import bitsandbytes as bnb
print("bitsandbytes:", bnb.__version__)

from transformers import BitsAndBytesConfig, AutoModelForCausalLM

bnb_cfg = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
)

print("Loading model weights (this takes a minute)...")
model = AutoModelForCausalLM.from_pretrained(
    "unsloth/gemma-4-26B-A4B-it",
    quantization_config=bnb_cfg,
    device_map="auto",
    torch_dtype=torch.bfloat16,
    attn_implementation="eager",
)
print("Model loaded OK:", model.__class__.__name__)
print("Params:", sum(p.numel() for p in model.parameters()) // 1_000_000, "M")
