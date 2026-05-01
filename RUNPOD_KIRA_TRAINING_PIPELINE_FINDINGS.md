# RunPod Kira Training, Pipeline, and Findings

Date captured: 2026-04-30  
RunPod SSH target inspected: `v7oxa8ubddgilb-64410d5a@ssh.runpod.io`  
Primary pod workspace: `/workspace/kira_gemma4_training`

This file records what we did on the RunPod, how it fits into the Verdict pipeline, what we found while training, and why the major decisions were made.

## Executive Summary

We moved Kira fine-tuning onto RunPod so the project could train a role-specific contract-risk model instead of relying only on generic local inference. The active product architecture remains:

```text
input/upload -> Harvey RAG -> Kira finds problems -> Admin consensus -> output
```

The RunPod work focused on the Kira lane:

1. Build a contract-risk instruction dataset from CUAD and MAUD.
2. Use DeepSeek distillation fields as the supervised target for risk classification, severity, rationale, worst case, and evidence span.
3. Fine-tune `unsloth/gemma-4-26B-A4B-it` with QLoRA on the prepared Kira data.
4. Feed the resulting Kira adapter into the Verdict run pipeline later, behind the same provider boundary.

At inspection time, training was still running. The one-epoch training pass had reached `477/477` steps, and the process was in evaluation over `1332` eval steps. The final adapter directory existed but was still empty because `kira_train.py` saves the adapter only after evaluation completes.

## Why We Did This

Kira's role is not to retrieve internal policy evidence. Harvey owns RAG and evidence retrieval. Kira owns problem-finding from contract text and structured compliance knowledge. That separation matters because it prevents Kira from inventing unsupported RAG citations and keeps the active run topology aligned with the architecture:

```text
create_run
-> ingest_pdf
-> parse_ocr_normalize
-> clause_index
-> harvey_context_load
-> kira_review_block
-> admin_merge
-> awaiting_human_review
-> finalized
```

The fine-tuning goal was therefore narrow: make Kira better at identifying contract problems, severity, rationale, worst-case impact, and evidence spans from clause text. We did not train a monolithic final reviewer/admin model because the active architecture no longer has admin/final reviewer agents in the review lane. Admin is merge-only.

## Dataset Pipeline

The intended Kira training pipeline is documented in `KIRA_PIPELINE.md` and follows this shape:

```text
scripts/download_datasets.py
-> scripts/build_kira_dataset.py
-> scripts/distill/label_with_deepseek.py
-> scripts/distill/export_kira.py
-> RunPod QLoRA training
```

The source datasets were:

- CUAD / Atticus: contract clause spans and legal QA-style annotations.
- MAUD: M&A agreement passages with attorney-verified answers.

The exported fine-tuning data on the RunPod was in:

```text
/workspace/kira_gemma4_training/data/ft/
```

Observed files and counts:

| Split | Path | Rows | Size |
|---|---:|---:|---:|
| Train | `data/ft/train.jsonl` | 22,858 | 626 MB |
| Validation | `data/ft/val.jsonl` | 5,327 | 140 MB |
| Test | `data/ft/test.jsonl` | 5,273 | 111 MB |
| Total |  | 33,458 | 875 MB |

Each row is a chat-format training example. The system prompt frames Kira as a contract review assistant. The user message provides clause type, left/right context, clause text, and sometimes the original CUAD question. The assistant target is strict JSON with:

```json
{
  "issue_type": "...",
  "severity": "...",
  "severity_rationale": "...",
  "what_is_wrong": "...",
  "worst_case": "...",
  "evidence_span": "..."
}
```

## Why We Used Distillation

CUAD and MAUD provide strong legal source material, but they do not directly match the exact JSON shape Kira must produce in Verdict. DeepSeek labeling bridged that gap by adding:

- `ds_issue_type`
- `ds_severity`
- `ds_severity_rationale`
- `ds_what_is_wrong`
- `ds_worst_case`
- `ds_evidence_span`

That gave the supervised trainer an output format close to the production Kira schema. The reason for doing this before fine-tuning was practical: supervised fine-tuning needs consistent assistant targets, and the target should match the exact behavior we want from the role agent.

## RunPod Environment

Observed pod details:

| Item | Value |
|---|---|
| Container hostname | `5fad3216fa77` |
| User inside pod | `root` |
| Workspace | `/workspace/kira_gemma4_training` |
| Model cache | `/workspace/hf_cache` |
| Python environment | `/root/kira_env` |
| GPU | NVIDIA A100-SXM4-80GB |
| GPU memory at inspection | 54,513 MiB used / 81,920 MiB total |
| GPU utilization at inspection | 46% |

Key RunPod paths:

```text
/workspace/kira_gemma4_training/kira_train.py
/workspace/kira_gemma4_training/load_test.py
/workspace/kira_gemma4_training/train.log
/workspace/kira_gemma4_training/tokenized_cache/
/workspace/kira_gemma4_training/kira_out/
/workspace/kira_gemma4_training/kira_adapter/
/workspace/hf_cache/hub/models--unsloth--gemma-4-26B-A4B-it/
```

## Model and Training Setup

The model selected was:

```text
unsloth/gemma-4-26B-A4B-it
```

The local snapshot path used by the training script was:

```text
/workspace/hf_cache/hub/models--unsloth--gemma-4-26B-A4B-it/snapshots/cd98c13581a9d4ad061cb85d983232ca4edb1343
```

Training configuration observed in `kira_train.py`:

| Setting | Value |
|---|---:|
| Max sequence length | 1024 |
| QLoRA mode | `load_in_4bit=True` |
| Full fine-tuning | `False` |
| LoRA rank | 16 |
| LoRA alpha | 32 |
| LoRA dropout | 0.0 |
| Target modules | `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj` |
| Gradient checkpointing | `unsloth` |
| Epochs | 1 |
| Per-device train batch size | 6 |
| Gradient accumulation | 8 |
| Effective batch size | 48 |
| Learning rate | `2e-4` |
| Eval strategy | steps |
| Eval steps | 500 |
| Save strategy | steps |
| Save steps | 500 |
| Save total limit | 3 |
| Best model metric | `eval_loss`, lower is better |
| Token cache | `/workspace/kira_gemma4_training/tokenized_cache` |

Unsloth detected the model as an MoE model with 128 experts and enabled LoRA on MoE parameters:

```text
experts.gate_up_proj
experts.down_proj
```

The run trained:

```text
505,429,248 trainable parameters out of 26,311,363,120
```

That is about 1.92% of the model parameters.

## Training Status Observed

The active process was:

```text
python kira_train.py
```

The training log showed:

```text
Num examples = 22,858
Num Epochs = 1
Total steps = 477
Batch size per device = 6
Gradient accumulation steps = 8
Total batch size = 48
```

The full training pass reached:

```text
477/477
```

Then evaluation began:

```text
0/1332 eval steps
...
122/1332 eval steps
```

The latest inspected state was still in evaluation. Because of that, these directories were still empty at inspection time:

```text
/workspace/kira_gemma4_training/kira_adapter
/workspace/kira_gemma4_training/kira_out
/workspace/kira_gemma4_training/kira_logs
```

This is expected for the current script because it saves only after `trainer.train()` finishes and then runs:

```python
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
shutil.copytree(OUTPUT_DIR, FINAL_DIR, dirs_exist_ok=True)
```

## Training Findings

### 1. The model fit started high and dropped quickly

Observed logged losses:

| Approx epoch | Loss |
|---:|---:|
| 0.021 | 6.468 |
| 0.042 | 2.250 |
| 0.063 | 1.504 |
| 0.105 | 1.162 |
| 0.210 | 0.9615 |
| 0.315 | 0.8431 |
| 0.504 | 0.7489 |
| 0.672 | 0.7111 |
| 0.861 | 0.6686 |
| 0.987 | 0.7137 |

The useful finding is that the model quickly learned the JSON/task pattern and then settled around the high `0.6` to low `0.7` range by the end of the epoch. Final judgment still depends on eval loss and structured-output checks after evaluation completes.

### 2. Evaluation is the blocker for claiming completion

The train pass completed, but the process was still evaluating. We should not call the adapter complete until:

- evaluation finishes,
- `kira_out/` contains adapter files,
- `kira_adapter/` contains the copied final adapter,
- `train.log` includes the final save message.

### 3. The A100 pod removed earlier memory pressure

Earlier runbook notes were written for an RTX A5000 24GB setup, where CPU offload, smaller sequence lengths, and quota pressure were major concerns. The current pod has an A100 80GB, and `load_in_4bit=True` was enough to keep training moving with `MAX_SEQ=1024`, batch size 6, and gradient accumulation 8.

### 4. Token caching mattered

The run used:

```text
/workspace/kira_gemma4_training/tokenized_cache
```

The log confirmed:

```text
Loaded token cache.
```

This avoided repeating the expensive tokenization pass every time training restarted.

### 5. The adapter is intentionally role-specific

The output should be treated as a Kira problem-finding adapter only. It should not be used as Harvey RAG, Admin merge, or final reviewer logic. That matches the active architecture where:

- Harvey retrieves evidence.
- Kira identifies problems.
- Admin merges findings.
- Human review gates finalization.

## Pipeline Findings

The most important architecture finding is that training must serve the run-based pipeline, not replace it.

The active topology is:

```text
create_run
-> ingest_pdf
-> parse_ocr_normalize
-> clause_index
-> harvey_context_load
-> kira_review_block
-> admin_merge
-> awaiting_human_review
-> finalized
```

Legacy stages must stay out of new runs:

```text
final_review_block
harvey_review_block
kira_context_load
```

The reason is architectural clarity. Harvey-only RAG is enforced at the service layer. Kira findings must not contain RAG citations. Harvey citations must resolve to the run retrieval trace. Kira should use structured compliance corpora and clause text, then Admin merges the branches into a human-reviewable result.

## Why the Main Decisions Were Made

| Decision | Why |
|---|---|
| Use Kira-specific fine-tuning | Kira has a narrow job: problem finding. A role-specific adapter is easier to evaluate and safer to integrate than a general legal model. |
| Use CUAD + MAUD | They provide real contract clauses, clause categories, and attorney-reviewed M&A examples. |
| Add DeepSeek labels | The raw datasets do not directly produce Verdict's target JSON schema. Distillation created the missing severity, rationale, worst-case, and evidence fields. |
| Use Gemma 4 26B-A4B | MoE gives larger model capacity with lower active parameter cost than a dense 26B model. |
| Use QLoRA | It trains only adapter weights, making the run feasible on rented GPU hardware without full model fine-tuning. |
| Use Unsloth | It reduces training overhead and handles MoE LoRA targeting. |
| Cache tokenized data | Tokenization is expensive and had previously caused responsiveness problems. Caching makes restarts practical. |
| Keep Admin merge-only | The active product architecture needs a deterministic merge/adjudication lane, not another hallucination-prone reviewer. |
| Keep human review mandatory | Legal contract review needs a human gate before final output. Training improves suggestions, not authority. |

## Open Items

1. Wait for the active RunPod evaluation to finish.
2. Confirm `kira_adapter/` contains adapter files.
3. Capture final `eval_loss` and any save message from `train.log`.
4. Run a small inference smoke test against the final adapter.
5. Add structured eval beyond token loss:
   - JSON parse rate.
   - required-field completeness.
   - issue-type accuracy.
   - evidence-span overlap.
   - empty-findings rate.
6. Decide how the adapter will be served locally or in deployment:
   - vLLM,
   - Ollama-compatible path,
   - direct Transformers/PEFT service.
7. Wire the served adapter behind the existing provider boundary without changing the run topology.

## Commands Used for Verification

Read-only commands run on the pod included:

```bash
ls -la /workspace
ls -la /workspace/kira_gemma4_training
wc -l data/ft/train.jsonl data/ft/val.jsonl data/ft/test.jsonl
tail -80 train.log
ps aux | grep kira_train | grep -v grep
nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader
grep -nE "MODEL|DATA_DIR|OUTPUT_DIR|FINAL_DIR|MAX_SEQ|per_device|gradient_accumulation|learning_rate|num_train_epochs|save|eval|target_modules|r=|lora_alpha|tokenized_cache|packing" kira_train.py
```

## Current Bottom Line

The RunPod work successfully got Kira QLoRA training running on the prepared dataset and completed the train pass. At the time of this note, evaluation was still running and the adapter had not yet been saved. The next concrete milestone is to wait for evaluation completion, verify the adapter files, and run a smoke test before integrating the model into Verdict's Kira review block.
