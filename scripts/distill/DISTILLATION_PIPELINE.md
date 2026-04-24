# Distillation Pipeline

Knowledge distillation pipeline for Veridict. A teacher model (GPT via Codex OAuth)
labels curated legal contract data; a student model (Gemma 4) is then fine-tuned on
those labels.

---

## Overview

```
Curated datasets
      │
      ▼
  [1] build       build_batches.py
      │  One GPT call per full contract (reviewer)
      │  One GPT call per (passage, question) pair (MAUD)
      │  One GPT call per NLI pair (validator)
      │  One GPT call per full SEC contract
      ▼
  data/distillation/batches/*.jsonl   +   manifest.json
      │
      ▼
  [2] calls       run_calls.py
      │  Async execution via ChatGPT Codex OAuth backend
      │  Per-request checkpointing → safe to stop and resume
      ▼
  data/distillation/results/*_results.jsonl
      │
      ▼
  [3] parse       parse_results.py
      │  Expands contract-level finding arrays → per-clause rows
      │  Annotates MAUD, validator, SEC rows
      ▼
  data/distillation/annotated/*_annotated.jsonl
      │
      ▼
  [4] export      export_gemma.py
      │  Converts annotated rows → chat-format training turns
      │  Splits into train / val / test
      ▼
  data/distillation/gemma/{train,val,test}.jsonl
      │
      ▼
  [5] train       train_gemma.py
      │  LoRA fine-tune on Gemma 4 using TRL SFTTrainer
      ▼
  data/distillation/model/   (merged weights)
```

---

## Datasets

| Dataset | Source files | GPT call unit | Training task |
|---------|-------------|---------------|---------------|
| Reviewer (Dataset A) | `data/curated/dataset_a/reviewer_{train,val,test}.jsonl` | One call per **full contract** covering all its flagged clauses | Contract clause risk review |
| Validator (Dataset B) | `data/curated/dataset_b/validator_{train,val,test}.jsonl` | One call per NLI **(premise, hypothesis)** pair | NLI / finding validation |
| MAUD (Dataset C) | `data/curated/dataset_c/maud_{train,val,test}.jsonl` | One call per unique **(passage, question)** pair | M&A deal-point risk analysis |
| SEC contracts | `data/material/sec_contracts.parquet` | One call per **full contract** (hard-skip > 14k tokens) | Open-ended contract risk scan |
| LEDGAR | RL pool only | **Not sent to GPT** — no full contract available | Auxiliary weak-label data for RLHF |

### Contract-level labeling policy

Reviewer and SEC calls always send the **full contract text** to GPT — never partial
chunks. If a contract exceeds `LARGE_CONTRACT_TOKENS` (~3,500 estimated input tokens)
it is written to a `*_large_batch_*` file and processed last to preserve rate-limit
budget for smaller contracts. Contracts above `SEC_HARD_SKIP_TOKENS` (14,000 tokens)
are skipped entirely and can be labeled in a later session once the full model
supports a longer context window.

---

## Step-by-step: How to Run

### Prerequisites

```bash
pip install httpx pandas pyarrow
# For training only:
pip install transformers trl peft accelerate bitsandbytes datasets torch
```

Authenticate once with Codex (required for `calls` step):

```bash
codex   # complete OAuth login — writes ~/.codex/auth.json
```

### 1. Build batch files

```bash
python -m scripts.run_distill build
```

Reads curated JSONL files and the CUAD contract JSON, writes batch input files to
`data/distillation/batches/`. Pass `--dry-run` to estimate token counts without
writing:

```bash
python -m scripts.run_distill build --dry-run
# Or point to a different contracts source:
python -m scripts.run_distill build --contracts-path data/atticus/CUAD_v1.json
```

Output files:

```
data/distillation/batches/
  reviewer_batch_0.jsonl          # normal-size contracts
  reviewer_large_batch_0.jsonl    # large contracts (run last)
  validator_batch_0.jsonl
  maud_batch_0.jsonl
  sec_batch_0.jsonl
  manifest.json                   # maps custom_id → clause metadata
```

### 2. Run GPT calls

```bash
python -m scripts.run_distill calls
```

Executes all batch files against the ChatGPT Codex backend using your OAuth token.
Results are written per-request to `data/distillation/results/` — the run is fully
resumable; already-completed requests are skipped automatically.

**Rate-limit workflow** — if you hit the daily limit mid-run:

```bash
# First session — process up to 500 requests then stop
python -m scripts.run_distill calls --max-new 500

# Check progress at any time
python -m scripts.run_distill calls --status

# Next session — picks up exactly where it left off
python -m scripts.run_distill calls --max-new 500
```

**Multi-account split** — if batch files were split across accounts:

```bash
python -m scripts.run_distill calls --account 1
python -m scripts.run_distill calls --account 2
python -m scripts.run_distill calls --account 3
```

**Custom auth file:**

```bash
python -m scripts.run_distill calls --auth-file /path/to/auth.json
```

### 3. Parse results

```bash
python -m scripts.run_distill parse
```

Merges GPT responses back into the original curated rows:

- **Reviewer**: uses `contract_clause_map` from `manifest.json` to expand each
  contract's finding array back to individual clause rows. Each finding carries:
  `risk_score` (1–10), `risk_analysis`, `false_positive_note`, `exploitability`,
  `severity`, `severity_confidence`, `recommendation`.
- **MAUD**: joins per `(passage, question)` hash. Each finding carries:
  `risk_owner`, `risk_score`, `risk_analysis`, `exploitability`, `severity`,
  `recommendation`.
- **Validator**: joins per `(premise, hypothesis)` hash. Each finding carries:
  `score` (0–5), `verdict` (retain/reject/uncertain), `reason`.
- **SEC**: open-ended per-contract scan; up to 5 highest-risk clauses returned.

Output: `data/distillation/annotated/*_annotated.jsonl`

### 4. Export fine-tuning data

```bash
python -m scripts.run_distill export
```

Converts annotated rows into chat-format training turns and writes them to
`data/distillation/gemma/`. Score-0 (boilerplate) reviewer rows are sampled at 15%
to avoid flooding the training set with trivial negatives.

Training turn format (reviewer):

```
system:    "You are Veridict, a specialized AI legal contract reviewer…"
user:      "Review this contract window and return clause-level findings:\n\n{clause_text}"
assistant: "Risk Score: 7/10\nSeverity: High\nCategory: Liability Exposure\n
            Risk Analysis: …\nFalse Positive Check: …\nExploitability: …\nRecommendation: …"
```

Training turn format (MAUD):

```
system:    "You are Veridict, a specialized AI legal contract reviewer focused on M&A…"
user:      "Analyze this merger agreement deal point:\n\nCategory: …\nQuestion: …\nPassage: …\nConfirmed Answer: …"
assistant: "Risk Owner: Buyer\nRisk Score: 8/10\nSeverity: High\nAnalysis: …\nExploitability: …\nRecommendation: …"
```

Output: `data/distillation/gemma/{train,val,test}.jsonl`

### 5. Fine-tune Gemma 4

```bash
python -m scripts.run_distill train
```

Runs LoRA fine-tuning via TRL's `SFTTrainer`. Key hyperparameters (all in
`config.py`):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `GEMMA_MODEL_ID` | `google/gemma-4-E4B` | HuggingFace model ID |
| `LORA_RANK` | 16 | LoRA rank |
| `LORA_ALPHA` | 32 | LoRA alpha |
| `TRAIN_EPOCHS` | 3 | Training epochs |
| `TRAIN_BATCH_SIZE` | 2 | Per-device batch size |
| `GRAD_ACCUM_STEPS` | 8 | Gradient accumulation (effective batch = 16) |
| `LEARNING_RATE` | 2e-4 | Learning rate |
| `MAX_SEQ_LENGTH` | 1024 | Token context window |

Override any of these from the command line:

```bash
python -m scripts.run_distill train --model google/gemma-4-26B-A4B-it
python -m scripts.run_distill train --epochs 1 --batch 1   # quick smoke test
python -m scripts.run_distill train --load-4bit            # QLoRA (less VRAM)
python -m scripts.run_distill train --no-lora              # full fine-tune
```

Output: `data/distillation/model/` (merged weights + tokenizer)

---

## Run Everything End-to-End

```bash
python -m scripts.run_distill all
```

Runs `build → calls → parse → export` in sequence. Does **not** run `train`
(fine-tuning is typically done separately on a GPU machine).

---

## File Layout

```
scripts/distill/
  config.py          — all hyperparameters and shared paths
  build_batches.py   — step 1: build GPT batch input files
  run_calls.py       — step 2: execute calls via Codex OAuth
  parse_results.py   — step 3: merge GPT annotations into curated rows
  export_gemma.py    — step 4: export chat-format training JSONL
  train_gemma.py     — step 5: LoRA fine-tune Gemma 4
  oauth.py           — OAuth token loading and refresh
  prompts.py         — all GPT system/user prompt templates

data/distillation/
  batches/           — step 1 output (batch JSONL + manifest)
  results/           — step 2 output (raw GPT responses + progress.json)
  annotated/         — step 3 output (curated rows with GPT fields merged in)
  gemma/             — step 4 output (train/val/test.jsonl for fine-tuning)
  checkpoints/       — step 5 per-epoch LoRA checkpoints
  model/             — step 5 final merged model weights
```

---

## Key Design Decisions

**One call per full contract, not per clause.**
Reviewer and SEC calls always include the full contract text. This gives GPT the
context it needs to catch cross-clause conflicts, defined-term risks, and
jurisdiction-specific issues that are invisible when evaluating clauses in isolation.

**Large contracts deferred, not chunked.**
Contracts above ~3,500 estimated input tokens are written to `*_large_batch_*` files
and processed in a later session. This ensures the rate-limit budget for a given
session is spent on as many contracts as possible. Contracts above 14,000 tokens
(~10,500 words) are skipped entirely for now.

**LEDGAR kept in RL pool only.**
LEDGAR rows have no associated full contract — only the isolated clause text. Sending
them through distillation would produce weak, context-free annotations. They are
retained as auxiliary weak-label data in `data/curated/rl_pool.jsonl` for future
RLHF/RLAIF use.

**Crash-safe resumption.**
`run_calls.py` writes each GPT response to disk immediately after it arrives. On
restart, already-completed `custom_id`s are loaded from the results file and skipped.
Errored responses are retried. The `--max-new N` flag lets you process a fixed number
of requests per session to stay within daily rate limits.

**Role-augmented rows deduplicated before labeling.**
`dataset_a` contains rows for multiple agent roles (reviewer, validator, etc.) that
share the same clause text and contract. `build_batches.py` deduplicates by
`(clause_text, contract_id)` hash before building requests — one GPT call covers all
role variants of the same clause. `parse_results.py` propagates the single finding
back to all matching rows.
