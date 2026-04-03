"""Atticus (CUAD) Dataset EDA Dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Atticus (CUAD) EDA", page_icon="📜", layout="wide")
st.title("📜 Atticus (CUAD) Dataset — EDA")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "atticus"
RAW_FILE = DATA_DIR / "cuad.parquet"
CLAUSES_FILE = DATA_DIR / "cuad_clauses.parquet"


@st.cache_data
def load_data():
    raw = pd.read_parquet(RAW_FILE) if RAW_FILE.exists() else None
    clauses = pd.read_parquet(CLAUSES_FILE) if CLAUSES_FILE.exists() else None
    return raw, clauses


if not RAW_FILE.exists():
    st.error("Dataset not found. Run `python scripts/download_datasets.py` first.")
    st.stop()

raw_df, clauses_df = load_data()

# ── Section 1: Overview ─────────────────────────────────────────────────────

st.header("1. Overview")

if raw_df is not None:
    n_contracts = raw_df["title"].nunique() if "title" in raw_df.columns else len(raw_df)
    n_rows = len(raw_df)
    unique_questions = raw_df["question"].nunique() if "question" in raw_df.columns else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total QA Rows", f"{n_rows:,}")
    col2.metric("Unique Contracts", f"{n_contracts:,}")
    col3.metric("Clause Categories (Questions)", f"{unique_questions}")

    if clauses_df is not None and not clauses_df.empty:
        col4.metric("Extracted Clause Spans", f"{len(clauses_df):,}")
    else:
        col4.metric("Extracted Clause Spans", "0")

    st.subheader("Raw Data Sample")
    st.dataframe(raw_df.head(10), use_container_width=True)

# ── Section 2: Missing Data Analysis ────────────────────────────────────────

st.header("2. Missing Data Analysis")

if raw_df is not None:
    null_counts = raw_df.isnull().sum()
    null_pct = (raw_df.isnull().sum() / len(raw_df) * 100).round(2)
    missing_df = pd.DataFrame({"Null Count": null_counts, "Null %": null_pct})
    missing_df = missing_df[missing_df["Null Count"] > 0]

    if missing_df.empty:
        st.success("No missing values detected!")
    else:
        st.dataframe(missing_df, use_container_width=True)

    # Heatmap of nulls
    null_matrix = raw_df.isnull().astype(int)
    # Sample for visualization if too large
    sample_size = min(200, len(null_matrix))
    null_sample = null_matrix.sample(sample_size, random_state=42) if len(null_matrix) > sample_size else null_matrix

    fig = px.imshow(
        null_sample.T,
        color_continuous_scale=["#2ecc71", "#e74c3c"],
        labels=dict(color="Is Null"),
        title="Missing Data Heatmap (sample)",
        aspect="auto",
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)

# ── Section 3: Clause Type Distribution ─────────────────────────────────────

st.header("3. Clause Category Distribution")

if raw_df is not None and "question" in raw_df.columns:
    # Count how many non-empty answers per clause category
    def count_answers(row):
        answers = row.get("answers", {})

        if not isinstance(answers, dict):
            return 0

        texts = answers.get("text", [])

        if texts is None:
            return 0

        # Ensure iterable
        try:
            return sum(1 for t in texts if isinstance(t, str) and t.strip())
        except TypeError:
            return 0
    
    raw_df["_answer_count"] = raw_df.apply(count_answers, axis=1)
    has_answer = raw_df[raw_df["_answer_count"] > 0]

    cat_counts = has_answer["question"].value_counts().reset_index()
    cat_counts.columns = ["Clause Category", "Count"]

    fig = px.bar(
        cat_counts,
        x="Count",
        y="Clause Category",
        orientation="h",
        title="Clause Categories by Number of Annotated Spans",
        color="Count",
        color_continuous_scale="Viridis",
    )
    fig.update_layout(height=max(600, len(cat_counts) * 18), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

# ── Section 4: Clause Text Length Distribution ──────────────────────────────

st.header("4. Clause Text Length Distribution")

if clauses_df is not None and not clauses_df.empty:
    clauses_df["word_count"] = clauses_df["clause_text"].str.split().str.len()

    col1, col2, col3 = st.columns(3)
    col1.metric("Mean Word Count", f"{clauses_df['word_count'].mean():.1f}")
    col2.metric("Median Word Count", f"{clauses_df['word_count'].median():.0f}")
    col3.metric("Max Word Count", f"{clauses_df['word_count'].max():,}")

    fig = px.histogram(
        clauses_df,
        x="word_count",
        nbins=80,
        title="Word Count Distribution (Extracted Clauses)",
        labels={"word_count": "Word Count"},
        color_discrete_sequence=["#3498db"],
    )
    fig.update_layout(bargap=0.05)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No clause-level data available.")

# ── Section 5: Clauses Per Contract ─────────────────────────────────────────

st.header("5. Clauses Per Contract")

if clauses_df is not None and not clauses_df.empty and "contract_title" in clauses_df.columns:
    clauses_per_contract = clauses_df.groupby("contract_title").size().reset_index(name="clause_count")

    col1, col2, col3 = st.columns(3)
    col1.metric("Mean Clauses/Contract", f"{clauses_per_contract['clause_count'].mean():.1f}")
    col2.metric("Median", f"{clauses_per_contract['clause_count'].median():.0f}")
    col3.metric("Max", f"{clauses_per_contract['clause_count'].max()}")

    fig = px.histogram(
        clauses_per_contract,
        x="clause_count",
        nbins=40,
        title="Distribution of Clauses Per Contract",
        labels={"clause_count": "Number of Clauses"},
        color_discrete_sequence=["#e67e22"],
    )
    fig.update_layout(bargap=0.05)
    st.plotly_chart(fig, use_container_width=True)

# ── Section 6: Context Length Distribution ──────────────────────────────────

st.header("6. Context (Contract) Length Distribution")

if raw_df is not None and "context" in raw_df.columns:
    # Get unique contexts (one per contract)
    contexts = raw_df.drop_duplicates(subset=["title"] if "title" in raw_df.columns else None)
    contexts["context_word_count"] = contexts["context"].astype(str).str.split().str.len()

    fig = px.histogram(
        contexts,
        x="context_word_count",
        nbins=50,
        title="Contract Context Word Count Distribution",
        labels={"context_word_count": "Word Count"},
        color_discrete_sequence=["#9b59b6"],
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Section 7: Data Quality ─────────────────────────────────────────────────

st.header("7. Data Quality")

if clauses_df is not None and not clauses_df.empty:
    n_total = len(clauses_df)
    n_duplicates = clauses_df.duplicated(subset=["clause_text"]).sum()
    n_short = (clauses_df["clause_text"].str.split().str.len() < 3).sum()
    n_empty = clauses_df["clause_text"].str.strip().eq("").sum()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Clauses", f"{n_total:,}")
    col2.metric("Duplicates", f"{n_duplicates:,}", delta=f"{n_duplicates/n_total*100:.1f}%", delta_color="inverse")
    col3.metric("Very Short (<3 words)", f"{n_short:,}", delta=f"{n_short/n_total*100:.1f}%", delta_color="inverse")
    col4.metric("Empty", f"{n_empty:,}", delta=f"{n_empty/n_total*100:.1f}%", delta_color="inverse")
elif raw_df is not None:
    st.info("Quality metrics shown at clause level. Run clause extraction first.")
