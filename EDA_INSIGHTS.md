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
7. [Token Budget and Imbalance Summary](#7-token-budget-and-imbalance-summary)
8. [Data Quality Flags](#8-data-quality-flags)

---

## 1. Dataset Overview

| Dataset | Rows | Granularity | Labels |
|---------|-----:|-------------|--------|
| Atticus (CUAD) | 13,823 | Clause | 41 clause types |
| LEDGAR | 80,000 | Clause | 100 provision types |
| ContractNLI | 9,788 | Premise–Hypothesis pairs | 3 (entail / contradict / neutral) |
| Material Contracts (SEC) | 804 | Full document | 52 doc types |
| RISCBAC | 10,000 | Full document | — (⚠️ pending) |


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

## 7. Token Budget and Imbalance Summary

### Token Budget (Clause-Level Datasets)

| Metric | Value |
|--------|------:|
| Combined clause samples (CUAD + LEDGAR) | 93,823 |
| Median estimated tokens | 99 |
| 95th percentile tokens | 381 |
| 99th percentile tokens | 604 |
| Samples needing chunking (>2048 tokens) | **0** |

> Clause-level data (CUAD, LEDGAR, ContractNLI premises) fits almost entirely within a 512-token window — nothing requires chunking. Material Contracts are a different story: only 5% fit at 512 tokens; 16k context is needed to cover 99.6% without chunking.

### Context Window Requirements by Dataset

| Dataset | Context Window | % That Fit |
|---------|---------------|----------:|
| CUAD | 512 tokens | 99.9% |
| LEDGAR | 512 tokens | 97.7% |
| ContractNLI pairs | 512 tokens | 99.2% |
| Material Contracts | 4,096 tokens | 53.1% |
| Material Contracts | 16,384 tokens | 99.6% |

### Class Imbalance Summary

| Dataset | Imbalance Ratio | Severity |
|---------|----------------:|---------|
| LEDGAR | 169.7× | 🔴 Severe |
| CUAD | 94.6× | 🔴 Severe |
| ContractNLI | 4.1× | 🟡 Moderate |

Both supervised datasets have severe imbalance. This is a **critical issue** for LLM fine-tuning — without correction, models will over-predict frequent labels (e.g., "Financings", "Parties") and ignore rare but legally important ones.

---

## 8. Data Quality Flags

Issues to address before using any dataset downstream:

| Flag | Dataset | Detail |
|------|---------|--------|
| 🔴 Severe imbalance (94.6×) | CUAD | Top label (Parties, 2,554) vs bottom (Price Restrictions, 27) |
| 🔴 Severe imbalance (169.7×) | LEDGAR | Top label (Financings, 4,243) vs bottom (Capitalization, 25) |
| 🟡 Contradiction underrepresented | ContractNLI | 11.3% contradiction vs 46.4% entailment |
| 🟡 15% duplicates | CUAD | 2,140 duplicate clause spans — filter before use |
| 🟡 Short/noise rows | CUAD | 1,619 clauses under 3 words — likely impossible-answer spans |
| 🔴 Document length | Material Contracts | Only 5% fit in 512 tokens; 16k context covers 99.6% |
| 🟡 Missing governing law | Material Contracts | 27% of rows have "N/A" for `governing_law` |
| ⚠️ RISCBAC unavailable | RISCBAC | GRAAL server unreachable — manual download required |

**Minimum cleaning steps before any use:**
1. **CUAD:** Filter `is_impossible=True` rows; de-duplicate on `clause_text`
2. **LEDGAR:** Flag or merge bottom-quartile labels (<100 samples) — too few for reliable signal
3. **Material Contracts:** Drop rows where `full_text` is empty or under 100 words

---

*Generated from EDA pipeline — Veridict Project, April 2026*
