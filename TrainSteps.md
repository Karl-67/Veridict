# Curated Training Data

This directory contains the fine-tuning datasets for the Veridict reviewer and validator agents.

## Directory Layout

```
data/curated/
├── split_manifest.json          # Contract-level train/val/test assignment (CUAD + LEDGAR)
├── boilerplate_archive.jsonl    # Negative examples — standard clauses that must NOT be flagged
│
├── dataset_a/                   # Reviewer fine-tuning (from CUAD)
│   ├── reviewer_train.jsonl     # 172,221 rows
│   ├── reviewer_val.jsonl       # 26,061 rows
│   └── reviewer_test.jsonl      # 13,818 rows
│
├── dataset_b/                   # Validator fine-tuning (from ContractNLI)
│   ├── validator_train.jsonl    # 9,231 rows
│   ├── validator_val.jsonl      # 0 rows — MISSING, hold out ~10% of train manually
│   └── validator_test.jsonl     # 1,991 rows
│
└── golden/
    ├── golden_edge_cases.jsonl  # 115 hold-out edge cases — never used for training
    └── overlap_report.txt       # Dedup report (SHA-256 + Jaccard ≥ 0.85 check vs. train)
```

---

## Dataset A — Reviewer Fine-tuning

**Source:** CUAD (Atticus) — 510 SEC contracts with 41 annotated clause categories
**Target agents:** HarveyReviewerAgent, KiraReviewerAgent (all 3 role variants each)

### Schema

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Unique row ID |
| `source` | str | Always `cuad` |
| `contract_id` | str | CUAD contract name |
| `clause_text` | str | The clause to be reviewed |
| `issue_type` | str | Category of legal risk |
| `severity` | str | `low` / `medium` / `high` |
| `severity_confidence` | str | `weak` / `moderate` / `strong` |
| `description` | str | Explanation of the issue |
| `recommendation` | str | Suggested mitigation |
| `agent_role` | str | `issue_discovery` / `false_positive_challenge` / `exploitability_impact` |
| `branch` | str | `harvey` (internal policy) or `kira` (compliance) |
| `split` | str | `train` / `val` / `test` |
| `class_weight` | float | Per-sample weight to compensate for label imbalance |

### Row Counts by Branch and Agent Role (train)

| Branch | Agent Role | Rows |
|--------|-----------|------|
| harvey | issue_discovery | 42,177 |
| harvey | false_positive_challenge | 42,121 |
| harvey | exploitability_impact | 42,158 |
| kira | issue_discovery | 15,258 |
| kira | false_positive_challenge | 15,233 |
| kira | exploitability_impact | 15,274 |

Harvey has ~3× more data than Kira. CUAD maps directly to internal policy checking (Harvey). Kira's
compliance scope requires LEDGAR — those rows are indexed in `split_manifest.json` but not yet wired
into Dataset A.

### Issue Type Distribution (train)

`financial_obligation` dominates (54,477 rows). `third_party_risk` is the rarest (348 rows). Use
`class_weight` during loss computation to avoid the model collapsing to the majority class.

### How to Use

```python
# Filter by branch and role to train a specialized model
import json

def load_reviewer_split(split: str, branch: str, agent_role: str):
    rows = []
    with open(f"dataset_a/reviewer_{split}.jsonl") as f:
        for line in f:
            row = json.loads(line)
            if row["branch"] == branch and row["agent_role"] == agent_role:
                rows.append(row)
    return rows

# Example: train the Harvey issue-discovery reviewer
train = load_reviewer_split("train", "harvey", "issue_discovery")

# Prompt format (adapt to your fine-tuning framework):
# System: "You are a legal reviewer identifying issues in contract clauses. [role instructions]"
# User:   clause_text
# Target: JSON with issue_type, severity, description, recommendation
```

---

## Dataset B — Validator Fine-tuning

**Source:** ContractNLI — 9,788 NLI examples from real NDAs
**Target agents:** HarveyValidatorAgent, KiraValidatorAgent

The validator checks whether a reviewer's finding (hypothesis) is actually supported by the clause
(premise). ContractNLI's NLI task maps directly to this.

### Schema

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Unique row ID |
| `source` | str | Always `contractnli` |
| `premise` | str | The actual clause text |
| `hypothesis` | str | The reviewer's proposed finding |
| `nli_label` | str | `entailment` / `contradiction` / `neutral` |
| `verdict` | str | `retain` / `reject` / `uncertain` |
| `split` | str | `train` / `test` |

### NLI Label → Validator Verdict Mapping

| NLI Label | Verdict | Meaning |
|-----------|---------|---------|
| `entailment` | `retain` | Finding is grounded in the clause — keep it |
| `contradiction` | `reject` | Finding contradicts the clause — hallucination |
| `neutral` | `uncertain` | Inconclusive — flag for human review |

### Row Counts

| Split | Rows | Entailment | Contradiction | Neutral |
|-------|------|-----------|--------------|---------|
| train | 9,231 | 3,195 (34.6%) | 3,216 (34.8%) | 2,820 (30.5%) |
| val | 0 | — | — | — |
| test | 1,991 | 878 (44.1%) | 210 (10.5%) | 903 (45.4%) |

**Warning:** `validator_val.jsonl` is empty. Hold out ~10% of the training set as a validation split
before training. The test set is also skewed — `contradiction` recall metrics are less stable at n=210.

### How to Use

```python
# Input: (premise, hypothesis) pair
# Output: verdict (retain / reject / uncertain)

# Prompt format:
# System: "You are a legal clause validator. Given a contract clause and a proposed finding,
#          determine if the finding is supported by the clause."
# User:   "Clause: {premise}\nFinding: {hypothesis}\nIs this finding supported?"
# Target: verdict
```

---

## Boilerplate Archive — Negative Examples

**Source:** CUAD (2,016 rows) + LEDGAR (17,183 rows) = **19,199 total**

These are standard/routine clauses that should **not** trigger any findings. They are the training
signal for the `false_positive_challenge` agent role — the reviewer whose job is to suppress
boilerplate flagging.

### Schema

| Field | Type | Description |
|-------|------|-------------|
| `source` | str | `cuad` or `ledgar` |
| `clause_text` | str | The boilerplate clause |
| `original_label` | str | Source annotation (e.g. CUAD category description) |
| `contract_id` | str | Source contract identifier |

### How to Use

Mix into reviewer training as negative examples (target: `no_issue`) when training the
`false_positive_challenge` role:

```python
# Augment false_positive_challenge training with boilerplate negatives
boilerplate = load_jsonl("boilerplate_archive.jsonl")
for row in boilerplate:
    row["issue_type"] = "no_issue"
    row["severity"] = None
    row["agent_role"] = "false_positive_challenge"
```

---

## Golden Dataset — Hold-out Evaluation Only

**115 examples** curated across 3 edge-case categories. Deduplicated against all 55,811 training
hashes using SHA-256 exact match and Jaccard ≥ 0.85 near-duplicate removal (33 exact + 5
near-duplicates removed). See `golden/overlap_report.txt` for details.

**Never use for training. This is your benchmark.**

### Schema

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Unique ID |
| `category` | str | `contradiction` / `rare_issue` / `false_positive_trap` |
| `source` | str | `contractnli` / `cuad` / `ledgar` |
| `clause_text` | str | The clause under test |
| `hypothesis` | str | The proposed finding to evaluate |
| `issue_type` | str | Expected issue type (null for false_positive_trap) |
| `overlap_score` | float | Highest Jaccard score vs. training set |
| `expected_behavior` | dict | `validator_verdict`, `failure_mode`, `notes` |

### Category Breakdown

| Category | Count | Sources | What It Tests |
|----------|-------|---------|---------------|
| `contradiction` | 42 | contractnli | Hallucination detection — clause explicitly refutes the finding |
| `rare_issue` | 48 | cuad | Edge case recall — issues small models tend to miss |
| `false_positive_trap` | 25 | ledgar | Boilerplate suppression — standard language that looks suspicious |

---

## Split Manifest

`split_manifest.json` assigns CUAD contracts and LEDGAR row indices to each split. Splits are
**by contract**, not by clause — all clauses from one contract stay in the same split. This prevents
data leakage where a model trains on clause A from Contract X and is then evaluated on clause B
from the same contract.

| Dataset | Train | Val | Test |
|---------|-------|-----|------|
| CUAD contracts | ~333 | ~47 | ~46 |
| LEDGAR row indices | ~47,081 | ~7,857 | ~3,939 |

When generating new examples from raw data, always check the manifest before assigning a split.

---

## Training Recipe

```
1. Reviewer agents (6 models or 2 base + 3 LoRA adapters each)
   └── Filter dataset_a by branch + agent_role
   └── Use class_weight for loss weighting
   └── Eval on reviewer_val.jsonl, final test on reviewer_test.jsonl

2. Validator agents (1 shared model)
   └── Train on dataset_b/validator_train.jsonl
   └── Hold out 10% of train as val (validator_val.jsonl is empty)
   └── Final test on validator_test.jsonl

3. False-positive suppression (augment step 1)
   └── Mix boilerplate_archive.jsonl as no_issue negatives
   └── Apply only to false_positive_challenge role training

4. Edge case evaluation (final benchmark)
   └── Run all trained models on golden/golden_edge_cases.jsonl
   └── Report recall per category: contradiction / rare_issue / false_positive_trap
```

---

## Known Gaps

| Gap | Impact | Fix |
|-----|--------|-----|
| `validator_val.jsonl` is empty | No validation loop for validator training | Hold out 10% of `validator_train.jsonl` |
| Kira has 3× less reviewer data than Harvey | Kira agents will underperform | Wire LEDGAR into Dataset A generation |
| Golden set is only 115 examples | Low statistical power for rare categories | Expand to 500+ per category |
| LEDGAR not in Dataset A | Kira compliance training is CUAD-only | Run LEDGAR through the curator pipeline |
