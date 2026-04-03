"""RISCBAC Dataset EDA Dashboard (Synthetic Insurance Contracts)."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="RISCBAC EDA", page_icon="🚗", layout="wide")
st.title("🚗 RISCBAC Dataset — EDA")

st.markdown("""
**RISCBAC** (Realistic Insurance Synthetic Bilingual Automobile Contract) contains 10,000 synthetic
automobile insurance contracts generated based on the Quebec regulatory insurance form.

Contracts are bilingual (French + English). This dashboard uses the **English** version.

*Source: `davebulaval/RISCBAC`, config `en`*
""")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "riscbac"
DATA_FILE = DATA_DIR / "riscbac.parquet"


@st.cache_data
def load_data():
    df = pd.read_parquet(DATA_FILE)
    return df


def find_text_column(df: pd.DataFrame) -> str:
    """Auto-detect the primary text column."""
    for candidate in ["text", "contract", "content", "contract_text", "document"]:
        if candidate in df.columns:
            return candidate
    # Fall back to first string column with long content
    for col in df.columns:
        if df[col].dtype == object:
            avg_len = df[col].astype(str).str.len().mean()
            if avg_len > 200:
                return col
    return df.columns[0]


if not DATA_FILE.exists():
    st.warning("""
**RISCBAC not yet downloaded.**

The GRAAL server hosting this dataset may be temporarily unavailable.

**To download manually:**
1. Visit: https://graal.ift.ulaval.ca/public/datasets/riscbac.zip
2. Save to: `data/riscbac/riscbac.zip`
3. Re-run: `python scripts/download_datasets.py`

Alternatively, generate data with the [RISC Python package](https://github.com/GRAAL-Research/risc).
""")
    st.stop()

df = load_data()
text_col = find_text_column(df)

# Compute text stats
df["word_count"] = df[text_col].astype(str).str.split().str.len()
df["char_count"] = df[text_col].astype(str).str.len()
df["est_tokens"] = (df["word_count"] / 0.75).astype(int)
df["est_pages"] = (df["word_count"] / 500).round(1)

# ── Section 1: Overview ─────────────────────────────────────────────────────

st.header("1. Overview")

n_total = len(df)
n_cols = len(df.columns)
all_columns = list(df.columns)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Contracts", f"{n_total:,}")
col2.metric("Columns", f"{n_cols}")
col3.metric("Avg Word Count", f"{df['word_count'].mean():,.0f}")
col4.metric("Avg Est. Pages", f"{df['est_pages'].mean():.1f}")

st.subheader("Dataset Columns")
col_info = pd.DataFrame({
    "Column": df.columns,
    "Type": [str(df[c].dtype) for c in df.columns],
    "Non-Null": [df[c].notna().sum() for c in df.columns],
    "Sample Value": [str(df[c].iloc[0])[:80] + "..." if len(str(df[c].iloc[0])) > 80 else str(df[c].iloc[0]) for c in df.columns],
})
st.dataframe(col_info, use_container_width=True)

st.subheader("Contract Text Sample")
st.text_area(
    "First contract (truncated to 1000 chars)",
    value=str(df[text_col].iloc[0])[:1000],
    height=200,
)

# ── Section 2: Missing Data Analysis ────────────────────────────────────────

st.header("2. Missing Data Analysis")

null_counts = df.isnull().sum()
null_pct = (null_counts / n_total * 100).round(2)
missing_df = pd.DataFrame({"Null Count": null_counts, "Null %": null_pct})
missing_df = missing_df[missing_df["Null Count"] > 0]

if missing_df.empty:
    st.success("No missing values detected!")
else:
    st.dataframe(missing_df.sort_values("Null %", ascending=False), use_container_width=True)

# ── Section 3: Text Length Distribution ─────────────────────────────────────

st.header("3. Text Length Distribution")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Mean Words", f"{df['word_count'].mean():,.0f}")
col2.metric("Median Words", f"{df['word_count'].median():,.0f}")
col3.metric("Min Words", f"{df['word_count'].min():,}")
col4.metric("Max Words", f"{df['word_count'].max():,}")

col1, col2, col3 = st.columns(3)
col1.metric("Mean Est. Pages", f"{df['est_pages'].mean():.1f}")
col2.metric("Median Est. Pages", f"{df['est_pages'].median():.1f}")
col3.metric("Max Est. Pages", f"{df['est_pages'].max():.0f}")

fig = px.histogram(
    df,
    x="word_count",
    nbins=80,
    title="Word Count Distribution",
    labels={"word_count": "Word Count"},
    color_discrete_sequence=["#e74c3c"],
)
fig.update_layout(bargap=0.05)
st.plotly_chart(fig, use_container_width=True)

fig = px.histogram(
    df,
    x="est_pages",
    nbins=50,
    title="Estimated Page Count Distribution (~500 words/page)",
    labels={"est_pages": "Estimated Pages"},
    color_discrete_sequence=["#c0392b"],
)
st.plotly_chart(fig, use_container_width=True)

# ── Section 4: Structured Fields Distribution ────────────────────────────────

st.header("4. Structured Fields Analysis")

# Show distributions for categorical columns (excluding text and word count cols)
skip_cols = {text_col, "word_count", "char_count", "est_tokens", "est_pages", "split"}
cat_cols = [
    c for c in df.columns
    if c not in skip_cols
    and df[c].dtype == object
    and df[c].nunique() < 50
    and df[c].nunique() > 1
]
num_cols = [
    c for c in df.columns
    if c not in skip_cols
    and df[c].dtype in ("int64", "float64", "int32")
    and c not in ("word_count", "char_count", "est_tokens", "est_pages")
]

if cat_cols:
    selected_cat = st.selectbox("Select categorical field to visualize", cat_cols)
    val_counts = df[selected_cat].value_counts().reset_index()
    val_counts.columns = [selected_cat, "Count"]
    fig = px.bar(
        val_counts.head(30),
        x="Count",
        y=selected_cat,
        orientation="h",
        title=f"Distribution of '{selected_cat}'",
        color="Count",
        color_continuous_scale="Viridis",
        text_auto=True,
    )
    fig.update_layout(height=max(300, len(val_counts.head(30)) * 25), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No categorical fields with < 50 unique values found (besides text).")

if num_cols:
    selected_num = st.selectbox("Select numeric field to visualize", num_cols)
    fig = px.histogram(
        df,
        x=selected_num,
        nbins=50,
        title=f"Distribution of '{selected_num}'",
        color_discrete_sequence=["#8e44ad"],
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Section 5: Repetition & Synthetic Structure Analysis ────────────────────

st.header("5. Synthetic Structure Analysis")

n_dup = df.duplicated(subset=[text_col]).sum()
n_near_identical = (df["word_count"] == df["word_count"].mode()[0]).sum() if not df["word_count"].mode().empty else 0
word_count_std = df["word_count"].std()
word_count_cv = word_count_std / df["word_count"].mean() * 100

col1, col2, col3, col4 = st.columns(4)
col1.metric("Exact Duplicates", f"{n_dup:,}")
col2.metric("Word Count Std Dev", f"{word_count_std:,.0f}")
col3.metric("Coefficient of Variation", f"{word_count_cv:.1f}%")
col4.metric("Most Common Word Count", f"{df['word_count'].mode().iloc[0]:,}")

st.markdown(f"""
**Observation:** A low coefficient of variation ({word_count_cv:.1f}%) indicates that
synthetic contracts have very consistent lengths — a signature of programmatically generated data.
This is expected for RISCBAC.
""")

# Word count box plot
fig = go.Figure()
fig.add_trace(go.Box(
    y=df["word_count"],
    name="Word Count",
    marker_color="#e74c3c",
    boxmean=True,
))
fig.update_layout(title="Word Count Box Plot (Uniformity Check)", yaxis_title="Word Count")
st.plotly_chart(fig, use_container_width=True)

# ── Section 6: Token Budget Analysis ────────────────────────────────────────

st.header("6. Token Budget Analysis")

st.warning("""
**Note:** Insurance contracts are long documents.
Most RISCBAC contracts require chunking for standard LLM context windows.
""")

windows = [512, 1024, 2048, 4096, 8192, 16384, 32768]
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
n_short = (df["word_count"] < 100).sum()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Contracts", f"{n_total:,}")
col2.metric("Exact Duplicates", f"{n_dup:,}", delta=f"{n_dup/n_total*100:.1f}%", delta_color="inverse")
col3.metric("Very Short (<100 words)", f"{n_short:,}", delta=f"{n_short/n_total*100:.1f}%", delta_color="inverse")
col4.metric("Near-Empty (<10 words)", f"{n_empty:,}", delta=f"{n_empty/n_total*100:.1f}%", delta_color="inverse")

if n_dup == 0:
    st.success("No duplicate contracts — synthetic generation produced unique contracts.")

# ── Section 8: LLM Training Role ────────────────────────────────────────────

st.header("8. LLM Training Role")

st.markdown("""
### RISCBAC in the Training Pipeline

| Attribute | Details |
|-----------|---------|
| **Task Role** | Raw / Pretraining / Long-Context Testing |
| **Format** | Full insurance contract documents |
| **Use Case** | Long-context robustness, summarization, clause extraction on insurance domain |
| **Strengths** | 10k samples, consistent structure, no noise, bilingual |
| **Weaknesses** | Synthetic (may not reflect real-world linguistic diversity), no clause labels |

### Recommended Usage
- **Long-context pretraining**: Test LLM handling of multi-page documents
- **Summarization**: Generate abstractive summaries of contracts
- **Robustness testing**: Evaluate models on insurance-specific terminology
- **Chunking strategy**: Split into overlapping 512-1024 token windows
""")
