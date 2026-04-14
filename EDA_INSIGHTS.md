# Veridict — Dataset EDA Insights Report

**Date:** April 2026
**Scope:** All 5 datasets (RISCBAC manually downloaded and parsed)
**Total samples available:** 114,415

---

## Table of Contents
1. [Dataset Overview](#1-dataset-overview)
2. [Atticus (CUAD)](#2-atticus-cuad)
3. [LEDGAR (Legal Clauses)](#3-ledgar-legal-clauses)
4. [ContractNLI](#4-contractnli)
5. [Material Contracts (SEC)](#5-material-contracts-sec)
6. [RISCBAC](#6-riscbac)
7. [Cross-Dataset Comparison](#7-cross-dataset-comparison)
8. [Token Budget and Imbalance Summary](#8-token-budget-and-imbalance-summary)
9. [Data Quality Flags](#9-data-quality-flags)

---

## 1. Dataset Overview

| Dataset | Rows | Granularity | Labels |
|---------|-----:|-------------|--------|
| Atticus (CUAD) | 13,823 | Clause | 41 clause types |
| LEDGAR | 80,000 | Clause | 100 provision types |
| ContractNLI | 9,788 | Premise–Hypothesis pairs | 3 (entail / contradict / neutral) |
| Material Contracts (SEC) | 804 | Full document | 52 doc types |
| RISCBAC | 10,000 | Full document | — (unlabelled) |


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

## 6. RISCBAC

### What It Is
RISCBAC is a **synthetic bilingual automobile insurance contract dataset** generated by the GRAAL Research Lab at Université Laval using the [RISC](https://github.com/GRAAL-Research/risc) package. All contracts are based on the Quebec regulatory insurance form (Q.P.F. No. 1 — Owner's Form). The dataset contains both English and French versions; only English (`en.jsonl`) is used here.

### Scale
- **10,000** full synthetic insurance contracts (English)
- **0 duplicates**, **0 missing values** — perfectly clean
- Single split: `full_en`

### Text Length — Critical Finding
| Metric | Value |
|--------|------:|
| Mean word count | 25,209 |
| Median word count | 25,251 |
| Std dev word count | **238** |
| Min word count | 24,673 |
| Max word count | 25,576 |
| Mean estimated tokens | ~33,600 |
| Estimated pages per contract | ~50 |

> **These are by far the longest documents in the corpus** — more than 9× the length of Material Contracts (median 2,756 words). The extremely low standard deviation (238 words across 25,000-word documents) confirms these are **template-generated**: every contract follows the same structure with different synthetic field values.

### Token Window Fit
| Token Window | % That Fit |
|---|---:|
| 512 tokens | **0.0%** |
| 1,024 tokens | **0.0%** |
| 2,048 tokens | **0.0%** |
| 4,096 tokens | **0.0%** |
| 8,192 tokens | **0.0%** |

> **No contract fits in any standard context window.** Each document requires approximately 33,600 tokens. Even a 32k-context model would need to truncate ~5% of most contracts. Aggressive chunking is the only viable processing strategy.

### Document Structure
Each contract is a multi-section document following the Q.P.F. B1 standard form:

| Section | Description |
|---------|-------------|
| ISSUE / DECLARATIONS | Policy number, client number, policy term |
| TABLE OF CONTENTS | Structural index |
| Q.P.F. B1 — Owner's Form | Core policy terms |
| DEFINITIONS | Legal definitions |
| PRINCIPAL COVERAGE | Sections A–D (liability, medical, uninsured, property damage) |
| ADDITIONAL COVERAGES | Optional add-ons |
| ENDORSEMENTS | ~49 endorsements per contract (Q.E.F. forms) |
| CANADA INTER-PROVINCE CARD | Standard liability card |

> Endorsements dominate the document length — ~49 Q.E.F. endorsement forms per contract, each adding specific coverage modifications or exclusions.

### Key Insurance Terms (per 100 contracts)
| Term | Total Occurrences | Avg per Contract |
|------|------------------:|-----------------:|
| insured | 53,525 | 535 |
| endorsement | 32,465 | 325 |
| policy | 14,212 | 142 |
| coverage | 13,350 | 134 |
| premium | 5,885 | 59 |
| deductible | 5,698 | 57 |
| claim | 3,994 | 40 |
| liability | 3,761 | 38 |
| exclusion | 1,600 | 16 |
| collision | 2,300 | 23 |

### Language
Documents contain **mixed English and French** content: the core Q.P.F. form is in English but certain standardised form headers, certificate names, and regulatory labels appear in French (e.g., `CERTIFICAT D'ASSURANCE RESPONSABILITÉ AUTOMOBILE`, `VÉHICULE ASSURÉ`). This bilingual mixing is inherent to Quebec insurance regulation.

### Data Quality
- No missing values, no duplicates
- Fully synthetic — no PII, no real policy numbers
- Consistent structure across all 10,000 contracts
- Minor issue: some encoding artifacts from the original zip (`è`, `é` → `é`, `Ã©` etc.) in isolated French headers

### Role in the Pipeline

| Use | Verdict |
|-----|---------|
| Fine-tuning (reviewer or validator) | ❌ Not suitable — too long, wrong domain (auto insurance ≠ commercial contracts), template-generated reduces diversity |
| RAG corpus | ⚠️ Limited value — highly domain-specific (Quebec auto insurance), low overlap with commercial contract vocabulary. Use only if insurance contract queries are expected |
| Chunking experiments | ✅ Good stress test — consistent 50-page structure makes it ideal for validating chunking/overlap strategies before applying them to real contracts |
| Pretraining / domain adaptation | ⚠️ Marginal — useful for general legal language patterns but the Quebec insurance domain is narrow |

> **Bottom line:** RISCBAC is far less useful for Veridict than initially assumed. The extreme document length (33k tokens), narrow domain (Quebec auto insurance), synthetic nature, and bilingual mixing all reduce its value. Material Contracts (SEC) is a much better RAG corpus for commercial contract review. RISCBAC is best kept as a chunking stress-test tool.

---

## 7. Cross-Dataset Comparison

### Size and Coverage
| Dataset | Samples | Unique Labels | Granularity |
|---------|--------:|--------------|-------------|
| LEDGAR | 80,000 | 100 | Clause |
| Atticus (CUAD) | 13,823 | 41 | Clause |
| ContractNLI | 9,788 | 3 | Clause pair |
| RISCBAC | 10,000 | — | Full document |
| Material Contracts | 804 | 52 (doc types) | Full document |

> **LEDGAR dominates** the supervised dataset by 6× over CUAD. Any combined classifier will be heavily anchored in LEDGAR's provision vocabulary.

### Text Length by Dataset
| Dataset | Median Words | P95 Words | Avg Tokens |
|---------|------------:|----------:|----------:|
| CUAD | 31 | 95 | ~54 |
| LEDGAR | 84 | 270 | ~151 |
| ContractNLI (premise) | 75 | 243 | ~132 |
| Material Contracts | 2,756 | 6,500+ | ~4,341 |
| **RISCBAC** | **25,251** | **~25,500** | **~33,600** |

> There is a **800× scale difference** between CUAD clauses (median 31 words) and RISCBAC full contracts (median 25,251 words). RISCBAC is nearly 10× longer than Material Contracts and fits in no standard context window.

### Label Overlap Between CUAD and LEDGAR
The two supervised datasets use **different labeling schemes**. CUAD uses 41 specific clause categories (e.g., "Anti-Assignment") while LEDGAR uses 100 provision types (e.g., "Assignments"). There is **conceptual overlap but no direct label alignment** — they cannot be naively merged for a single classifier.

---

## 8. Token Budget and Imbalance Summary

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
| RISCBAC | 8,192 tokens | **0.0%** |
| RISCBAC | 32,768 tokens | **~0.0%** (need ~33,600 tokens) |

### Class Imbalance Summary

| Dataset | Imbalance Ratio | Severity |
|---------|----------------:|---------|
| LEDGAR | 169.7× | 🔴 Severe |
| CUAD | 94.6× | 🔴 Severe |
| ContractNLI | 4.1× | 🟡 Moderate |

Both supervised datasets have severe imbalance. This is a **critical issue** for LLM fine-tuning — without correction, models will over-predict frequent labels (e.g., "Financings", "Parties") and ignore rare but legally important ones.

---

## 9. Data Quality Flags

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
| 🟡 Domain mismatch | RISCBAC | Quebec auto insurance only — low overlap with commercial contract vocabulary |
| 🟡 Extreme length | RISCBAC | ~33,600 tokens per document — 0% fit in any standard context window; must chunk into ~65 segments |
| 🟡 Bilingual mixing | RISCBAC | French regulatory headers mixed into English documents — may confuse encoder models |
| 🟡 Low RAG value | RISCBAC | Synthetic + domain-narrow + template-generated → prioritise Material Contracts for RAG corpus |

**Minimum cleaning steps before any use:**
1. **CUAD:** Filter `is_impossible=True` rows; de-duplicate on `clause_text`
2. **LEDGAR:** Flag or merge bottom-quartile labels (<100 samples) — too few for reliable signal
3. **Material Contracts:** Drop rows where `full_text` is empty or under 100 words
4. **RISCBAC:** Skip for fine-tuning entirely; if used for RAG, chunk at 512 tokens with 128-token overlap (~65 chunks/contract = ~650,000 total chunks) and filter out French-only chunks

---

*Generated from EDA pipeline — Veridict Project, April 2026*
