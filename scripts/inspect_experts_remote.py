#!/usr/bin/env python3
"""Inspect PJMixers expert module structure in detail."""
import os
os.environ["HF_HOME"] = "/root/hf_cache"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import torch
from transformers import AutoModelForCausalLM
from bitsandbytes.nn import Params4bit

m = AutoModelForCausalLM.from_pretrained(
    "PJMixers-Dev/Qwen3-30B-A3B-Instruct-2507-bnb-4bit",
    device_map={"": 0}, dtype=torch.bfloat16,
)
print("config._experts_implementation =", getattr(m.config, "_experts_implementation", "<unset>"))
print("config.moe_intermediate_size =", m.config.moe_intermediate_size)
print("config.hidden_size =", m.config.hidden_size)

exp = m.model.layers[0].mlp.experts
print("experts class:", type(exp).__name__)
print("experts named_children:", [(n, type(c).__name__) for n,c in exp.named_children()])

print("experts parameters:")
for n, p in exp.named_parameters(recurse=False):
    qs = getattr(p, "quant_state", None)
    print(f"  {n}  type={type(p).__name__}  shape={tuple(p.shape)}  dtype={p.dtype}  qs={'OK' if qs is not None else 'NONE'}")

# Check buffers too (sometimes quant_state lives there)
print("experts buffers:")
for n, b in exp.named_buffers(recurse=False):
    print(f"  {n}  shape={tuple(b.shape)}  dtype={b.dtype}")

# Recursive
print("\nALL experts named_parameters (recurse):")
for n, p in exp.named_parameters():
    qs = getattr(p, "quant_state", None)
    print(f"  {n}  type={type(p).__name__}  shape={tuple(p.shape)}  qs={'OK' if qs is not None else 'NONE'}")

# Check raw safetensors keys for layer 0 to see what the checkpoint actually has
import glob
from safetensors import safe_open
shards = sorted(glob.glob("/root/hf_cache/hub/models--PJMixers-Dev--*/snapshots/*/model-*-of-*.safetensors"))
print(f"\nshards: {len(shards)}")
keys_layer0 = []
for s in shards:
    with safe_open(s, framework="pt") as f:
        for k in f.keys():
            if "layers.0.mlp.experts" in k:
                t = f.get_slice(k)
                shape = tuple(t.get_shape())
                keys_layer0.append((k, shape))
print(f"\nlayer 0 expert keys ({len(keys_layer0)}):")
for k, sh in sorted(keys_layer0)[:20]:
    print(f"  {sh!s:20s}  {k}")
if len(keys_layer0) > 20:
    print(f"  ... and {len(keys_layer0)-20} more")
