# Kira Fine-Tuning Pipeline

Kira is Gemma 4 26B fine-tuned as a legal contract risk analyst.
It trains on CUAD clause spans (with targeted review questions and GT spans) enriched by
DeepSeek severity labels, plus MAUD M&A passages anchored by attorney-verified answers.

---

## Architecture Overview

```
scripts/download_datasets.py          →  data/atticus/{cuad,cuad_clauses}.parquet
                                          data/maud/maud.parquet

scripts/build_kira_dataset.py         →  data/kira/raw/{train,val,test}.jsonl
                                          (CUAD + MAUD, document-level split, ±8-sentence context)

scripts/distill/label_with_deepseek.py →  data/kira/labeled/{train,val,test}.jsonl
                                          (DeepSeek adds severity, issue type, evidence span)

scripts/distill/export_kira.py        →  data/kira/ft/{train,val,test}.jsonl
                                          (balanced Gemma chat turns)

scripts/distill/train_gemma.py        →  data/kira/model/
                                          (LoRA fine-tune on Gemma 4 26B)
```

---

## Step 1 — Download datasets

```bash
python -m scripts.download_datasets
```

Downloads and builds:
- `data/atticus/cuad.parquet` — 500 contracts, 41 clause categories, QA format
- `data/atticus/cuad_clauses.parquet` — 13,823 clause spans with **full** contract context
- `data/maud/maud.parquet` — 152 merger agreements, 39k expert-annotated QA rows

If the parquet files already exist the script is a no-op, so it is safe to re-run.

---

## Step 2 — Build raw dataset

```bash
python -m scripts.build_kira_dataset
```

**What it does:**

| Dataset | Rows (raw) | Split method |
|---------|-----------|--------------|
| CUAD    | 8,748 (after dedup + wc ≥ 10) | Document-level 70/15/15 — same contract never crosses splits |
| MAUD    | 25,436 (wc 10–600) | Official document-level splits used directly |

**Output counts:**

| Split | CUAD | MAUD | Total |
|-------|------|------|-------|
| train | 6,244 | 16,698 | 22,942 |
| val   | 1,280 | 4,399  | 5,679  |
| test  | 1,224 | 4,339  | 5,563  |

**Per-row schema (CUAD rows):**
```json
{
  "id":                 "cuad_<sha1>",
  "source":             "cuad",
  "split":              "train",
  "contract_id":        "LIMEENERGYCO_09_09_1999-...",
  "clause_type":        "Governing Law",
  "clause_text":        "This Agreement shall be governed by...",
  "cuad_question":      "Highlight the parts (if any) related to \"Governing Law\"...",
  "ground_truth_spans": ["the laws of the State of Delaware"],
  "left_context":       "...(up to 8 sentences / 600 chars before clause)...",
  "right_context":      "...(up to 8 sentences / 600 chars after clause)...",
  "full_contract":      "...(complete contract text — DeepSeek fallback only)..."
}
```

**Per-row schema (MAUD rows):**
```json
{
  "id":            "maud_<id>",
  "source":        "maud",
  "split":         "train",
  "contract_id":   "contract_41",
  "clause_type":   "Type of Consideration",
  "maud_category": "General Information",
  "clause_text":   "Each Share... shall be cancelled and converted into...",
  "maud_question": "Type of Consideration-Answer",
  "maud_answer":   "All Cash",
  "left_context":  "",
  "right_context": "",
  "full_contract": ""
}
```

---

## Step 3 — Label with DeepSeek  ← start here for API labeling

> **This is where you need the DeepSeek API key.**

### 3a — Configure credentials

Add your key and model to `.env` in the project root:

```
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat        # or deepseek-reasoner — check deepseek.com for current model IDs
```

Source the file before running (or export manually):

```bash
# Linux / macOS
export $(grep -v '^#' .env | xargs)

# Windows PowerShell
Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } |
  ForEach-Object { $k,$v = $_ -split '=',2; [System.Environment]::SetEnvironmentVariable($k,$v) }

# Windows CMD
for /f "tokens=1,2 delims==" %a in (.env) do set %a=%b
```

### 3b — Dry run (always do this first)

Runs 5 rows from the train split, prints prompts and responses, **does not write any files**:

```bash
python -m scripts.distill.label_with_deepseek --dry-run
```

Check the output for:
- `ds_severity_rationale` cites actual clause language, not just the topic category
- `ds_evidence_valid: true` — the quoted span is a substring of `clause_text`
- JSON structure is well-formed

### 3c — Label all splits

```bash
# Label train (largest — run first)
python -m scripts.distill.label_with_deepseek --split train

# Then val and test
python -m scripts.distill.label_with_deepseek --split val
python -m scripts.distill.label_with_deepseek --split test

# Or all at once (sequential)
python -m scripts.distill.label_with_deepseek --split all
```

**Resume safety:** The labeler checkpoints every 500 rows by appending to the output file.
If interrupted, re-running the same command skips already-labeled row IDs automatically.

**Fallback calls:** DeepSeek signals `needs_full_contract: true` when the context window
is insufficient. The labeler then re-calls with the full contract prepended. Expect 5–15%
of CUAD rows to trigger this. MAUD rows never trigger it (no full contract available).

**Output** written to `data/kira/labeled/{train,val,test}.jsonl` with these additional fields:

| Field | Type | Description |
|-------|------|-------------|
| `ds_issue_type` | str or null | One of 13 issue types, or null if no material risk |
| `ds_severity` | str | `critical / high / medium / low` |
| `ds_severity_rationale` | str | 1 sentence citing actual clause language |
| `ds_what_is_wrong` | str or null | 2–3 sentences on the risk |
| `ds_worst_case` | str or null | 1 sentence worst realistic outcome |
| `ds_evidence_span` | str | Exact quoted text from the clause |
| `ds_evidence_valid` | bool | True if span is a substring of `clause_text` |
| `ds_used_full_contract` | bool | True if fallback call was made |
| `ds_labeled` | bool | False if the API call failed (row kept, skipped in export) |

**Quality targets:**
- `ds_labeled=False` rate < 2%
- `ds_used_full_contract=True` rate 5–15%

Failed rows are retained in the file with `ds_labeled=False, ds_error=<message>`.
They are excluded automatically in Step 4.

---

## Step 4 — Export to Gemma format

```bash
python -m scripts.distill.export_kira
```

Reads `data/kira/labeled/` and applies three balancing passes to the train split:

1. **No-risk cap** — rows where `ds_issue_type` is null are capped at 20% of train
2. **Clause-type cap** — per `clause_type`, cap at `median_count × 3` (prevents "License Grant" dominating)
3. **Severity upsample** — within each clause-type bucket, ensure at least one example per severity level (max 2× upsample)

Val and test splits are exported as-is (no balancing).

**Output** in `data/kira/ft/{train,val,test}.jsonl`, one JSON object per line:

```json
{
  "messages": [
    {"role": "system",    "content": "You are Kira, an expert AI legal contract reviewer..."},
    {"role": "user",      "content": "Contract: ...\nClause type: ...\n--- CLAUSE ---\n..."},
    {"role": "assistant", "content": "{\"findings\": [{\"issue_type\": \"liability_exposure\", ...}]}"}
  ]
}
```

No-risk rows produce `{"findings": []}` as the assistant turn.

---

## Step 5 — Fine-tune

```bash
python -m scripts.distill.train_gemma --role kira --load-4bit
```

Trains LoRA adapters on `data/kira/ft/train.jsonl`, evaluates on `val.jsonl`.
Checkpoints saved to `data/distillation/checkpoints_kira/`.
Final model at `data/distillation/model_kira/`.

---

## Run order (complete)

```bash
python -m scripts.download_datasets
python -m scripts.build_kira_dataset

# Set DEEPSEEK_API_KEY and DEEPSEEK_MODEL in .env, then:
python -m scripts.distill.label_with_deepseek --dry-run
python -m scripts.distill.label_with_deepseek --split all

python -m scripts.distill.export_kira
python -m scripts.distill.train_gemma --role kira --load-4bit
```

---

## File map

```
data/
├── atticus/
│   ├── cuad.parquet              QA rows (title, context, question, answers)
│   └── cuad_clauses.parquet      Clause spans with FULL contract context
├── maud/
│   └── maud.parquet              39k expert-annotated M&A QA rows
└── kira/
    ├── raw/                      Output of build_kira_dataset.py
    │   ├── train.jsonl           22,942 rows (CUAD + MAUD)
    │   ├── val.jsonl             5,679 rows
    │   └── test.jsonl            5,563 rows
    ├── labeled/                  Output of label_with_deepseek.py
    │   ├── train.jsonl           + ds_* fields
    │   ├── val.jsonl
    │   └── test.jsonl
    └── ft/                       Output of export_kira.py
        ├── train.jsonl           Balanced Gemma chat turns
        ├── val.jsonl
        └── test.jsonl

scripts/
├── download_datasets.py          Download CUAD + MAUD from HuggingFace
├── build_kira_dataset.py         Build raw rows, document-level split
└── distill/
    ├── config.py                 All paths and constants (KIRA_RAW_DIR etc.)
    ├── label_with_deepseek.py    DeepSeek labeling with checkpoint + fallback
    ├── export_kira.py            Balanced Gemma chat-turn export
    └── train_gemma.py            LoRA fine-tune on Gemma 4 26B

.env                              DEEPSEEK_API_KEY and DEEPSEEK_MODEL (fill before Step 3)
```

---

## 13 Issue Types

| Issue type | Description |
|------------|-------------|
| `liability_exposure` | Unlimited or one-sided indemnification, uncapped damages |
| `termination_risk` | Unilateral termination, short notice, automatic termination triggers |
| `ip_risk` | Broad IP assignment, loss of ownership, work-for-hire traps |
| `financial_obligation` | Uncapped fees, milestone payments, penalty clauses |
| `restriction_clause` | Non-compete, non-solicit, exclusivity with unclear scope |
| `dispute_resolution` | Unfavorable venue, mandatory arbitration, asymmetric rights |
| `warranty_and_insurance` | Inadequate warranty duration, missing insurance requirements |
| `governance_risk` | Change-of-control triggers, unilateral amendment rights |
| `third_party_risk` | Obligations to unnamed third parties, assignment without consent |
| `compliance_obligation` | Regulatory requirements, audit rights, reporting burdens |
| `confidentiality_risk` | Overly broad confidentiality scope, no carve-outs |
| `representation_risk` | Inaccurate or overly broad representations and warranties |
| `jurisdictional_risk` | Unfavorable governing law, ambiguous jurisdiction |
