# Veridict — Dataset EDA Insights Report

**Date:** April 2026
**Scope:** CUAD, LEDGAR, ContractNLI, MAUD
**Total rows:** 142,842 | **Unique texts:** ~104,390

---

## 1. Dataset Overview

| Dataset | Rows | Unique Texts | Contracts | Labels / Categories | Granularity |
|---------|-----:|-------------:|----------:|---------------------|-------------|
| CUAD | 13,823 | ~11,683 | 510 | 41 clause types | Clause |
| LEDGAR | 80,000 | 80,000 | — | 100 provision types | Clause |
| ContractNLI | 9,788 | 4,703 premises | — | 3 (entail/neutral/contradict) | Premise–Hypothesis pair |
| MAUD | 39,231 | 8,226 | 153 | 7 categories, 92 questions | Contract passage (M&A) |

> **Key planning number:** 142,842 total rows collapse to ~104,390 unique texts after deduplication. After quality filters and boilerplate archiving, the realistic LLM-labeling budget pool is **~15,000–20,000 items**.

---

## 2. Atticus (CUAD)

### Scale
- **13,823** clause rows from **510** commercial contracts
- **41** distinct clause types (CUAD question categories)
- **27.1** clauses per contract on average (range: 2–97)

### Top 10 Clause Types by Count

| Clause Type | Count |
|-------------|------:|
| Parties | 2,554 |
| License Grant | 777 |
| Cap On Liability | 672 |
| Anti-Assignment | 654 |
| Audit Rights | 643 |
| Insurance | 560 |
| Document Name | 521 |
| Agreement Date | 476 |
| Expiration Date | 467 |
| Governing Law | 464 |

> Imbalance ratio: **94.6×**. After taxonomy mapping to 13 issue types this drops significantly — see Section 7.

### Word Count Distribution

| Metric | Value |
|--------|------:|
| Mean | 40.7 words |
| Median | 31 words |
| Std dev | 43.4 |
| 25th pct | 5 words |
| 75th pct | 57 words |
| Max | 479 words |

### Length Buckets

| Bucket | Count | % |
|--------|------:|--:|
| Short (≤ 30 words) | 6,847 | 49.5% |
| Medium (31–150 words) | 6,619 | 47.9% |
| Long (> 150 words) | 357 | 2.6% |

> **49.5% short** — most are partial answer spans from `is_impossible=True` QA rows (party names, dates, single numbers), not full clauses. These are noise for fine-tuning.

### Token Fit

| Window | % Fits |
|--------|-------:|
| 128 tokens | 91.5% |
| 256 tokens | 98.7% |
| 512 tokens | 99.9% |
| 1024 tokens | 100.0% |

### Data Quality

| Issue | Count | % |
|-------|------:|--:|
| Exact text duplicates | 2,140 | 15.5% |
| Rows < 5 words | 3,106 | 22.4% |
| Rows < 10 words | 3,906 | 28.3% |
| Empty rows | 0 | 0.0% |

**Usable pool after cleaning (wc ≥ 10 + dedup): ~8,695 rows.**

---

## 3. LEDGAR

### Scale
- **80,000** provision rows, no contract-level grouping
- **100** active label types (indices 100–130 in the raw label list are unreachable — never appear in data)
- Splits: 60,000 train / 10,000 validation / 10,000 test

### Top 15 Labels

| Label | Count |
|-------|------:|
| Governing Laws | 4,243 |
| Counterparts | 3,346 |
| Notices | 3,313 |
| Entire Agreements | 3,105 |
| Severability | 2,552 |
| Survival | 1,951 |
| Amendments | 1,948 |
| Assignments | 1,730 |
| Expenses | 1,577 |
| Terms | 1,511 |
| Taxes | 1,488 |
| Insurances | 1,441 |
| Terminations | 1,423 |
| Compliance With Laws | 1,335 |
| Litigations | 1,329 |

### Bottom 10 Labels (rare)

| Label | Count |
|-------|------:|
| Consent To Jurisdiction | 243 |
| Approvals | 230 |
| Costs | 205 |
| Venues | 170 |
| Sanctions | 156 |
| Anti-Corruption Laws | 155 |
| Powers | 153 |
| Qualifications | 60 |
| Assigns | 38 |
| Books | 25 |

> Imbalance ratio: **169.7×**. Top labels are almost all boilerplate. Estimated **~28,738 rows (35.9%)** are boilerplate — archive for RAG, not SFT.

### Word Count Distribution

| Metric | Value |
|--------|------:|
| Mean | 113 words |
| Median | 84 words |
| Std dev | 96 |
| 25th pct | 47 words |
| 75th pct | 147 words |
| Max | 1,215 words |

### Length Buckets

| Bucket | Count | % |
|--------|------:|--:|
| Short (≤ 30 words) | 9,480 | 11.8% |
| Medium (31–150 words) | 51,240 | 64.0% |
| Long (> 150 words) | 19,280 | 24.1% |

> **Healthiest distribution in the corpus** — 64% medium, 24% long. Right shape for clause-level SFT.

### Token Fit

| Window | % Fits |
|--------|-------:|
| 256 tokens | 84.6% |
| 512 tokens | 97.7% |
| 1024 tokens | 99.9% |

### Data Quality

| Issue | Count | % |
|-------|------:|--:|
| Exact duplicates | 0 | 0.0% |
| Rows < 5 words | 20 | 0.025% |

> Cleanest dataset in the corpus. No deduplication needed. **After boilerplate archiving: ~51,262 SFT candidates.**

---

## 4. ContractNLI

### Scale
- **9,788** premise–hypothesis pairs from NDA-style contracts
- **4,703** unique premises (same premise paired with multiple hypotheses by design)
- Splits: 6,819 train / 978 dev / 1,991 test

### Label Distribution

| Label | Count | % |
|-------|------:|--:|
| Entailment | 4,539 | 46.4% |
| Neutral | 4,146 | 42.4% |
| Contradiction | 1,103 | 11.3% |

> Imbalance ratio: **4.1×** — most balanced dataset. Contradiction is underrepresented; **oversample to ~30%** for validator training.

### Contradiction Fraction by Split

| Split | Rows | Contradiction | % |
|-------|-----:|-------------:|--:|
| train | 6,819 | 804 | 11.8% |
| dev | 978 | 89 | 9.1% |
| test | 1,991 | 210 | 10.5% |

> Consistent ~10–12% across all splits — stratification is correct.

### Word Count

| | Premise | Hypothesis |
|---|--------:|----------:|
| Mean | 98.7 words | 12.8 words |
| Median | 75 words | 13 words |
| Max | 429 words | 23 words |

> Hypotheses are short fixed-form statements (7–23 words). Premises are the variable-length contract clause passages.

### Length Buckets (Premise)

| Bucket | Count | % |
|--------|------:|--:|
| Short (≤ 30 words) | 963 | 9.8% |
| Medium (31–150 words) | 7,030 | 71.8% |
| Long (> 150 words) | 1,795 | 18.3% |

### Token Fit (Premise + Hypothesis Combined)

| Window | % Fits |
|--------|-------:|
| 256 tokens | 87.4% |
| 512 tokens | 99.2% |
| 1024 tokens | 100.0% |

> 99.2% fit in 512 tokens — ideal for encoder-style NLI fine-tuning.

### Data Quality

| Issue | Count | % |
|-------|------:|--:|
| Duplicate premises (structural) | 5,085 | 52.0% |
| Duplicate pairs | 1,361 | 13.9% |

> Structural — same clause paired with multiple hypotheses. For LLM labeling: **4,703 unique premises** to process.

---

## 5. MAUD

### Scale
- **39,231** rows across **153** merger agreements and **92** deal-point questions
- **8,226** unique passage texts; 79% duplication is structural (same passage answers multiple questions)
- Average **4.8 questions per unique passage**
- **22** distinct text types (subtypes within categories)
- Splits: 25,827 train / 6,753 validation / 6,651 test — all **document-level** (every contract appears in each split's labeling, no contract leaks across splits)

### Category Distribution

| Category | Rows | % |
|----------|-----:|--:|
| Deal Protection and Related Provisions | 14,708 | 37.5% |
| Material Adverse Effect | 12,960 | 33.0% |
| Conditions to Closing | 7,761 | 19.8% |
| Operating and Efforts Covenant | 2,461 | 6.3% |
| Knowledge | 669 | 1.7% |
| General Information | 342 | 0.9% |
| Remedies | 330 | 0.8% |

> Category imbalance ratio: **44.6×**. Oversample Knowledge, Remedies, General Information in the labeling pool.

### Top 10 Text Types

| Text Type | Rows |
|-----------|-----:|
| MAE Definition | 12,960 |
| Accuracy of Target R&W Closing Condition | 7,341 |
| Tail Period & Acquisition Proposal Details | 5,509 |
| Limitations on FTR Exercise | 1,722 |
| Fiduciary exception to COR covenant | 1,603 |
| Agreement provides for matching rights (COR) | 1,317 |
| Ordinary course covenant | 1,154 |
| Intervening Event Definition | 1,082 |
| Fiduciary exception: Board determination (no-shop) | 892 |
| Superior Offer Definition | 883 |

### Word Count Distribution

| Metric | Value |
|--------|------:|
| Mean | 452.6 words |
| Median | 375 words |
| Std dev | 371.9 |
| 25th pct | 132 words |
| 75th pct | 707 words |
| Max | 2,661 words |

### Median Word Count by Category

| Category | Median Words | Notes |
|----------|------------:|-------|
| Material Adverse Effect | 697 | ~930 tokens — needs 2k model |
| Conditions to Closing | 245 | borderline 512 token |
| Deal Protection | 186 | fits in 512 |
| General Information | 134 | fits in 256 |
| Remedies | 125 | fits in 256 |
| Operating Covenant | 119 | fits in 256 |
| Knowledge | 47 | fits in 128 — **best for budget labeling** |

### Length Buckets

| Bucket | Count | % |
|--------|------:|--:|
| Short (≤ 30 words) | 361 | 0.9% |
| Medium (31–150 words) | 10,799 | 27.5% |
| Long (> 150 words) | 28,071 | 71.6% |

### Token Fit

| Window | % Fits |
|--------|-------:|
| 256 tokens | 35.3% |
| 512 tokens | 50.3% |
| 1024 tokens | 82.0% |
| 2048 tokens | 98.9% |
| 4096 tokens | 100.0% |

> Only 50.3% fit in 512 tokens. Use a **2k-context model** (covers 98.9%) or restrict to medium bucket (≤150 words) for budget labeling.

### Answer Distribution (Top 5)

| Answer | Count |
|--------|------:|
| Yes | 5,559 |
| No | 3,796 |
| Same/Different AP — sign during Tail Period (no closing req.) | 2,060 |
| General R&Ws | 864 |
| War or terrorism, Natural disaster | 815 |

> **23.8% binary Yes/No** (9,355 rows) — directly usable for clause-present / clause-absent detection.

### Data Quality

| Issue | Count | % |
|-------|------:|--:|
| Exact text duplicates (structural) | 31,005 | 79.0% |
| Text + question duplicates | 15,908 | 40.6% |
| Rows < 5 words | 361 | 0.9% |

> All duplicates are structural. After dedup: **8,226 unique passages**. After medium-bucket filter: **3,336 budget-safe passages**.

---

## 6. Cross-Dataset Comparison

### Text Length by Dataset

| Dataset | Median Words | P95 Words | Median Tokens (est.) |
|---------|------------:|----------:|---------------------:|
| CUAD | 31 | 95 | ~41 |
| LEDGAR | 84 | 270 | ~112 |
| ContractNLI (premise) | 75 | 243 | ~100 |
| MAUD | 375 | ~1,050 | ~500 |

> **12× length gap** between CUAD and MAUD — cannot use the same prompt template or context budget.

### Cross-Dataset Exact Text Overlap

| Pair | Matches |
|------|--------:|
| CUAD vs LEDGAR | 11 |
| CUAD vs ContractNLI | 0 |
| CUAD vs MAUD | 0 |
| LEDGAR vs ContractNLI | 0 |
| LEDGAR vs MAUD | 0 |
| ContractNLI vs MAUD | 0 |

> **Cross-dataset leakage is negligible.** All four datasets come from distinct source collections. The only leakage risk is intra-dataset (splitting rows from the same contract across train/test), not cross-dataset.

---

## 7. Token Budget and Imbalance Summary

### Token Fit per Dataset

| Dataset | 256 tok | 512 tok | 1024 tok | 2048 tok |
|---------|--------:|--------:|---------:|---------:|
| CUAD | 98.7% | 99.9% | 100% | 100% |
| LEDGAR | 84.6% | 97.7% | 99.9% | 100% |
| ContractNLI (pair) | 87.4% | 99.2% | 100% | 100% |
| MAUD | 35.3% | 50.3% | 82.0% | 98.9% |

### Class Imbalance

| Dataset | Ratio | Severity | Recommended Fix |
|---------|------:|----------|-----------------|
| LEDGAR | 169.7× | 🔴 Severe | Archive boilerplate; cap dominant labels at 1,500 |
| CUAD | 94.6× | 🔴 Severe | Taxonomy mapping to 13 types; cap per type |
| MAUD (categories) | 44.6× | 🔴 Severe | Oversample Knowledge, Remedies, General Info |
| ContractNLI | 4.1× | 🟡 Moderate | Oversample contradiction to ~30% |

### Estimated Labeling Pool (after dedup + quality filter)

| Dataset | Usable Rows | Notes |
|---------|------------:|-------|
| CUAD | ~8,695 | wc ≥ 10, deduplicated |
| LEDGAR (non-boilerplate) | ~51,262 | ~28,738 boilerplate rows archived |
| ContractNLI | ~4,703 | deduplicated premises |
| MAUD (medium bucket, deduped) | ~3,336 | ≤150 words — budget-safe |
| MAUD (all, deduped) | ~8,226 | needs 2k model |
| **Total (conservative)** | **~67,996** | MAUD medium only |

> First labeling batch recommendation: **8,000–12,000 items** drawn from CUAD medium bucket + LEDGAR non-boilerplate (capped per issue type) + ContractNLI unique premises + MAUD Knowledge/Remedies/Operating Covenant passages (shortest categories first).

---

## 8. Data Quality Flags

| Flag | Dataset | Detail | Action |
|------|---------|--------|--------|
| 🔴 Imbalance 94.6× | CUAD | Parties (2,554) vs bottom label | Taxonomy map + cap at 1,500/type |
| 🔴 Imbalance 169.7× | LEDGAR | Governing Laws (4,243) vs Books (25) | Archive boilerplate; cap dominant labels |
| 🔴 Category imbalance 44.6× | MAUD | Deal Protection (14,708) vs Remedies (330) | Oversample rare categories |
| 🟡 Contradiction underrepresented | ContractNLI | ~11% across all splits | Oversample to ~30% for validator SFT |
| 🟡 49.5% short/noise rows | CUAD | 6,847 rows ≤ 30 words — is_impossible spans | Filter wc < 10 |
| 🟡 35.9% boilerplate | LEDGAR | ~28,738 low-risk boilerplate rows | Archive for RAG corpus |
| 🟡 71.6% long passages | MAUD | 28,071 rows > 150 words | Restrict to medium bucket or use 2k model |
| 🟡 MAE Definition length | MAUD | Median 697 words (~930 tokens) | Exclude from 512-token budget labeling |
| 🟢 LEDGAR duplicates | LEDGAR | 0 exact duplicates | No action |
| 🟢 Cross-dataset leakage | All | Only 11 matches (CUAD↔LEDGAR) | No action |
| 🟢 MAUD official splits | MAUD | Document-level — no contract appears in two splits | Use as-is |

### Minimum Cleaning Steps Before Labeling

1. **CUAD** — drop `is_impossible=True` rows; filter `wc < 10`; deduplicate on `clause_text`
2. **LEDGAR** — decode integer labels to names; archive boilerplate labels to RAG corpus; cap dominant issue-type groups at 1,500 rows each
3. **ContractNLI** — use provided splits as-is; oversample contradiction to ~30% in training mix
4. **MAUD** — deduplicate on `text`; for budget labeling restrict to `wc ≤ 150`; for full labeling use ≥ 2k context model; drop the 361 rows < 5 words

---

*Generated from EDA pipeline — Veridict Project, April 2026*
