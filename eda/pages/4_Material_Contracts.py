"""Material Contracts (SEC EDGAR) Dataset EDA Dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Material Contracts EDA", page_icon="📋", layout="wide")
st.title("📋 Material Contracts (SEC EDGAR) — EDA")

st.markdown("""
**Material Contracts Corpus** contains 804 real contracts filed with the SEC via EDGAR.
Each record includes the full contract text plus structured metadata extracted by GPT-4o.

*Source: `chenghao/sec-material-contracts-qa`*
""")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "material"
DATA_FILE = DATA_DIR / "sec_contracts.parquet"


@st.cache_data
def load_data():
    df = pd.read_parquet(DATA_FILE)
    # Use full_text as the primary text column
    text_col = "full_text" if "full_text" in df.columns else "file_content"
    df["_text"] = df[text_col].astype(str)
    df["word_count"] = df["_text"].str.split().str.len()
    df["char_count"] = df["_text"].str.len()
    df["est_tokens"] = (df["word_count"] / 0.75).astype(int)
    # Estimate pages (rough: ~500 words per page)
    df["est_pages"] = (df["word_count"] / 500).round(1)
    return df, text_col


if not DATA_FILE.exists():
    st.error("Dataset not found. Run `python scripts/download_datasets.py` first.")
    st.stop()

df, text_col = load_data()

# ── Section 1: Overview ─────────────────────────────────────────────────────

st.header("1. Overview")

n_total = len(df)
n_doc_types = df["doc_type"].nunique() if "doc_type" in df.columns else 0
n_companies = df["name"].nunique() if "name" in df.columns else 0
avg_words = df["word_count"].mean()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Contracts", f"{n_total:,}")
col2.metric("Unique Document Types", f"{n_doc_types}")
col3.metric("Unique Companies", f"{n_companies:,}")
col4.metric("Avg Word Count", f"{avg_words:,.0f}")

st.subheader("Data Sample (Text + Key Metadata)")
preview_cols = [c for c in ["name", "doc_type", "type", "date", "governing_law", "word_count"] if c in df.columns]
st.dataframe(df[preview_cols].head(10), use_container_width=True)

# ── Section 2: Missing Data Analysis ────────────────────────────────────────

st.header("2. Missing Data Analysis")

key_cols = [c for c in [
    "full_text", "doc_type", "name", "date", "governing_law",
    "party_name", "counterparty_name", "contract_value",
    "agreement_date", "expiration_date",
] if c in df.columns]

null_counts = df[key_cols].isnull().sum()
null_pct = (null_counts / n_total * 100).round(2)
missing_df = pd.DataFrame({"Null Count": null_counts, "Null %": null_pct}).sort_values("Null %", ascending=False)

fig = px.bar(
    missing_df.reset_index().rename(columns={"index": "Column"}),
    x="Column",
    y="Null %",
    title="Missing Data % by Column",
    color="Null %",
    color_continuous_scale="RdYlGn_r",
    text_auto=".1f",
)
fig.update_layout(xaxis_tickangle=-45)
st.plotly_chart(fig, use_container_width=True)

st.dataframe(missing_df, use_container_width=True)

# ── Section 3: Document Type Distribution ───────────────────────────────────

st.header("3. Document Type Distribution")

if "doc_type" in df.columns:
    doc_type_counts = df["doc_type"].value_counts().reset_index()
    doc_type_counts.columns = ["Document Type", "Count"]

    top_n = st.slider("Show top N document types", 5, min(50, len(doc_type_counts)), 20)
    display = doc_type_counts.head(top_n)

    fig = px.bar(
        display,
        x="Count",
        y="Document Type",
        orientation="h",
        title=f"Top {top_n} Document Types",
        color="Count",
        color_continuous_scale="Viridis",
        text_auto=True,
    )
    fig.update_layout(height=max(400, top_n * 22), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

if "type" in df.columns:
    filing_counts = df["type"].value_counts().reset_index()
    filing_counts.columns = ["Filing Type", "Count"]
    col1, col2 = st.columns(2)
    with col1:
        fig = px.pie(
            filing_counts,
            values="Count",
            names="Filing Type",
            title="SEC Filing Type Distribution",
        )
        st.plotly_chart(fig, use_container_width=True)

# ── Section 4: Text Length Distribution ─────────────────────────────────────

st.header("4. Text Length Distribution")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Mean Word Count", f"{df['word_count'].mean():,.0f}")
col2.metric("Median Word Count", f"{df['word_count'].median():,.0f}")
col3.metric("Min Word Count", f"{df['word_count'].min():,}")
col4.metric("Max Word Count", f"{df['word_count'].max():,}")

col1, col2, col3 = st.columns(3)
col1.metric("Mean Est. Pages", f"{df['est_pages'].mean():.1f}")
col2.metric("Median Est. Pages", f"{df['est_pages'].median():.1f}")
col3.metric("Max Est. Pages", f"{df['est_pages'].max():.0f}")

fig = px.histogram(
    df,
    x="word_count",
    nbins=60,
    title="Word Count Distribution (Full Contract Text)",
    labels={"word_count": "Word Count"},
    color_discrete_sequence=["#e67e22"],
)
fig.update_layout(bargap=0.05)
st.plotly_chart(fig, use_container_width=True)

# Estimated pages histogram
fig = px.histogram(
    df,
    x="est_pages",
    nbins=40,
    title="Estimated Page Count Distribution (~500 words/page)",
    labels={"est_pages": "Estimated Pages"},
    color_discrete_sequence=["#9b59b6"],
)
st.plotly_chart(fig, use_container_width=True)

# ── Section 5: Metadata Analysis ────────────────────────────────────────────

st.header("5. Metadata Analysis")

# Governing law
if "governing_law" in df.columns:
    gov_law = df["governing_law"].dropna().value_counts().head(15).reset_index()
    gov_law.columns = ["Governing Law", "Count"]
    fig = px.bar(
        gov_law,
        x="Count",
        y="Governing Law",
        orientation="h",
        title="Top 15 Governing Laws",
        color="Count",
        color_continuous_scale="Blues",
        text_auto=True,
    )
    fig.update_layout(yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

# Auto renewal
if "auto_renewal" in df.columns:
    ar = df["auto_renewal"].dropna().value_counts().reset_index()
    ar.columns = ["Auto Renewal", "Count"]
    col1, col2 = st.columns(2)
    with col1:
        fig = px.pie(ar, values="Count", names="Auto Renewal", title="Auto Renewal Distribution")
        st.plotly_chart(fig, use_container_width=True)

# Filing date over time
if "date" in df.columns:
    df["_year"] = pd.to_datetime(df["date"], errors="coerce").dt.year
    year_counts = df["_year"].dropna().value_counts().sort_index().reset_index()
    year_counts.columns = ["Year", "Count"]
    with col2:
        fig = px.bar(
            year_counts,
            x="Year",
            y="Count",
            title="Contracts by Filing Year",
            color_discrete_sequence=["#2980b9"],
        )
        st.plotly_chart(fig, use_container_width=True)

# ── Section 6: Token Budget Analysis ────────────────────────────────────────

st.header("6. Token Budget Analysis")

st.warning("""
**Note:** Material contracts are full-length legal documents.
Most contracts will exceed standard LLM context windows and require chunking.
""")

windows = [512, 1024, 2048, 4096, 8192, 16384]
budget_rows = []
for w in windows:
    fits = (df["est_tokens"] <= w).sum()
    pct = fits / n_total * 100
    budget_rows.append({"Window": f"{w:,} tokens", "Fits": fits, "% of Data": round(pct, 1)})

st.dataframe(pd.DataFrame(budget_rows), use_container_width=True)

fig = px.bar(
    pd.DataFrame(budget_rows),
    x="Window",
    y="% of Data",
    title="% of Contracts Fitting in Token Windows",
    text_auto=".1f",
    color="% of Data",
    color_continuous_scale="RdYlGn",
)
fig.update_layout(yaxis_range=[0, 105])
st.plotly_chart(fig, use_container_width=True)

# ── Section 7: Data Quality ──────────────────────────────────────────────────

st.header("7. Data Quality")

n_empty = (df["word_count"] < 10).sum()
n_dup = df.duplicated(subset=["_text"]).sum() if "_text" in df.columns else 0
n_short = (df["word_count"] < 100).sum()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Contracts", f"{n_total:,}")
col2.metric("Duplicates", f"{n_dup:,}", delta=f"{n_dup/n_total*100:.1f}%", delta_color="inverse")
col3.metric("Very Short (<100 words)", f"{n_short:,}", delta=f"{n_short/n_total*100:.1f}%", delta_color="inverse")
col4.metric("Near-Empty (<10 words)", f"{n_empty:,}", delta=f"{n_empty/n_total*100:.1f}%", delta_color="inverse")

# ── Section 8: LLM Training Role ────────────────────────────────────────────

st.header("8. LLM Training Role")

st.markdown("""
### Material Contracts in the Training Pipeline

| Attribute | Details |
|-----------|---------|
| **Task Role** | Raw / Pretraining / Document-level |
| **Format** | Full contract documents |
| **Use Case** | Pretraining, document embedding, retrieval-augmented generation |
| **Strengths** | Real SEC filings, rich metadata, diverse document types |
| **Weaknesses** | Very long documents require chunking, no clause-level labels |

### Recommended Usage
- **Pretraining / continued pretraining**: Use `full_text` as raw text input
- **Chunking strategy**: Split into 512-token overlapping windows
- **Retrieval**: Embed full contracts for similarity search
- **Metadata extraction**: Use structured fields to build a labeled subset
""")
