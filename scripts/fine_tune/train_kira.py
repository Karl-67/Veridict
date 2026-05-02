#!/usr/bin/env python3
"""
train_kira.py — QLoRA fine-tune of gemma-4-26B-A4B-it.

Uses BitsAndBytes 4-bit runtime quantization (NF4) + LoRA adapters.
The BF16 model shard is loaded sequentially via low_cpu_mem_usage=False
to avoid the 484 MiB parallel-materialization peak in transformers 5.5.0.
Falls back automatically to older loading path.
"""

import os, gc, json, logging
from pathlib import Path

HF_HOME     = "/tmp/hf_cache"
DATA_DIR    = Path("/workspace/verdict_training/data")
ADAPTER_DIR = Path("/workspace/verdict_training/kira_adapter")
OUTPUT_DIR  = Path("/workspace/verdict_training/output")

os.environ["HF_HOME"]                    = HF_HOME
os.environ["TRANSFORMERS_CACHE"]         = HF_HOME
os.environ["HF_DATASETS_CACHE"]          = "/dev/shm/hf_datasets_cache"
os.environ["TOKENIZERS_PARALLELISM"]     = "false"
os.environ["PYTORCH_CUDA_ALLOC_CONF"]    = "expandable_segments:True"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["HF_HUB_DISABLE_XET"]        = "1"

Path("/dev/shm/hf_datasets_cache").mkdir(parents=True, exist_ok=True)

LOG_FILE = "/workspace/verdict_training/kira_training.log"
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

import torch
import torch.nn as nn

if not hasattr(nn.Module, "set_submodule"):
    def _set_submodule(self, target, module):
        parts = target.split(".")
        parent = self
        for part in parts[:-1]:
            parent = getattr(parent, part)
        setattr(parent, parts[-1], module)
    nn.Module.set_submodule = _set_submodule

MODEL_ID       = "unsloth/gemma-4-26B-A4B-it"
LORA_R         = 16
LORA_ALPHA     = 32
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj"]
MAX_SEQ_LEN    = 512
BATCH_SIZE     = 1
GRAD_ACCUM     = 8
EPOCHS         = 3
LR             = 2e-4


try:
    from scripts.llmops_mlflow import dataset_version, enabled as mlflow_enabled, log_artifact, log_metrics, log_params, sha256_text, start_run
except Exception:
    def mlflow_enabled():
        return False
    def dataset_version(paths):
        return "unavailable"
    def sha256_text(value):
        return "unavailable"
    def log_params(params):
        return None
    def log_metrics(metrics, prefix=""):
        return None
    def log_artifact(path, artifact_path=None):
        return None
    def start_run(run_name, tags=None, nested=False):
        from contextlib import nullcontext
        return nullcontext(None)


def _split_paths(split):
    return [DATA_DIR / "ft" / (split + ".jsonl"), DATA_DIR / (split + ".jsonl")]


def _existing_split_path(split):
    for path in _split_paths(split):
        if path.exists():
            return path
    return _split_paths(split)[0]


def load_rows(split):
    for p in _split_paths(split):
        if p.exists():
            rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
            log.info("Loaded %d %s rows from %s", len(rows), split, p)
            return rows
    raise FileNotFoundError("No data for split: " + split)


def to_gemma_text(row):
    role_map = {"system": "system", "user": "user", "assistant": "model"}
    parts = []
    for msg in row.get("messages", []):
        tag = role_map.get(msg["role"], msg["role"])
        parts.append(f"<start_of_turn>{tag}\n{msg['content']}<end_of_turn>")
    return "\n".join(parts) + "\n"


def fix_split_cache():
    """
    hf_hub_download(cache_dir="/tmp/hf_cache") writes to /tmp/hf_cache/models--*/
    but transformers via HF_HOME="/tmp/hf_cache" expects  /tmp/hf_cache/hub/models--*/
    This merges them by hardlinking any missing blobs into the hub tree.
    """
    import shutil
    base = Path(HF_HOME)
    hub_base  = base / "hub"
    flat_base = base   # hf_hub_download without hub subdir

    repo_slug = "models--unsloth--gemma-4-26B-A4B-it"
    hub_blobs  = hub_base  / repo_slug / "blobs"
    flat_blobs = flat_base / repo_slug / "blobs"

    if not flat_blobs.exists():
        return  # nothing to merge

    hub_blobs.mkdir(parents=True, exist_ok=True)
    for src in flat_blobs.iterdir():
        dst = hub_blobs / src.name
        if not dst.exists():
            try:
                os.link(src, dst)   # hardlink — zero extra disk
                log.info("Linked shard blob %s into hub cache", src.name[:16])
            except OSError:
                shutil.copy2(src, dst)
                log.info("Copied shard blob %s into hub cache", src.name[:16])

    # Also fix the snapshot symlinks so shard-00001 resolves correctly
    flat_snap = flat_base / repo_slug / "snapshots"
    hub_snap  = hub_base  / repo_slug / "snapshots"
    if flat_snap.exists():
        for rev in flat_snap.iterdir():
            hub_rev = hub_snap / rev.name
            hub_rev.mkdir(parents=True, exist_ok=True)
            for f in rev.iterdir():
                target = hub_rev / f.name
                if not target.exists():
                    blob_name = f.resolve().name if f.is_symlink() else f.name
                    link_dst = Path("../../blobs") / blob_name
                    target.symlink_to(link_dst)
                    log.info("Symlinked snapshot file %s", f.name)


def main():
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, TaskType, prepare_model_for_kbit_training
    from trl import SFTTrainer, SFTConfig

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ADAPTER_DIR.mkdir(parents=True, exist_ok=True)

    train_path = _existing_split_path("train")
    val_path = _existing_split_path("val")
    mlflow_context = start_run(
        "kira-sft-qlora",
        tags={"llmops.phase": "training", "role": "kira", "training.kind": "sft_qlora"},
    )
    mlflow_context.__enter__()
    log_params(
        {
            "model": MODEL_ID,
            "adapter_type": "lora",
            "dataset_train_path": str(train_path),
            "dataset_val_path": str(val_path),
            "data_version": dataset_version([train_path, val_path]),
            "prompt_version": sha256_text("gemma_chat_messages_v1"),
            "lora_r": LORA_R,
            "lora_alpha": LORA_ALPHA,
            "target_modules": TARGET_MODULES,
            "max_seq_len": MAX_SEQ_LEN,
            "batch_size": BATCH_SIZE,
            "gradient_accumulation_steps": GRAD_ACCUM,
            "epochs": EPOCHS,
            "learning_rate": LR,
        }
    )

    log.info("Fixing split HF cache layout if needed...")
    fix_split_cache()

    hf_token = os.getenv("HF_TOKEN") or None

    log.info("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=hf_token)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        llm_int8_enable_fp32_cpu_offload=True,
    )

    log.info("Loading model with BnB 4-bit (capped GPU → CPU overflow)...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=bnb_cfg,
        device_map="auto",
        max_memory={0: "22000MiB", "cpu": "460000MiB"},
        token=hf_token,
        torch_dtype=torch.bfloat16,
        attn_implementation="eager",
    )
    model.config.use_cache = False

    log.info("GPU after load: %.1f GB", torch.cuda.memory_allocated() / 1e9)

    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    lora_cfg = LoraConfig(
        r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=0.05,
        target_modules=TARGET_MODULES, bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()

    log.info("Building datasets...")
    train_rows = load_rows("train")
    val_rows = load_rows("val")
    log_params({"train_row_count": len(train_rows), "val_row_count": len(val_rows)})
    train_ds = Dataset.from_list([{"text": to_gemma_text(r)} for r in train_rows])
    val_ds   = Dataset.from_list([{"text": to_gemma_text(r)} for r in val_rows])

    sft_cfg = SFTConfig(
        output_dir=str(OUTPUT_DIR),
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LR,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=True, fp16=False,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        report_to=["mlflow"] if mlflow_enabled() else "none",
        gradient_checkpointing=True,
        dataloader_num_workers=0,
        max_seq_length=MAX_SEQ_LEN,
        dataset_text_field="text",
        packing=False,
    )

    trainer = SFTTrainer(
        model=model, args=sft_cfg,
        train_dataset=train_ds, eval_dataset=val_ds,
        processing_class=tokenizer,
    )

    log.info("=== TRAINING START ===")
    train_output = trainer.train()
    log_metrics(train_output.metrics, prefix="train.")
    eval_metrics = trainer.evaluate()
    log_metrics(eval_metrics, prefix="eval.")

    log.info("Saving adapter -> %s", ADAPTER_DIR)
    trainer.model.save_pretrained(str(ADAPTER_DIR))
    tokenizer.save_pretrained(str(ADAPTER_DIR))
    log_artifact(LOG_FILE, artifact_path="logs")
    log.info("=== DONE ===")
    mlflow_context.__exit__(None, None, None)


if __name__ == "__main__":
    main()
