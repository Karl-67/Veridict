# Veridict — Dataset EDA Insights Report

**Date:** April 2026
**Scope:** 4 of 5 planned datasets (RISCBAC server currently unreachable)
**Total samples available:** 104,415

---

## Table of Contents
1. [Dataset Overview](#1-dataset-overview)
2. [Atticus (CUAD)](#2-atticus-cuad)
3. [LEDGAR (Legal Clauses)](#3-ledgar-legal-clauses)
4. [ContractNLI](#4-contractnli)
5. [Material Contracts (SEC)](#5-material-contracts-sec)
6. [Cross-Dataset Comparison](#6-cross-dataset-comparison)
7. [LLM Training Readiness](#7-llm-training-readiness)
8. [Recommendations](#8-recommendations)

---

## 1. Dataset Overview

| Dataset | Role | Rows | Granularity | Labels |
|---------|------|-----:|-------------|--------|
| Atticus (CUAD) | Supervised / Classification | 13,823 | Clause | 41 clause types |
| LEDGAR | Supervised / Classification | 80,000 | Clause | 100 provision types |
| ContractNLI | Reasoning / NLI | 9,788 | Premise–Hypothesis pairs | 3 (entail / contradict / neutral) |
| Material Contracts (SEC) | Raw / Pretraining | 804 | Full document | 52 doc types |
| RISCBAC | Raw / Pretraining | 10,000 | Full document | — (⚠️ pending) |

The pipeline is structured around **3 task roles**:
- **Supervised / Classification** — Atticus + LEDGAR → clause tagging and labeling
- **Reasoning / NLI** — ContractNLI → claim validation against contract text
- **Raw / Pretraining** — Material + RISCBAC → continued pretraining and retrieval

---

## 2. Atticus (CUAD)

### Scale
- **13,823** annotated clause spans across **510** commercial contracts
- **41 clause categories** (e.g., Parties, License Grant, Governing Law, Cap on Liability)
- Average **27.1 clauses per contract** (max: 97)

### Text Length
| Metric | Value |
|--------|------:|
| Mean word count | 40.7 |
| Median word count | 31 |
| Max word count | 479 |
| % fitting in 512-token window | **99.9%** |

> All clauses fit comfortably in 512 tokens — ideal for fine-tuning encoder models (BERT, RoBERTa, LegalBERT).

### Label Distribution
CUAD is **severely imbalanced** with an imbalance ratio of **94.6×**:

| Top labels | Count |
|------------|------:|
| Parties | 2,554 |
| License Grant | 777 |
| Cap On Liability | 672 |
| Anti-Assignment | 654 |
| Audit Rights | 643 |

| Bottom labels | Count |
|---------------|------:|
| No-Solicit Of Customers | 58 |
| Third Party Beneficiary | 39 |
| Most Favored Nation | 38 |
| Unlimited License | 32 |
| Price Restrictions | 27 |

> **Risk:** Training a classifier directly will heavily bias toward "Parties" and almost never predict rare categories like "Price Restrictions" (27 samples). Oversampling or weighted loss is mandatory.

### Data Quality
- **2,140 duplicate clause spans** (15.5% of dataset) — likely the same clause text appearing across multiple QA rows for the same contract passage
- **1,619 very short clauses** (<3 words, 11.7%) — likely answer spans for negative/impossible QA examples
- Recommendation: filter out `is_impossible=True` rows and de-duplicate before training

---

## 3. LEDGAR (Legal Clauses)

### Scale
- **80,000** contract provisions across **100 provision types**
- Well-structured: 60k train / 10k validation / 10k test (official splits)

### Text Length
| Metric | Value |
|--------|------:|
| Mean word count | 113.0 |
| Median word count | 84 |
| Max word count | 1,215 |
| % fitting in 512-token window | **97.7%** |
| % fitting in 1024-token window | **99.9%** |

> Longer than CUAD clauses (median 84 vs 31 words). Some provisions (1,215 words max) may require truncation at 512 tokens — but only 2.3% of the dataset.

### Label Distribution
LEDGAR is **extremely imbalanced** with a ratio of **169.7×**:

| Top labels | Count |
|------------|------:|
| Financings | 4,243 |
| Costs | 3,346 |
| Limitations | 3,313 |
| Erisa | 3,105 |
| Obligations | 2,552 |

| Bottom labels | Count |
|---------------|------:|
| Anti-Corruption Laws | 155 |
| Modifications | 153 |
| No Defaults | 60 |
| Audits | 38 |
| Capitalization | 25 |

> With 100 classes and a 169.7× imbalance, LEDGAR presents a harder classification problem than CUAD. The bottom quartile of labels has fewer than 100 samples — too few for reliable supervised learning without augmentation.

### Data Quality
- **Zero duplicate texts** — dataset is clean
- No missing values in key fields
- Very consistent quality as it comes from LexGLUE benchmark

---

## 4. ContractNLI

### Scale
- **9,788** (premise, hypothesis, label) triples
- Splits: **6,819** train / **978** dev / **1,991** test

### Label Distribution
| Label | Count | % |
|-------|------:|--:|
| Entailment | 4,539 | 46.4% |
| Neutral | 4,146 | 42.4% |
| Contradiction | 1,103 | 11.3% |

- Imbalance ratio: **4.1×** — moderate but manageable
- **Contradiction is underrepresented** — the model may struggle to identify when a hypothesis directly contradicts contract text, which is arguably the most important signal for contract validation

### Text Length
| Field | Mean words | Median | Max |
|-------|----------:|-------:|----:|
| Premise (contract clause) | 98.7 | 75 | 429 |
| Hypothesis (statement) | 12.8 | 13 | 23 |

- Hypotheses are very short (avg 12.8 words) — consistent phrasing of legal obligations
- Premises are moderate length (avg 98.7 words) — contract clauses
- **99.2% of combined pairs fit in 512 tokens**, making this compatible with standard BERT-style encoding

### Data Quality
- No duplicates or empty fields detected
- Labels are string-encoded (no mapping needed)
- This is a benchmark-quality dataset — very clean

---

## 5. Material Contracts (SEC)

### Scale
- **804** real contracts from SEC EDGAR filings (8-K, 10-K, 10-Q)
- Rich metadata extracted by GPT-4o: parties, dates, governing law, payment terms, auto-renewal flags

### Filing Type Distribution
| Filing Type | Count |
|-------------|------:|
| 8-K (material event) | 717 (89.2%) |
| 10-Q (quarterly report) | 52 (6.5%) |
| 10-K (annual report) | 35 (4.4%) |

> The vast majority are 8-K filings — i.e., contracts filed as material events, not embedded annual/quarterly report exhibits.

### Document Type Distribution (top 5)
| Doc Type | Count |
|----------|------:|
| EX-10.1 | 372 |
| EX-10.2 | 154 |
| EX-10.3 | 71 |
| EX-10.4 | 50 |
| EX-10.5 | 34 |

> EX-10.x are "material contract" exhibits — the primary category of interest for contract AI.

### Text Length (full contracts)
| Metric | Value |
|--------|------:|
| Mean word count | 3,253 |
| Median word count | 2,756 |
| Max word count | 12,968 |
| Mean estimated pages | 6.5 |
| Max estimated pages | 26 |

**This is the key challenge for this dataset — documents are very long:**

| Token Window | % of Contracts That Fit |
|-------------|------------------------:|
| 512 tokens | **5.0%** |
| 2,048 tokens | **33.0%** |
| 4,096 tokens | **53.1%** |
| 16,384 tokens | **99.6%** |

> Nearly all contracts require at least 4k token windows. Less than a third fit within a standard 2k window. A **16k context model** (GPT-4, Claude, Llama-3 long) is required to process these without chunking.

### Metadata Completeness
All GPT-4o-extracted fields are present (0% missing for governing_law, party_name, contract_value). However, some fields have qualitative noise:
- `governing_law`: 217 entries are "N/A" (27%) — these contracts don't specify governing law explicitly
- Top governing laws: **New York (218)**, Delaware (107), Florida (29), Nevada (27)

> New York and Delaware dominate — consistent with real-world SEC filings where most companies incorporate in Delaware and conduct finance in New York.

---

## 6. Cross-Dataset Comparison

### Size and Coverage
| Dataset | Samples | Unique Labels | Granularity |
|---------|--------:|--------------|-------------|
| LEDGAR | 80,000 | 100 | Clause |
| Atticus (CUAD) | 13,823 | 41 | Clause |
| ContractNLI | 9,788 | 3 | Clause pair |
| Material Contracts | 804 | 52 (doc types) | Document |

> **LEDGAR dominates** the supervised dataset by 6× over CUAD. Any combined classifier will be heavily anchored in LEDGAR's provision vocabulary.

### Text Length by Dataset
| Dataset | Median Words | P95 Words |
|---------|------------:|----------:|
| CUAD | 31 | 95 |
| LEDGAR | 84 | 270 |
| ContractNLI (premise) | 75 | 243 |
| Material Contracts | 2,756 | 6,500+ |

> There is a **100× scale difference** between clause-level datasets and document-level datasets. Material contracts require fundamentally different handling (chunking, retrieval).

### Label Overlap Between CUAD and LEDGAR
The two supervised datasets use **different labeling schemes**. CUAD uses 41 specific clause categories (e.g., "Anti-Assignment") while LEDGAR uses 100 provision types (e.g., "Assignments"). There is **conceptual overlap but no direct label alignment** — they cannot be naively merged for a single classifier.

---

## 7. LLM Training Readiness

### Token Budget Summary (Supervised / Clause-Level)

| Metric | Value |
|--------|------:|
| Combined supervised samples (CUAD + LEDGAR) | 93,823 |
| Median estimated tokens | 99 |
| 95th percentile tokens | 381 |
| 99th percentile tokens | 604 |
| Samples needing chunking (>2048 tokens) | **0** |

> **Clause-level training is extremely LLM-friendly.** The entire supervised dataset fits within a 512-token window for 95% of samples, and nothing requires chunking. This makes fine-tuning both fast and memory-efficient.

### By Task Role

| Role | Dataset | Context Window Needed | Chunking Required? |
|------|---------|----------------------|--------------------|
| Classification | CUAD + LEDGAR | 512 tokens | No |
| NLI / Reasoning | ContractNLI | 512 tokens | No (99.2% fit) |
| Pretraining | Material Contracts | 4k–16k tokens | Yes (47–95% of docs) |

### Class Imbalance Summary

| Dataset | Imbalance Ratio | Severity |
|---------|----------------:|---------|
| LEDGAR | 169.7× | 🔴 Severe |
| CUAD | 94.6× | 🔴 Severe |
| ContractNLI | 4.1× | 🟡 Moderate |

Both supervised datasets have severe imbalance. This is a **critical issue** for LLM fine-tuning — without correction, models will over-predict frequent labels (e.g., "Financings", "Parties") and ignore rare but legally important ones.

---

## 8. Recommendations

### Data Cleaning (Do Before Training)

1. **CUAD:** Remove `is_impossible=True` rows and de-duplicate by `clause_text`. This eliminates ~15% of rows but significantly improves signal quality.
2. **LEDGAR:** Remove or merge the bottom 10 labels (<100 samples each) into an "Other" class, or apply oversampling (SMOTE on embeddings, or in-context data augmentation with an LLM).
3. **Material Contracts:** Filter rows where `full_text` is empty or under 100 words.

### Training Strategy

**Model 1 — Clause Classifier**
- Data: CUAD + LEDGAR (clean, de-duplicated)
- Architecture: LegalBERT or RoBERTa-base, sequence classification
- Context: 512 tokens (covers 97%+ of data)
- Key issue: Handle 169.7× imbalance with class-weighted cross-entropy
- Recommended split: Use LEDGAR's official splits; add CUAD with 80/10/10 stratified by clause_type

**Model 2 — Contract NLI / Reasoning**
- Data: ContractNLI
- Architecture: BERT-style cross-encoder (premise + hypothesis in single input)
- Context: 512 tokens (99.2% fit)
- Key issue: Contradiction class is underrepresented (11.3%) — consider 2× oversampling
- Use provided train/dev/test splits for fair evaluation

**Model 3 — Document Encoder / Retriever**
- Data: Material Contracts (SEC)
- Architecture: Long-context model (e.g., Longformer, BigBird) or chunked embeddings
- Context: 4k–16k tokens required
- Use for retrieval-augmented generation (RAG) over full contracts

### Recommended Split Ratios

| Dataset | Train | Val | Test | Strategy |
|---------|------:|----:|-----:|---------|
| CUAD | 80% | 10% | 10% | Stratify by clause_type |
| LEDGAR | 75% | 12.5% | 12.5% | Use official splits |
| ContractNLI | 70% | 10% | 20% | Use official splits |
| Material | 70% | 15% | 15% | Stratify by doc_type |

### Priority Flags

| Flag | Dataset | Action |
|------|---------|--------|
| 🔴 Severe imbalance | CUAD, LEDGAR | Weighted loss + oversampling |
| 🟡 Contradiction underrepresented | ContractNLI | Mild oversampling (2×) |
| 🟡 15% duplicates | CUAD | De-duplicate before split |
| 🔴 Document length | Material Contracts | Chunking pipeline required |
| ⚠️ RISCBAC unavailable | RISCBAC | Manual download from GRAAL server |

---

*Generated from EDA pipeline — Veridict Project, April 2026*
