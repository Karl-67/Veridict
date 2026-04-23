# Data Pipeline

Covers curation (`curate_dataset.py`), golden selection (`curate_golden.py`), and labeling shards.

---

## Source Datasets

| Dataset | File | Rows | Task |
|---------|------|------|------|
| CUAD (Atticus) | `data/atticus/cuad_clauses.parquet` | ~13,800 clauses | Clause classification |
| LEDGAR | `data/legal_clauses/ledgar.parquet` | 80,000 clauses | Clause classification |
| ContractNLI | `data/contractnli/contractnli.parquet` | 9,788 pairs | NLI (retain / reject / uncertain) |
| MAUD | `data/maud/maud.parquet` | 39,231 rows | M&A deal-point QA |

**Why MAUD?**  CUAD and LEDGAR teach clause-level risk classification on standard commercial contracts.  MAUD teaches a qualitatively different skill: multi-sentence reasoning over merger agreement passages against specific deal-point questions (e.g. "What is the outside date?", "Does the MAE definition include customer attrition?").  M&A agreements have their own vocabulary and risk structure that does not appear in CUAD or LEDGAR, so without MAUD the model has no exposure to that domain during SFT.  MAUD annotations are all attorney-sourced, making them the highest-quality signal in the pipeline.

---

## Curation Pipeline (`curate_dataset.py`)

Run once to produce the canonical outputs:

```
python scripts/curate_dataset.py
```

### Phases

| Phase | What it does |
|-------|-------------|
| A | Load & clean. CUAD: dedup by `clause_text`, drop rows < 10 words. LEDGAR: decode integer labels. MAUD: no passage-level dedup (reuse across questions is intentional); filter 10–600 words. |
| B+C | Map each clause to one of 13 unified issue types. Boilerplate rows are archived to `boilerplate_archive.jsonl` for RAG use, not discarded. |
| G | Document-level train/val/test split **before** any weak supervision, preventing leakage. MAUD uses its official splits unchanged. |
| D+E | Weak supervision: attach `description`, `recommendation`, `severity` (heuristic). Role augmentation: each clause becomes 3 rows — `issue_discovery`, `false_positive_challenge`, `exploitability_impact`. Branch (`harvey`/`kira`) is fixed by issue type, independent of role. |
| F | Imbalance correction on train split only. Primary signal: `class_weight` field (inverse frequency). Secondary: capped oversampling up to 3× per unique row. |
| H | ContractNLI validator dataset. Maps NLI labels → `retain` / `reject` / `uncertain`. Oversamples `reject` toward 35% of train. |
| I | MAUD M&A reviewer dataset. Generates deal-point QA records. Oversamples rare categories to a floor of 400 rows in train. |
| J | RL pool: all train-split rows from Datasets A + B + C combined into a single undivided pool. Not split by shard. |

### Outputs

```
data/curated/
  dataset_a/   reviewer_{train,val,test}.jsonl   — Reviewer SFT (~171k / 26k / 14k rows)
  dataset_b/   validator_{train,val,test}.jsonl  — Validator SFT (~9.2k / 1k / 2k rows)
  dataset_c/   maud_{train,val,test}.jsonl       — M&A Reviewer SFT (~17k / 4.4k / 4.3k rows)
  rl_pool.jsonl                                  — ~198k rows, no split
  boilerplate_archive.jsonl                      — Archived boilerplate for RAG
  split_manifest.json                            — Split ledger used by curate_golden.py
```

### Unified Taxonomy (13 issue types)

`liability_exposure` · `restriction_clause` · `ip_risk` · `financial_obligation` · `termination_risk` · `governance_risk` · `compliance_obligation` · `dispute_resolution` · `confidentiality_risk` · `warranty_and_insurance` · `jurisdictional_risk` · `representation_risk` · `third_party_risk`

Branch assignment is derived from issue type, not chosen at labeling time:
- **harvey** — internal policy context: liability, IP, financial, termination, governance, restriction, warranty, dispute, third-party
- **kira** — compliance/regulatory context: compliance, jurisdiction, representation, confidentiality

---

## Golden Dataset (`curate_golden.py`)

Must be run after `curate_dataset.py`:

```
python scripts/curate_golden.py
```

The golden set provides dense evaluation coverage for types and categories that are **underrepresented in the regular test split** (fewer than 500 rows).  Selection is test-rarity driven, not hardness-based.

### Four categories

| Category | Source | Selection rule |
|----------|--------|----------------|
| `rare_reviewer` | CUAD golden contracts + LEDGAR golden rows | Issue types with < 500 rows in `reviewer_test.jsonl` |
| `rare_validator` | ContractNLI val/test rows | Verdicts with < 500 rows in `validator_test.jsonl` (`reject` = ~210) |
| `rare_maud` | MAUD val/test rows | MAUD categories with < 500 rows in `maud_test.jsonl` |
| `false_positive_trap` | `boilerplate_archive.jsonl` | Boilerplate labels containing ≥ 2 risk keywords |

**Overlap check**: exact SHA-256 hash match against training data only.  Jaccard fuzzy matching is not used against training (legal boilerplate legitimately shares phrasing across splits).  Jaccard 0.85 is used only within the golden set to deduplicate near-identical rows.

**Output**: `data/curated/golden/golden_edge_cases.jsonl` (~189 examples)

---

## Labeling Shards

The labeling pipeline (OAuth GPT) is parallelised across three people.  Each person labels one shard.  After labeling, outputs are merged before computing global metrics.

```
# Build shard N (label-bearing splits only; RL pool stays global)
python scripts/curate_dataset.py --shard N --num-shards 3
python scripts/curate_golden.py  --shard N --num-shards 3

# Aliases
python scripts/curate_dataset.py --shard1   # equivalent to --shard 1 --num-shards 3
python scripts/curate_golden.py  --shard1
```

### Shard assignment

```
label_shard = (SHA-256(group_key) % num_shards) + 1
```

Assignment is **deterministic and stable**: re-running with the same inputs always produces the same shards.  Oversampled copies of a row inherit the same shard as the original.

| Dataset | Group key | Rationale |
|---------|-----------|-----------|
| Reviewer | `source` + `contract_id` + `clause_text` | All 3 roles for the same clause go to one labeler |
| Validator | `source` + `premise` + `hypothesis` | Atomic NLI unit |
| MAUD | `source` + `contract_id` + `passage` + `question` | Fine-grained; better balance across shards |

### Shard output shape

```
data/curated/shards/
  shard_1/
    dataset_a/  reviewer_{train,val,test}.jsonl   (~57k / 8.4k / 4.9k rows)
    dataset_b/  validator_{train,val,test}.jsonl  (~3.1k / 335 / 719 rows)
    dataset_c/  maud_{train,val,test}.jsonl       (~5.6k / 1.5k / 1.4k rows)
    golden/     golden_edge_cases.jsonl           (~73 rows)
  shard_2/  ...  (~57k / 8.7k / 4.7k | ~3.1k / 318 / 631 | ~5.7k / 1.5k / 1.5k | ~59 golden)
  shard_3/  ...  (~57k / 9.0k / 4.7k | ~3.0k / 325 / 641 | ~5.7k / 1.5k / 1.5k | ~57 golden)
```

### Labeling workflow

1. Build canonical data once (`curate_dataset.py` + `curate_golden.py`, no `--shard` flag).
2. Build shard outputs for each person (`--shard 1/2/3`).
3. Each person runs the OAuth GPT labeling pipeline on their shard.
4. Merge labeled shard outputs back into full train/val/test/golden.
5. Compute global metrics on the merged labeled val/test/golden.

The RL pool is not sharded.  It is reconstructed from labeled train rows after the merge step.
