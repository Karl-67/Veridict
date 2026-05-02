# Kira QLoRA Runbook — Gemma 4 26B-A4B on RTX A5000 24 GB

## One-command bootstrap (fresh pod)

For a brand new runpod box, run `scripts/bootstrap_kira_pod.sh` on the box. It builds the venv with strictly-pinned versions (skips the 8-min unsloth resolver fight), downloads the model only if missing, and writes the training script + run wrapper. Idempotent.

From Windows git-bash, after creating the askpass helper (see "Prerequisites §1"):

```bash
SSH_ASKPASS=/tmp/sshhelper/askpass.sh SSH_ASKPASS_REQUIRE=force DISPLAY=:0 \
  ssh -o StrictHostKeyChecking=no -p 22019 student1@69.30.85.178 \
  'bash -s' < scripts/bootstrap_kira_pod.sh < /dev/null
```

When done, kick off training:
```bash
nohup bash /tmp/run_train.sh > /dev/null 2>&1 &
tail -f /workspace/verdict_training/train.log
```

The bootstrap also wires in a tokenized-data cache at `$TRAIN_DIR/tokenized_cache` so re-runs skip the 4-min tokenization pass, and pins `dataset_num_proc=8` (instead of 64) to avoid starving sshd.

Prereq: `/workspace/verdict_training/data/ft/{train,val,test}.jsonl` must already exist on the pod.

---

## Quick start (if everything still exists)

If the venv, model, and script are still present, re-run training with:

```bash
ssh -p 22019 student1@69.30.85.178
source /home/student1/kira_env/bin/activate
export HF_HOME=/workspace/hf_cache
export TRANSFORMERS_OFFLINE=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
cd /workspace/verdict_training && python kira_train.py
```

Or from Windows git-bash, non-interactively:

```bash
SSH_ASKPASS=/tmp/sshhelper/askpass.sh SSH_ASKPASS_REQUIRE=force DISPLAY=:0 \
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 22019 \
  student1@69.30.85.178 'source /home/student1/kira_env/bin/activate && \
  cd /workspace/verdict_training && python kira_train.py' < /dev/null
```

Monitor logs with `tail -f /workspace/verdict_training/train.log`.

---

## Environment Details

**Host:** runpod box, SSH `student1@69.30.85.178 -p 22019` (password: `student1`)

**Hardware:**
- GPU: 1x NVIDIA RTX A5000, 24 GB VRAM (23.5 GB usable)
- System RAM: 503 GB
- Storage:
  - `/home`: 60 GB overlay (per-user local, fast)
  - `/workspace`: MooseFS cluster (`mfs#ca-mtl-1.runpod.net:9421`), per-user quota ~60 GB (despite `df` reporting 192 TB free)

**Model:** `unsloth/gemma-4-26B-A4B-it`
- 26B-param MoE with 4B active params, 128 experts
- Multimodal (vision tower included)
- 51 GB in bf16 (no pre-quantized bnb-4bit variant exists for MoE; only GGUF and MLX quantized)

**Training data:** chat-format JSONL at `/workspace/verdict_training/data/ft/{train,val,test}.jsonl`
- 22858 train, 5327 val, 5273 test examples
- Format: `messages: [{role, content}]`

---

## Prerequisites

### 1. SSH from Windows (non-interactive)

SSH from git-bash requires the `SSH_ASKPASS` mechanism (no `sshpass` available by default).

```bash
mkdir -p /tmp/sshhelper
cat > /tmp/sshhelper/askpass.sh <<'BASH'
#!/bin/bash
echo "student1"
BASH
chmod +x /tmp/sshhelper/askpass.sh
```

Then invoke ssh with:

```bash
SSH_ASKPASS=/tmp/sshhelper/askpass.sh SSH_ASKPASS_REQUIRE=force DISPLAY=:0 \
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 22019 \
  student1@69.30.85.178 '<command>' < /dev/null
```

The `< /dev/null` is required — it closes stdin so ssh falls through to ASKPASS instead of hanging.

### 2. Understand `/workspace` quota limits

`df -h /workspace` reports cluster-wide free space (192 TB), **not per-user quota**. Per-user quota is ~60 GB.

Watch for:
```
OSError: [Errno 122] Disk quota exceeded
RuntimeError: Data processing error: File reconstruction error: IO Error: Disk quota exceeded
```

When quota is hit:
1. Delete stale model caches: `rm -rf /workspace/hf_cache/hub/models--unsloth--gemma-4-26b-a4b-it/*` (frees ~49 GB if the bf16 model was cached)
2. Move large artifacts to `/home` instead (it's local per-user and much faster)
3. Run `du -sh /workspace` and `du -sh /home` to confirm space freed

---

## Full Setup (from scratch)

### Step 1: Create Python venv in /home (not /workspace)

```bash
ssh -p 22019 student1@69.30.85.178
python3 -m venv /home/student1/kira_env
source /home/student1/kira_env/bin/activate
pip install --upgrade pip wheel setuptools
```

### Step 2: Install core dependencies

```bash
# Install torch first (unsloth will pull in transitive deps and fight over versions)
pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 \
  --index-url https://download.pytorch.org/whl/cu124

# Install the rest; unsloth's pins will resolve to:
# torch 2.10.0+cu128, transformers 5.5.0, accelerate 1.13.0, bitsandbytes 0.49.2
pip install --no-cache-dir "transformers==5.7.0" "accelerate>=1.13.0" \
  "bitsandbytes>=0.49.2" "peft>=0.19.1" "trl>=0.24.0" "datasets>=4.0.0" \
  sentencepiece protobuf "huggingface_hub[cli]"

# Install unsloth last (its deps will downgrade some packages)
pip install --no-cache-dir "unsloth>=2026.4.8" "unsloth_zoo>=2026.4.9"
```

Verify the install worked:

```bash
python -c "import torch, transformers, unsloth, bitsandbytes; \
  print(f'torch {torch.__version__}'); \
  print(f'transformers {transformers.__version__}'); \
  print(f'unsloth {unsloth.__version__}')"
```

Expected output:
```
torch 2.10.0+cu128
transformers 5.5.0
unsloth 2026.4.8
```

### Step 3: Download the model

The bf16 source model is 49 GB. Set `HF_HUB_ENABLE_HF_TRANSFER=0` (the default `hf_transfer` backend is unreliable and can leave 44 GB `.incomplete` files if the connection drops).

```bash
export HF_HOME=/workspace/hf_cache
export HF_HUB_ENABLE_HF_TRANSFER=0
python << 'PYTHON'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='unsloth/gemma-4-26B-A4B-it',
    cache_dir='/workspace/hf_cache/hub',
    max_workers=4,
    allow_patterns=['*.json', '*.safetensors', '*.model', 'tokenizer*', '*.txt'],
)
print("Download complete.")
PYTHON
```

This will take 10-20 minutes depending on network. The final snapshot path is:
```
/workspace/hf_cache/hub/models--unsloth--gemma-4-26B-A4B-it/snapshots/cd98c13581a9d4ad061cb85d983232ca4edb1343
```

Verify the snapshot exists:
```bash
ls -lh /workspace/hf_cache/hub/models--unsloth--gemma-4-26B-A4B-it/snapshots/cd98c13581a9d4ad061cb85d983232ca4edb1343/
```

### Step 4: Create training directories

```bash
mkdir -p /workspace/verdict_training/{kira_out,kira_logs}
ls -la /workspace/verdict_training/data/ft/  # Verify training data exists
```

### Step 5: Write the training script

Create `/workspace/verdict_training/kira_train.py`:

```python
#!/usr/bin/env python3
"""Kira QLoRA fine-tune - Gemma 4 26B-A4B-it (MoE) with CPU-streamed nf4 quantization."""
import os
os.environ["HF_HOME"] = "/workspace/hf_cache"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import unsloth  # MUST be imported before transformers
from unsloth import FastLanguageModel, is_bfloat16_supported

import json, shutil, torch
from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from transformers import BitsAndBytesConfig
from bitsandbytes.nn import Params4bit as _P4b

# Patch: transformers 5.5 passes _is_hf_initialized to Params4bit but bnb 0.49 doesn't accept it
_orig_p4b_new = _P4b.__new__
def _patched_p4b_new(cls, *args, **kwargs):
    kwargs.pop("_is_hf_initialized", None)
    return _orig_p4b_new(cls, *args, **kwargs)
_P4b.__new__ = _patched_p4b_new

MODEL_PATH = "/workspace/hf_cache/hub/models--unsloth--gemma-4-26B-A4B-it/snapshots/cd98c13581a9d4ad061cb85d983232ca4edb1343"
DATA_DIR   = "/workspace/verdict_training/data/ft"
OUTPUT_DIR = "/workspace/verdict_training/kira_out"
FINAL_DIR  = "/workspace/verdict_training/kira_adapter"
LOG_DIR    = "/workspace/verdict_training/kira_logs"
MAX_SEQ    = 512  # 24 GB GPU + MoE 26B nf4 + activations

print("[1/5] Loading BitsAndBytes config...")
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=False,  # MUST be False — True triggers meta-tensor crash
    llm_int8_enable_fp32_cpu_offload=True,  # Enables CPU spilling for weights
)

print("[2/5] Loading model and tokenizer (with nf4 quantization on CPU)...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name           = MODEL_PATH,
    max_seq_length       = MAX_SEQ,
    dtype                = None,
    full_finetuning      = False,
    quantization_config  = bnb_config,
    max_memory           = {0: "20GiB", "cpu": "300GiB"},  # Cap GPU at 20 GB so accelerate spills excess to CPU
)

print("[3/5] Applying LoRA with unsloth (auto-detects MoE)...")
model = FastLanguageModel.get_peft_model(
    model,
    r              = 16,
    lora_alpha     = 32,
    lora_dropout   = 0.0,
    bias           = "none",
    target_modules = ["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    use_gradient_checkpointing = "unsloth",
    random_state   = 3407,
    use_rslora     = False,
)

print("[4/5] Loading training data (chat format JSONL)...")
def load_jsonl(path):
    data = []
    with open(path, 'r') as f:
        for line in f:
            data.append(json.loads(line))
    return data

train_raw = load_jsonl(f"{DATA_DIR}/train.jsonl")
val_raw   = load_jsonl(f"{DATA_DIR}/val.jsonl")

def format_chat_template(example):
    """Convert {messages: [{role, content}]} to chat template string."""
    msgs = example["messages"]
    formatted = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
    return {"text": formatted}

train_ds = Dataset.from_list(train_raw).map(format_chat_template, num_proc=8)
val_ds   = Dataset.from_list(val_raw).map(format_chat_template, num_proc=8)

print(f"Train: {len(train_ds)} examples, Val: {len(val_ds)} examples")

print("[5/5] Initializing SFTTrainer...")
trainer = SFTTrainer(
    model              = model,
    tokenizer          = tokenizer,
    train_dataset      = train_ds,
    eval_dataset       = val_ds,
    args               = SFTConfig(
        output_dir             = OUTPUT_DIR,
        logging_dir            = LOG_DIR,
        num_train_epochs       = 1,
        per_device_train_batch_size = 2,
        per_device_eval_batch_size  = 4,
        gradient_accumulation_steps = 2,
        warmup_steps           = 100,
        learning_rate          = 5e-4,
        lr_scheduler_type      = "cosine",
        optim                  = "paged_adamw_32bit",
        weight_decay           = 0.01,
        max_grad_norm          = 1.0,
        logging_steps          = 10,
        eval_strategy          = "steps",
        eval_steps             = 100,
        save_strategy          = "steps",
        save_steps             = 100,
        save_total_limit       = 2,
        bf16                   = is_bfloat16_supported(),
        seed                   = 3407,
        dataloader_num_workers = 4,
    ),
    max_seq_length     = MAX_SEQ,
    packing            = False,
    dataset_text_field = "text",
)

print("\n=== TRAINING START ===\n")
trainer.train()

print("\n=== TRAINING COMPLETE ===\n")
print(f"Saving final adapter to {FINAL_DIR}...")
model.save_pretrained(FINAL_DIR, safe_serialization=True)
tokenizer.save_pretrained(FINAL_DIR)

print("Done! LoRA adapter saved.")
```

### Step 6: Run training with logging

```bash
cat > /tmp/run_train.sh <<'BASH'
#!/bin/bash
exec > /workspace/verdict_training/train.log 2>&1
source /home/student1/kira_env/bin/activate
export HF_HOME=/workspace/hf_cache
export TRANSFORMERS_OFFLINE=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
echo "=== START $(date) ==="
cd /workspace/verdict_training
python kira_train.py
echo "=== END $(date) RC=$? ==="
BASH
chmod +x /tmp/run_train.sh
nohup bash /tmp/run_train.sh > /dev/null 2>&1 &
echo "Training running in background. Monitor with: tail -f /workspace/verdict_training/train.log"
```

Monitor with:

```bash
tail -f /workspace/verdict_training/train.log
```

---

## Pitfall log

This section documents every error encountered during development and the exact fix.

| Error | Root cause | Fix |
|-------|-----------|-----|
| `RuntimeError: Tensor.item() cannot be called on meta tensors` | `bnb_4bit_use_double_quant=True` causes `QuantState.as_dict` to call `.item()` on nested-quant `offset` tensor during accelerate's dispatch phase, when tensor is still on meta device | Set `bnb_4bit_use_double_quant=False` in BitsAndBytesConfig |
| `Params4bit.__new__() got an unexpected keyword argument '_is_hf_initialized'` | transformers 5.5/5.7 passes new `_is_hf_initialized` kwarg; bitsandbytes 0.49.2 does not accept it | Monkey-patch `Params4bit.__new__` to pop the kwarg before calling original |
| `RuntimeError: Some modules are dispatched on the CPU or the disk. Make sure that all modules are on the same device` | bitsandbytes refuses CPU offload by default; model too large for 24 GB GPU | Set `llm_int8_enable_fp32_cpu_offload=True` in BitsAndBytesConfig and `max_memory={0: "20GiB", "cpu": "300GiB"}` to force accelerate to stream weights through CPU |
| `CUDA out of memory. Tried to allocate 484.00 MiB` at 33% weight load | `device_map="auto"` forces all bf16 weights onto GPU before quantization happens; 26B bf16 = 52 GB, exceeds 24 GB | Use `max_memory` dict instead; accelerate will stream weights through CPU and quantize on-device |
| `OSError: [Errno 122] Disk quota exceeded` mid-install or mid-download | Per-user `/workspace` quota is ~60 GB despite `df` reporting 192 TB cluster-wide free | (1) Delete stale model caches, (2) Move venv to `/home/student1` (local per-user, 60 GB), (3) Use `du -sh` to confirm space freed |
| `RepositoryNotFoundError: 401 Client Error` for `unsloth/gemma-4-26B-A4B-it-unsloth-bnb-4bit` | Pre-quantized bnb-4bit repo does not exist for 26B-A4B MoE (only bf16, GGUF, MLX exist) | Download bf16 source, quantize on-the-fly with CPU offload |
| `AttributeError: module 'torch._inductor' has no attribute 'config'` during unsloth_zoo import | unsloth requires torch >= 2.5; box had 2.4.1+cu124 | Build venv from scratch; unsloth's dependency pins will pull torch 2.10.0+cu128 |
| `kex_exchange_identification: Connection reset by peer` then `Connection timed out during banner exchange` | Server CPU saturated by tokenization with `num_proc=64` + CPU-offloaded weight movement; sshd starved | Reduce `num_proc` from 64 to 8 in tokenization, or pre-tokenize once and cache, or accept 5-10 min reduced sshd responsiveness during weight load |

---

## Open issues / future hardening

1. **CPU offload is slow.** The `max_memory` cap forces weights to move between RAM and GPU on every forward step, which is much slower than keeping everything on-device. If you get a larger GPU (A6000 48 GB or A100 80 GB), drop the `max_memory` constraint entirely.

2. **Tokenization with `num_proc=64` saturates the box.** When the training script tokenizes data with 64 workers, it burns CPU so hard that sshd becomes unresponsive. Reduce to `num_proc=8` or pre-tokenize once and save to disk.

3. **Training progress was never confirmed.** The last observed state was tokenization at 31% completion, then sshd became unreachable. On next run, check `/workspace/verdict_training/train.log` in a second terminal or write a status script that tails the log periodically.

4. **Pre-quantize the model once.** The nf4 quantization happens on-the-fly during each `from_pretrained` call (~6 min CPU streaming). After loading once, save the quantized model to disk with `model.save_pretrained("/path/to/quantized")` and reload from there on subsequent runs (much faster).

5. **Monitor GPU memory during the weight load phase.** Use `nvidia-smi` in a second terminal to watch VRAM usage creep from 0 to 20 GB during quantization. If it spikes above 21 GB, the model will OOM; reduce `max_memory[0]` further or add a `max_memory["cpu"]` bound.

---

## Troubleshooting checklist

If training fails, go through in order:

- [ ] Venv is activated: `which python` outputs `/home/student1/kira_env/bin/python`
- [ ] Environment variables set: `echo $HF_HOME`, `echo $PYTORCH_CUDA_ALLOC_CONF`
- [ ] Model snapshot exists: `ls /workspace/hf_cache/hub/models--unsloth--gemma-4-26B-A4B-it/snapshots/cd98c13581a9d4ad061cb85d983232ca4edb1343/`
- [ ] Training data readable: `wc -l /workspace/verdict_training/data/ft/{train,val,test}.jsonl`
- [ ] Disk quota OK: `du -sh /workspace` and `du -sh /home/student1` (sum should be < 120 GB)
- [ ] GPU present and visible: `nvidia-smi` shows RTX A5000 with 24 GB
- [ ] No stale Python processes: `ps aux | grep python` and `kill -9 <pid>` if needed
- [ ] Log tail: `tail -50 /workspace/verdict_training/train.log` to see last errors

---

## Quick reference: key paths and commands

**Paths:**
- Venv: `/home/student1/kira_env`
- Model cache: `/workspace/hf_cache/hub/models--unsloth--gemma-4-26B-A4B-it/snapshots/cd98c13581a9d4ad061cb85d983232ca4edb1343`
- Training script: `/workspace/verdict_training/kira_train.py`
- Training data: `/workspace/verdict_training/data/ft/{train,val,test}.jsonl`
- Output adapter: `/workspace/verdict_training/kira_adapter`
- Logs: `/workspace/verdict_training/train.log`

**Commands:**
```bash
# Activate venv
source /home/student1/kira_env/bin/activate

# Check versions
python -c "import torch, transformers; print(torch.__version__, transformers.__version__)"

# Monitor training
tail -f /workspace/verdict_training/train.log

# Check GPU
nvidia-smi

# Check disk quota
du -sh /workspace /home/student1

# Kill stuck training
pkill -f kira_train.py

# SSH from Windows
SSH_ASKPASS=/tmp/sshhelper/askpass.sh SSH_ASKPASS_REQUIRE=force DISPLAY=:0 \
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 22019 \
  student1@69.30.85.178
```

