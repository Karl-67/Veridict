"""MAUD (Merger Agreement Understanding Dataset) EDA Dashboard."""

import html as _html
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="MAUD EDA", page_icon="🤝", layout="wide")
st.title("🤝 MAUD — Merger Agreement Understanding Dataset — EDA")

st.markdown("""
**MAUD** is an expert-annotated reading comprehension dataset for merger agreements.

- **Source:** `theatticusproject/maud` (The Atticus Project / Harvard Law)
- **Scope:** 153 merger agreements annotated by law students supervised by experienced M&A lawyers
- **Format:** Each row is a (passage, question, answer) triple — 92 deal-point questions per contract
- **Coverage:** Material Adverse Effect definitions, Deal Protection provisions, Conditions to Closing,
  Operating Covenants, Remedies, and more
""")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "maud"
DATA_FILE = DATA_DIR / "maud.parquet"

CATEGORY_COLORS = {
    "Material Adverse Effect": "#e74c3c",
    "Deal Protection and Related Provisions": "#3498db",
    "Conditions to Closing": "#2ecc71",
    "Operating and Efforts Covenant": "#f39c12",
    "Knowledge": "#9b59b6",
    "General Information": "#1abc9c",
    "Remedies": "#e67e22",
}


@st.cache_data
def load_data():
    df = pd.read_parquet(DATA_FILE)
    df["word_count"] = df["text"].astype(str).str.split().str.len()
    df["est_tokens"] = (df["word_count"] / 0.75).astype(int)
    # length buckets
    df["length_bucket"] = pd.cut(
        df["word_count"],
        bins=[0, 30, 150, 99999],
        labels=["Short (≤30)", "Medium (31–150)", "Long (>150)"],
    )
    return df


if not DATA_FILE.exists():
    st.error("Dataset not found. Run `python scripts/download_datasets.py` first.")
    st.stop()

df = load_data()

# ── Section 1: Overview ──────────────────────────────────────────────────────

st.header("1. Overview")

n_rows = len(df)
n_contracts = df["contract_name"].nunique()
n_questions = df["question"].nunique() if "question" in df.columns else 0
n_categories = df["category"].nunique() if "category" in df.columns else 0
splits = df["split"].value_counts().to_dict() if "split" in df.columns else {}
unique_texts = df["text"].nunique()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Rows", f"{n_rows:,}")
col2.metric("Unique Contracts", f"{n_contracts:,}")
col3.metric("Unique Questions", f"{n_questions}")
col4.metric("Categories", f"{n_categories}")

col1b, col2b, col3b = st.columns(3)
col1b.metric("Unique Passage Texts", f"{unique_texts:,}")
col2b.metric("Avg Questions per Contract", f"{n_rows / n_contracts:.0f}")
col3b.metric("Splits", " | ".join(f"{k}: {v:,}" for k, v in splits.items()))

st.info(
    f"**Structural note:** MAUD has {n_rows:,} rows but only {unique_texts:,} unique passage texts "
    f"({n_rows - unique_texts:,} are repeated across multiple questions). "
    "Each contract passage is re-used to answer several of the 92 deal-point questions. "
    "For LLM labeling, send each unique passage once and broadcast labels back."
)

st.subheader("Data Sample")
cols_show = [c for c in ["contract_name", "category", "text_type", "question", "answer", "split"] if c in df.columns]
st.dataframe(df[cols_show].head(10), use_container_width=True)

# ── Section 2: Category Distribution ────────────────────────────────────────

st.header("2. Category Distribution")

if "category" in df.columns:
    cat_counts = df["category"].value_counts().reset_index()
    cat_counts.columns = ["Category", "Count"]
    cat_counts["Pct"] = (cat_counts["Count"] / n_rows * 100).round(1)

    col1, col2 = st.columns(2)
    with col1:
        fig = px.pie(
            cat_counts,
            values="Count",
            names="Category",
            title="Row Distribution by Category",
            color="Category",
            color_discrete_map=CATEGORY_COLORS,
        )
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig = px.bar(
            cat_counts.sort_values("Count"),
            x="Count",
            y="Category",
            orientation="h",
            title="Row Count by Category",
            color="Category",
            color_discrete_map=CATEGORY_COLORS,
            text="Pct",
        )
        fig.update_traces(texttemplate="%{text}%", textposition="outside")
        fig.update_layout(showlegend=False, height=350)
        st.plotly_chart(fig, use_container_width=True)

    imbalance = cat_counts["Count"].max() / cat_counts["Count"].min()
    st.warning(
        f"Category imbalance ratio: **{imbalance:.1f}×** "
        f"(Deal Protection {cat_counts.iloc[0]['Count']:,} rows vs Remedies {cat_counts.iloc[-1]['Count']:,}). "
        "Oversample rare categories (Knowledge, Remedies, General Information) when building the labeling pool."
    )

# ── Section 3: Question Type (text_type) Distribution ───────────────────────

st.header("3. Question Type Distribution (text_type)")

if "text_type" in df.columns:
    tt_counts = df["text_type"].value_counts().reset_index()
    tt_counts.columns = ["Text Type", "Count"]
    top_n = st.slider("Show top N question types", 10, min(50, len(tt_counts)), 20, key="maud_topn")
    display = tt_counts.head(top_n)

    fig = px.bar(
        display.sort_values("Count"),
        x="Count",
        y="Text Type",
        orientation="h",
        title=f"Top {top_n} Question Types by Row Count",
        color="Count",
        color_continuous_scale="Viridis",
    )
    fig.update_layout(height=max(500, top_n * 22))
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Each text_type corresponds to a specific M&A deal-point question. "
        "MAE Definition (12,960) dominates because every contract has an MAE clause. "
        "For LLM labeling, prioritise text types with < 500 rows — they represent rare deal structures."
    )

# ── Section 4: Text Length Distribution ─────────────────────────────────────

st.header("4. Text Length Distribution")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Mean Word Count", f"{df['word_count'].mean():.0f}")
col2.metric("Median Word Count", f"{df['word_count'].median():.0f}")
col3.metric("95th Percentile", f"{df['word_count'].quantile(0.95):.0f}")
col4.metric("Max Word Count", f"{df['word_count'].max():,}")

fig = px.histogram(
    df,
    x="word_count",
    nbins=100,
    title="Word Count Distribution (All MAUD Passages)",
    labels={"word_count": "Word Count"},
    color_discrete_sequence=["#3498db"],
)
fig.update_layout(bargap=0.05)
fig.add_vline(x=30, line_dash="dash", line_color="green",
              annotation_text="Short/Medium boundary (30 words)")
fig.add_vline(x=150, line_dash="dash", line_color="orange",
              annotation_text="Medium/Long boundary (150 words)")
st.plotly_chart(fig, use_container_width=True)

# By category
if "category" in df.columns:
    fig2 = px.box(
        df,
        x="category",
        y="word_count",
        color="category",
        title="Word Count Distribution by Category",
        labels={"word_count": "Word Count", "category": "Category"},
        color_discrete_map=CATEGORY_COLORS,
    )
    fig2.update_layout(xaxis_tickangle=-30, showlegend=False)
    st.plotly_chart(fig2, use_container_width=True)

# ── Section 5: Length Buckets ────────────────────────────────────────────────

st.header("5. Short / Medium / Long Clause Buckets")

bucket_counts = df["length_bucket"].value_counts().sort_index().reset_index()
bucket_counts.columns = ["Bucket", "Count"]
bucket_counts["Pct"] = (bucket_counts["Count"] / n_rows * 100).round(1)

col1, col2 = st.columns(2)
with col1:
    st.dataframe(bucket_counts, use_container_width=True, hide_index=True)
    st.warning(
        "**71.6% of MAUD passages are long (>150 words).** "
        "These exceed standard 512-token encoder windows. "
        "For LLM labeling, restrict to short+medium bucket (≤150 words) "
        "or use a model with ≥2k context."
    )
with col2:
    fig = px.bar(
        bucket_counts,
        x="Bucket",
        y="Count",
        title="Row Count by Length Bucket",
        color="Bucket",
        color_discrete_sequence=["#2ecc71", "#f39c12", "#e74c3c"],
        text="Pct",
    )
    fig.update_traces(texttemplate="%{text}%", textposition="outside")
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

# Bucket breakdown by category
if "category" in df.columns:
    bucket_cat = df.groupby(["category", "length_bucket"]).size().reset_index(name="Count")
    fig3 = px.bar(
        bucket_cat,
        x="category",
        y="Count",
        color="length_bucket",
        title="Length Bucket Distribution per Category",
        barmode="stack",
        color_discrete_sequence=["#2ecc71", "#f39c12", "#e74c3c"],
    )
    fig3.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig3, use_container_width=True)

# ── Section 6: Answer / Label Distribution ──────────────────────────────────

st.header("6. Answer Distribution")

if "answer" in df.columns:
    ans_counts = df["answer"].value_counts().reset_index()
    ans_counts.columns = ["Answer", "Count"]
    top_ans = st.slider("Show top N answers", 10, min(40, len(ans_counts)), 20, key="maud_ans")
    display_ans = ans_counts.head(top_ans)

    fig = px.bar(
        display_ans.sort_values("Count"),
        x="Count",
        y="Answer",
        orientation="h",
        title=f"Top {top_ans} Answer Values",
        color="Count",
        color_continuous_scale="Blues",
    )
    fig.update_layout(height=max(400, top_ans * 22))
    st.plotly_chart(fig, use_container_width=True)

    # Binary Yes/No breakdown
    yes_no = df["answer"].isin(["Yes", "No"]).sum()
    st.info(
        f"{yes_no:,} rows ({yes_no/n_rows*100:.1f}%) have binary Yes/No answers — "
        "useful for clause-present / clause-absent detection tasks. "
        "Remaining rows have structured multi-value answers representing specific deal terms."
    )

# ── Section 7: Data Quality — Duplicate Analysis ────────────────────────────

st.header("7. Data Quality — Structural Duplicates")

n_text_dupes = df.duplicated(subset=["text"]).sum()
n_pair_dupes = df.duplicated(subset=["text", "question"]).sum() if "question" in df.columns else 0
n_short = (df["word_count"] < 5).sum()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Rows", f"{n_rows:,}")
col2.metric("Unique Passage Texts", f"{unique_texts:,}",
            delta=f"{n_text_dupes:,} repeated")
col3.metric("Duplicate Passages (by text)", f"{n_text_dupes:,}",
            delta=f"{n_text_dupes/n_rows*100:.1f}%", delta_color="off")
col4.metric("Rows < 5 Words", f"{n_short:,}",
            delta=f"{n_short/n_rows*100:.2f}%", delta_color="inverse")

st.markdown("""
**Why so many duplicate passages?**

MAUD's design reuses each contract passage to answer multiple of the 92 deal-point questions.
For example, the MAE Definition clause from a merger agreement might appear as the passage for
10 different questions: "What is the time period of the MAE definition?", "Does it include
a pandemic carveout?", "Does it have a general economic condition carveout?", etc.

This is **not a data quality problem** — it is by design. The 79% duplication rate reflects
the richness of the annotation (many questions per passage), not noise.

**For LLM labeling:** deduplicate on `text` first, then label each unique passage once.
After labeling, join labels back to all rows sharing that passage.
""")

# Show average questions per passage
if "question" in df.columns:
    avg_q_per_passage = df.groupby("text")["question"].count().mean()
    st.metric("Average Questions per Unique Passage", f"{avg_q_per_passage:.1f}")

# ── Section 8: Per-Contract Analysis ────────────────────────────────────────

st.header("8. Per-Contract Analysis")

if "contract_name" in df.columns:
    contract_stats = df.groupby("contract_name").agg(
        total_rows=("text", "count"),
        unique_passages=("text", "nunique"),
        categories=("category", "nunique"),
    ).reset_index()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Contracts", f"{len(contract_stats):,}")
    col2.metric("Avg Rows per Contract", f"{contract_stats['total_rows'].mean():.0f}")
    col3.metric("Avg Unique Passages per Contract", f"{contract_stats['unique_passages'].mean():.0f}")

    fig = px.histogram(
        contract_stats,
        x="total_rows",
        nbins=30,
        title="Distribution of Row Count per Contract",
        labels={"total_rows": "Rows per Contract"},
        color_discrete_sequence=["#9b59b6"],
    )
    st.plotly_chart(fig, use_container_width=True)

    # Split distribution
    if "split" in df.columns:
        split_contracts = df.groupby("split")["contract_name"].nunique().reset_index()
        split_contracts.columns = ["Split", "Contracts"]
        split_rows = df["split"].value_counts().reset_index()
        split_rows.columns = ["Split", "Rows"]
        split_summary = split_contracts.merge(split_rows, on="Split")
        st.subheader("Split Distribution")
        st.dataframe(split_summary, use_container_width=True, hide_index=True)
        st.caption(
            "MAUD's official splits are document-level — no contract appears in two splits. "
            "Use these splits directly to avoid train-test leakage."
        )

# ── Section 9: Token Budget Analysis ────────────────────────────────────────

st.header("9. Token Budget Analysis")

windows = [256, 512, 1024, 2048, 4096]
budget_rows = []
for w in windows:
    fits = (df["est_tokens"] <= w).sum()
    pct = fits / n_rows * 100
    budget_rows.append({"Context Window": f"{w} tokens", "Fits": f"{fits:,}", "% of Rows": f"{pct:.1f}%"})

st.dataframe(pd.DataFrame(budget_rows), use_container_width=True, hide_index=True)

fig = px.bar(
    pd.DataFrame(budget_rows),
    x="Context Window",
    y=[float(r["% of Rows"].rstrip("%")) for r in budget_rows],
    title="% of MAUD Passages Fitting in Token Windows",
    labels={"y": "% of Rows"},
    text_auto=".1f",
    color=[float(r["% of Rows"].rstrip("%")) for r in budget_rows],
    color_continuous_scale="RdYlGn",
)
fig.update_layout(yaxis_range=[0, 105], showlegend=False)
st.plotly_chart(fig, use_container_width=True)

st.warning(
    "Only ~45% of MAUD passages fit within 512 tokens. "
    "For LLM labeling calls, restrict to passages ≤ 600 words, or use a model with ≥ 2k context. "
    "The medium-bucket filter (≤ 150 words) covers ~28% of rows but is LLM-budget-safe."
)

# ── Section 10: Role in the Pipeline ────────────────────────────────────────

st.header("10. Role in the Training Pipeline")

st.markdown("""
### MAUD in the Veridict Pipeline

| Attribute | Details |
|-----------|---------|
| **Task Role** | Expert Annotation / M&A Deal-Point QA |
| **Granularity** | Contract passage (long, ~375 median words) |
| **Use Case** | Fine-tuning an M&A-specialist reviewer agent |
| **Strengths** | Expert lawyer annotations, 92 deal-point questions, 153 contracts |
| **Weaknesses** | M&A only (no general commercial contracts), long passages need truncation |
| **Unique in corpus** | Only dataset with structured M&A deal-point coverage |

### Recommended Usage

- **Fine-tuning target:** M&A deal-point reviewer — classify deal structure and flag missing or unusual provisions
- **Input format for SFT:** `{contract_passage, deal_point_question, expected_answer}` → teach the model what a correct M&A answer looks like
- **RL pool:** MAUD is ideal for the RL curation pool — deal-point questions have clear right/wrong answers, making reward signal generation straightforward
- **Curation note:** filter to the short+medium bucket (≤ 150 words) for budget-safe LLM labeling; long passages may need summarisation or chunking first
- **Split strategy:** use MAUD's provided document-level train/val/test splits directly — they are already contract-safe

### Coverage Gaps MAUD Fills
CUAD and LEDGAR have limited M&A-specific content. MAUD is the only dataset in this corpus that covers:
- Material Adverse Effect (MAE) clause structures
- Termination fees and reverse termination fees
- Fiduciary-out provisions
- No-shop / go-shop deal protection
- Conditions precedent in acquisition agreements
""")

# ── Section 11: Contract Explorer ───────────────────────────────────────────

st.header("11. Contract Explorer")
st.markdown("Select a merger agreement and browse all its annotated deal-point Q&A pairs.")

all_contracts = sorted(df["contract_name"].unique())
selected_contract = st.selectbox("Choose a contract", all_contracts, key="maud_contract")

contract_rows = df[df["contract_name"] == selected_contract].copy()

col1, col2, col3 = st.columns(3)
col1.metric("Total Q&A rows", len(contract_rows))
col2.metric("Unique passages", contract_rows["text"].nunique())
col3.metric("Categories covered", contract_rows["category"].nunique() if "category" in contract_rows.columns else "—")

# Category filter
cat_filter = st.multiselect(
    "Filter by category",
    options=sorted(contract_rows["category"].unique()) if "category" in contract_rows.columns else [],
    default=sorted(contract_rows["category"].unique()) if "category" in contract_rows.columns else [],
    key="maud_cat_filter",
)
if cat_filter:
    contract_rows = contract_rows[contract_rows["category"].isin(cat_filter)]

# Show the Q&A table
show_cols = [c for c in ["category", "text_type", "question", "answer", "split"] if c in contract_rows.columns]
st.dataframe(contract_rows[show_cols].reset_index(drop=True), use_container_width=True, height=280)

# Expandable passage cards
st.subheader("Passage Cards")
st.caption("Each card shows the contract passage with its deal-point question and expert answer.")

n_cards = st.slider("Cards to show", 3, 20, 5, key="maud_cards")
card_rows = contract_rows.sample(min(n_cards, len(contract_rows)), random_state=42) if len(contract_rows) > 0 else contract_rows.head(0)

CAT_COLORS = {
    "Material Adverse Effect": "#e74c3c",
    "Deal Protection and Related Provisions": "#3498db",
    "Conditions to Closing": "#2ecc71",
    "Operating and Efforts Covenant": "#f39c12",
    "Knowledge": "#9b59b6",
    "General Information": "#1abc9c",
    "Remedies": "#e67e22",
}

for i, (_, row) in enumerate(card_rows.iterrows(), 1):
    cat = str(row.get("category", ""))
    border = CAT_COLORS.get(cat, "#aaa")
    q = str(row.get("question", row.get("text_type", "")))
    a = str(row.get("answer", ""))
    with st.expander(f"#{i}  {q[:80]}  →  **{a}**", expanded=(i == 1)):
        st.markdown(
            f'<div style="background:#fafafa;border-left:5px solid {border};'
            f'padding:10px 14px;border-radius:4px;font-size:0.83rem;'
            f'white-space:pre-wrap;font-family:monospace;max-height:300px;overflow-y:auto;color:#1a1a1a">'
            f'{_html.escape(str(row["text"]))}</div>',
            unsafe_allow_html=True,
        )
        col_a, col_b, col_c = st.columns(3)
        col_a.markdown(f"**Category:** {cat}")
        col_b.markdown(f"**Answer:** `{a}`")
        col_c.markdown(f"**Words:** {row.get('word_count', '—')}")

# ── Section 12: Deal-Point Question Browser ──────────────────────────────────

st.header("12. Deal-Point Question Browser")
st.markdown("Pick a deal-point question type and browse sample passages and answers across all contracts.")

all_text_types = sorted(df["text_type"].unique()) if "text_type" in df.columns else []
selected_tt = st.selectbox("Question type (text_type)", all_text_types, key="maud_tt")

tt_rows = df[df["text_type"] == selected_tt].copy() if "text_type" in df.columns else df.head(0)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total rows", len(tt_rows))
col2.metric("Unique contracts", tt_rows["contract_name"].nunique())
col3.metric("Unique answers", tt_rows["answer"].nunique() if "answer" in tt_rows.columns else "—")
col4.metric("Avg word count", f"{tt_rows['word_count'].mean():.0f}" if "word_count" in tt_rows.columns else "—")

# Answer distribution for this question type
if "answer" in tt_rows.columns:
    ans_dist = tt_rows["answer"].value_counts().reset_index()
    ans_dist.columns = ["Answer", "Count"]
    fig_ans = px.bar(
        ans_dist.head(15),
        x="Count",
        y="Answer",
        orientation="h",
        title=f'Answer distribution — "{selected_tt}"',
        color="Count",
        color_continuous_scale="Purples",
    )
    fig_ans.update_layout(height=max(300, min(15, len(ans_dist)) * 30), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig_ans, use_container_width=True)

# Sample passage cards
n_tt = st.slider("Samples to show", 3, 20, 5, key="maud_tt_n")
answer_filter = st.selectbox(
    "Filter by answer (optional)",
    ["(all)"] + sorted(tt_rows["answer"].unique().tolist()) if "answer" in tt_rows.columns else ["(all)"],
    key="maud_ans_filter",
)
tt_filtered = tt_rows if answer_filter == "(all)" else tt_rows[tt_rows["answer"] == answer_filter]

sample_tt = tt_filtered.sample(min(n_tt, len(tt_filtered)), random_state=42) if len(tt_filtered) > 0 else tt_filtered.head(0)

for i, (_, row) in enumerate(sample_tt.iterrows(), 1):
    a = str(row.get("answer", ""))
    contract = str(row.get("contract_name", ""))
    with st.expander(f"#{i}  {contract}  →  **{a}**", expanded=(i == 1)):
        st.markdown(
            f'<div style="background:#f8f0ff;border-left:5px solid #9b59b6;'
            f'padding:10px 14px;border-radius:4px;font-size:0.83rem;'
            f'white-space:pre-wrap;font-family:monospace;max-height:300px;overflow-y:auto;color:#1a1a1a">'
            f'{_html.escape(str(row["text"]))}</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"Contract: {contract}  |  Answer: {a}  |  Words: {row.get('word_count', '—')}")
