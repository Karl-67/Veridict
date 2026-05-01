#!/bin/bash
# Bootstrap a fresh runpod box for Kira QLoRA fine-tune (Gemma 4 26B-A4B).
# Idempotent: safe to re-run. Skips steps already complete.
#
# Run from the box (after SSH'ing in):
#   bash bootstrap_kira_pod.sh
#
# Or from Windows git-bash (one-liner):
#   SSH_ASKPASS=/tmp/sshhelper/askpass.sh SSH_ASKPASS_REQUIRE=force DISPLAY=:0 \
#     ssh -o StrictHostKeyChecking=no -p 22019 student1@69.30.85.178 \
#     'bash -s' < scripts/bootstrap_kira_pod.sh < /dev/null
#
# Prereq on the box: training data must already be at
#   /workspace/verdict_training/data/ft/{train,val,test}.jsonl

set -e
set -o pipefail

VENV=/root/kira_env
HF_CACHE=/workspace/hf_cache
TRAIN_DIR=/workspace/verdict_training
MODEL_REPO="unsloth/gemma-4-26B-A4B-it"
MODEL_DIR_GLOB="$HF_CACHE/hub/models--unsloth--gemma-4-26B-A4B-it/snapshots/*"

echo "=== Bootstrap start $(date) ==="

# 1. venv
if [ ! -x "$VENV/bin/python" ]; then
    echo "[1/5] Creating venv at $VENV"
    python3 -m venv "$VENV"
else
    echo "[1/5] venv exists, skipping"
fi

source "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip wheel setuptools

# 2. pinned deps (these are the versions that actually resolve and work together;
#    they match the unsloth==2026.4.8 pin tree so the resolver doesn't churn)
echo "[2/5] Installing pinned dependencies"
pip install --no-cache-dir --quiet \
    torch==2.10.0+cu128 torchvision==0.25.0 \
    --index-url https://download.pytorch.org/whl/cu128 || \
pip install --no-cache-dir --quiet \
    torch==2.10.0 torchvision==0.25.0

pip install --no-cache-dir --quiet \
    "transformers==5.5.0" \
    "accelerate==1.13.0" \
    "bitsandbytes==0.49.2" \
    "peft==0.19.1" \
    "trl==0.24.0" \
    "datasets==4.3.0" \
    "huggingface_hub==1.12.2" \
    "hf_transfer==0.1.9" \
    "sentencepiece" "protobuf" "pillow" "pydantic==2.13.3" \
    "tyro==1.0.13" "msgspec==0.21.1" "diffusers==0.37.1" \
    "torchao==0.17.0" "xformers==0.0.35" "cut_cross_entropy==25.1.1"

# MLflow installed separately so its resolver doesn't fight datasets==4.3.0 pyarrow pin
pip install --no-cache-dir --quiet "mlflow-skinny>=2.18,<4"

pip install --no-cache-dir --quiet \
    "unsloth==2026.4.8" "unsloth_zoo==2026.4.9"

python - <<'PY'
import torch, transformers, unsloth, bitsandbytes, peft, trl
print(f"torch {torch.__version__} cuda={torch.cuda.is_available()} dev={torch.cuda.get_device_name(0)}")
print(f"transformers {transformers.__version__}  unsloth {unsloth.__version__}  bnb {bitsandbytes.__version__}")
PY

# 3. model (skip if already cached)
echo "[3/5] Checking model cache"
mkdir -p "$HF_CACHE/hub"
if ls $MODEL_DIR_GLOB/model-00002-of-00002.safetensors >/dev/null 2>&1; then
    SNAP=$(ls -d $MODEL_DIR_GLOB | head -1)
    echo "    model already at $SNAP"
else
    echo "    downloading $MODEL_REPO (~49 GB; HF_HUB_ENABLE_HF_TRANSFER=0 to avoid mid-stream resets)"
    HF_HOME="$HF_CACHE" HF_HUB_ENABLE_HF_TRANSFER=0 python - <<PY
from huggingface_hub import snapshot_download
p = snapshot_download(
    repo_id="$MODEL_REPO",
    cache_dir="$HF_CACHE/hub",
    max_workers=4,
    allow_patterns=["*.json","*.safetensors","*.model","tokenizer*","*.txt"],
)
print("PATH:", p)
PY
    SNAP=$(ls -d $MODEL_DIR_GLOB | head -1)
fi
echo "    SNAP=$SNAP"

# 4. write training script (idempotent overwrite)
echo "[4/5] Writing training script"
mkdir -p "$TRAIN_DIR"
cat > "$TRAIN_DIR/kira_train.py" <<PY
#!/usr/bin/env python3
"""Kira QLoRA fine-tune - Gemma 4 26B-A4B-it (MoE) on A40 46GB.

Loads the bf16 source and quantizes to nf4 on the fly. The nf4 26B model is
~13 GB, so on A40 it fits entirely on the GPU and no CPU offload is needed.
"""
import os
os.environ["HF_HOME"] = "$HF_CACHE"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import unsloth  # MUST be first
from unsloth import FastLanguageModel, is_bfloat16_supported

import json, shutil, torch
from datasets import Dataset
from trl import SFTTrainer, SFTConfig
from bitsandbytes.nn import Params4bit as _P4b
from transformers import BitsAndBytesConfig as _BnbCfg

# Patch 1: transformers 5.5 passes _is_hf_initialized to Params4bit; bnb 0.49 rejects it
_orig_p4b_new = _P4b.__new__
def _patched_p4b_new(cls, *args, **kwargs):
    kwargs.pop("_is_hf_initialized", None)
    return _orig_p4b_new(cls, *args, **kwargs)
_P4b.__new__ = _patched_p4b_new

# Patch 2: unsloth builds the BnB config internally; force two settings:
#   - bnb_4bit_use_double_quant=False: True triggers a meta-tensor crash in
#     QuantState.as_dict during accelerate dispatch.
#   - llm_int8_enable_fp32_cpu_offload=True: required because the bf16 source
#     (52 GB) exceeds 46 GB A40 VRAM during load, so weights stream through CPU
#     before being quantized to nf4 in-place.
_orig_bnb_init = _BnbCfg.__init__
def _patched_bnb_init(self, *args, **kwargs):
    kwargs["bnb_4bit_use_double_quant"] = False
    kwargs["llm_int8_enable_fp32_cpu_offload"] = True
    _orig_bnb_init(self, *args, **kwargs)
_BnbCfg.__init__ = _patched_bnb_init

MODEL_PATH = "$SNAP"
DATA_DIR   = "$TRAIN_DIR/data/ft"
OUTPUT_DIR = "$TRAIN_DIR/kira_out"
FINAL_DIR  = "$TRAIN_DIR/kira_adapter"
LOG_DIR    = "$TRAIN_DIR/kira_logs"
TOKEN_CACHE = "$TRAIN_DIR/tokenized_cache"
MAX_SEQ    = 1024
NUM_PROC   = 16

# Stream bf16 source through CPU during load (bf16 52 GB > 46 GB VRAM); after
# quantization the nf4 model is ~13 GB and we redispatch entirely to GPU.
print("Loading model (nf4, CPU-streamed during load)...", flush=True)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name      = MODEL_PATH,
    max_seq_length  = MAX_SEQ,
    dtype           = None,
    load_in_4bit    = True,
    full_finetuning = False,
    max_memory      = {0: "40GiB", "cpu": "300GiB"},
)
print(f"  GPU memory after load: {torch.cuda.memory_allocated()/1e9:.1f} GB", flush=True)

# After load, some modules may be on CPU. Redispatch entirely to GPU 0 so the
# trainer accepts it (nf4 26B is ~13 GB, fits easily on 46 GB A40).
if hasattr(model, "hf_device_map"):
    cpu_count = sum(1 for v in model.hf_device_map.values() if str(v) == "cpu")
    if cpu_count > 0:
        print(f"  {cpu_count} modules on CPU; redispatching to GPU 0...", flush=True)
        from accelerate import dispatch_model
        new_dm = {k: 0 for k in model.hf_device_map}
        model = dispatch_model(model, device_map=new_dm)
        torch.cuda.empty_cache()
        print(f"  GPU memory after redispatch: {torch.cuda.memory_allocated()/1e9:.1f} GB", flush=True)

model = FastLanguageModel.get_peft_model(
    model,
    r              = 16,
    lora_alpha     = 32,
    lora_dropout   = 0.0,
    bias           = "none",
    target_modules = ["q_proj","k_proj","v_proj","o_proj",
                      "gate_proj","up_proj","down_proj"],
    use_gradient_checkpointing = "unsloth",
    random_state   = 3407,
)

def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]

SYSTEM_PROMPT = (
    "You are Kira, a contract review assistant. Given a clause and its surrounding context, "
    "identify the issue type, assess severity, explain what is wrong, and describe the worst-case "
    "consequence. Respond in strict JSON with keys: issue_type, severity, severity_rationale, "
    "what_is_wrong, worst_case, evidence_span."
)

def build_user_msg(ex):
    parts = []
    if ex.get("clause_type"):
        parts.append(f"Clause type: {ex['clause_type']}")
    if ex.get("left_context"):
        parts.append(f"Left context:\n{ex['left_context']}")
    parts.append(f"Clause:\n{ex.get('clause_text','')}")
    if ex.get("right_context"):
        parts.append(f"Right context:\n{ex['right_context']}")
    if ex.get("cuad_question"):
        parts.append(f"Question: {ex['cuad_question']}")
    return "\n\n".join(parts)

def build_assistant_msg(ex):
    out = {
        "issue_type": ex.get("ds_issue_type"),
        "severity": ex.get("ds_severity"),
        "severity_rationale": ex.get("ds_severity_rationale"),
        "what_is_wrong": ex.get("ds_what_is_wrong"),
        "worst_case": ex.get("ds_worst_case"),
        "evidence_span": ex.get("ds_evidence_span"),
    }
    return json.dumps(out, ensure_ascii=False)

def format_sample(ex):
    if "messages" in ex:
        msgs = ex["messages"]
    else:
        msgs = [
            {"role": "system",    "content": SYSTEM_PROMPT},
            {"role": "user",      "content": build_user_msg(ex)},
            {"role": "assistant", "content": build_assistant_msg(ex)},
        ]
    return tokenizer.apply_chat_template(
        msgs, tokenize=False, add_generation_prompt=False,
    )

print("Loading data...", flush=True)
if os.path.isdir(TOKEN_CACHE + "/train") and os.path.isdir(TOKEN_CACHE + "/val"):
    train_data = Dataset.load_from_disk(TOKEN_CACHE + "/train")
    val_data   = Dataset.load_from_disk(TOKEN_CACHE + "/val")
    print("    loaded from token cache", flush=True)
else:
    train_data = Dataset.from_list([{"text": format_sample(x)} for x in load_jsonl(DATA_DIR + "/train.jsonl")])
    val_data   = Dataset.from_list([{"text": format_sample(x)} for x in load_jsonl(DATA_DIR + "/val.jsonl")])
    os.makedirs(TOKEN_CACHE, exist_ok=True)
    train_data.save_to_disk(TOKEN_CACHE + "/train")
    val_data.save_to_disk(TOKEN_CACHE + "/val")
print(f"Train: {len(train_data)}  Val: {len(val_data)}", flush=True)

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

trainer = SFTTrainer(
    model         = model,
    tokenizer     = tokenizer,
    train_dataset = train_data,
    eval_dataset  = val_data,
    args = SFTConfig(
        output_dir                  = OUTPUT_DIR,
        num_train_epochs            = 1,
        per_device_train_batch_size = 4,
        gradient_accumulation_steps = 4,
        warmup_ratio                = 0.03,
        learning_rate               = 2e-4,
        lr_scheduler_type           = "cosine",
        bf16                        = is_bfloat16_supported(),
        fp16                        = not is_bfloat16_supported(),
        optim                       = "adamw_8bit",
        weight_decay                = 0.01,
        logging_steps               = 10,
        eval_strategy               = "steps",
        eval_steps                  = 250,
        save_strategy               = "steps",
        save_steps                  = 250,
        save_total_limit            = 3,
        load_best_model_at_end      = True,
        metric_for_best_model       = "eval_loss",
        greater_is_better           = False,
        logging_dir                 = LOG_DIR,
        dataset_text_field          = "text",
        max_seq_length              = MAX_SEQ,
        packing                     = False,
        seed                        = 3407,
        dataset_num_proc            = NUM_PROC,
        report_to                   = ["mlflow"],
        run_name                    = "kira-gemma4-26b-a4b-qlora",
    ),
)

print("Starting training...", flush=True)
trainer.train()

print("Saving adapter...", flush=True)
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
os.makedirs(FINAL_DIR, exist_ok=True)
shutil.copytree(OUTPUT_DIR, FINAL_DIR, dirs_exist_ok=True)
print(f"Done. Adapter at {FINAL_DIR}", flush=True)
PY

# 5. write run wrapper
echo "[5/5] Writing run wrapper at /tmp/run_train.sh"
cat > /tmp/run_train.sh <<BASH
#!/bin/bash
set -o pipefail
exec > $TRAIN_DIR/train.log 2>&1
source /root/kira_env/bin/activate
export HF_HOME=$HF_CACHE
export TRANSFORMERS_OFFLINE=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export MLFLOW_TRACKING_URI=file://$TRAIN_DIR/mlruns
export MLFLOW_EXPERIMENT_NAME=kira-qlora
echo "=== START \$(date) ==="
cd $TRAIN_DIR
python kira_train.py
RC=\$?
echo "=== END \$(date) RC=\$RC ==="
exit \$RC
BASH
chmod +x /tmp/run_train.sh

echo "=== Bootstrap done $(date) ==="
echo ""
echo "Start training with: nohup bash /tmp/run_train.sh > /dev/null 2>&1 &"
echo "Monitor with:        tail -f $TRAIN_DIR/train.log"
