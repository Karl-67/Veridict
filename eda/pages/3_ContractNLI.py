"""ContractNLI Dataset EDA Dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="ContractNLI EDA", page_icon="⚖️", layout="wide")
st.title("⚖️ ContractNLI Dataset — EDA")

st.markdown("""
**ContractNLI** is a Natural Language Inference dataset for contracts.
Each row is a (premise, hypothesis) pair with a 3-class label:
- **Entailment** — the hypothesis is supported by the contract
- **Contradiction** — the hypothesis is contradicted by the contract
- **Neutral** — the hypothesis is neither entailed nor contradicted

*Source: `kiddothe2b/contract-nli`, config `contractnli_b`*
""")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "contractnli"
DATA_FILE = DATA_DIR / "contractnli.parquet"

LABEL_COLORS = {
    "entailment": "#2ecc71",
    "contradiction": "#e74c3c",
    "neutral": "#3498db",
}


@st.cache_data
def load_data():
    df = pd.read_parquet(DATA_FILE)
    if "label_name" not in df.columns:
        label_map = {0: "contradiction", 1: "entailment", 2: "neutral"}
        df["label_name"] = df["label"].map(label_map).fillna(df["label"].astype(str))
    df["premise_words"] = df["premise"].astype(str).str.split().str.len()
    df["hypothesis_words"] = df["hypothesis"].astype(str).str.split().str.len()
    return df


if not DATA_FILE.exists():
    st.error("Dataset not found. Run `python scripts/download_datasets.py` first.")
    st.stop()

df = load_data()

# ── Section 1: Overview ─────────────────────────────────────────────────────

st.header("1. Overview")

splits = df["split"].value_counts().to_dict() if "split" in df.columns else {}
n_total = len(df)
n_labels = df["label_name"].nunique()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Samples", f"{n_total:,}")
col2.metric("Unique Labels", f"{n_labels}")
col3.metric("Avg Premise Words", f"{df['premise_words'].mean():.1f}")
col4.metric("Avg Hypothesis Words", f"{df['hypothesis_words'].mean():.1f}")

if splits:
    st.markdown("**Splits:** " + " | ".join(f"`{k}`: {v:,}" for k, v in splits.items()))

st.subheader("Data Sample")
st.dataframe(df[["premise", "hypothesis", "label_name", "split"]].head(10), use_container_width=True)

# ── Section 2: Missing Data Analysis ────────────────────────────────────────

st.header("2. Missing Data Analysis")

null_counts = df[["premise", "hypothesis", "label", "label_name"]].isnull().sum()
null_pct = (null_counts / n_total * 100).round(2)
missing_df = pd.DataFrame({"Null Count": null_counts, "Null %": null_pct})
missing_df = missing_df[missing_df["Null Count"] > 0]

if missing_df.empty:
    st.success("No missing values in key columns!")
else:
    st.dataframe(missing_df, use_container_width=True)

# ── Section 3: Label Distribution ────────────────────────────────────────────

st.header("3. Label Distribution")

label_counts = df["label_name"].value_counts().reset_index()
label_counts.columns = ["Label", "Count"]
label_counts["Color"] = label_counts["Label"].map(LABEL_COLORS)

col1, col2 = st.columns(2)

with col1:
    fig = px.pie(
        label_counts,
        values="Count",
        names="Label",
        title="Label Distribution (Overall)",
        color="Label",
        color_discrete_map=LABEL_COLORS,
    )
    st.plotly_chart(fig, use_container_width=True)

with col2:
    fig = px.bar(
        label_counts,
        x="Label",
        y="Count",
        title="Label Counts",
        color="Label",
        color_discrete_map=LABEL_COLORS,
        text_auto=True,
    )
    st.plotly_chart(fig, use_container_width=True)

# Label distribution by split
if "split" in df.columns and df["split"].nunique() > 1:
    split_label = df.groupby(["split", "label_name"]).size().reset_index(name="Count")
    fig = px.bar(
        split_label,
        x="split",
        y="Count",
        color="label_name",
        title="Label Distribution by Split",
        color_discrete_map=LABEL_COLORS,
        barmode="group",
        text_auto=True,
    )
    st.plotly_chart(fig, use_container_width=True)

# Imbalance check
imbalance = label_counts["Count"].max() / label_counts["Count"].min()
if imbalance > 2:
    st.warning(f"Class imbalance detected: ratio = {imbalance:.1f}x. Consider weighted loss or resampling.")
else:
    st.success(f"Labels are relatively balanced (ratio = {imbalance:.1f}x).")

# ── Section 4: Text Length Analysis ─────────────────────────────────────────

st.header("4. Text Length Analysis")

col1, col2 = st.columns(2)
col1.metric("Premise — Mean Words", f"{df['premise_words'].mean():.1f}")
col1.metric("Premise — Median Words", f"{df['premise_words'].median():.0f}")
col1.metric("Premise — Max Words", f"{df['premise_words'].max():,}")
col2.metric("Hypothesis — Mean Words", f"{df['hypothesis_words'].mean():.1f}")
col2.metric("Hypothesis — Median Words", f"{df['hypothesis_words'].median():.0f}")
col2.metric("Hypothesis — Max Words", f"{df['hypothesis_words'].max():,}")

# Premise length histogram by label
fig = px.histogram(
    df,
    x="premise_words",
    color="label_name",
    nbins=80,
    title="Premise Word Count Distribution by Label",
    labels={"premise_words": "Word Count"},
    barmode="overlay",
    opacity=0.7,
    color_discrete_map=LABEL_COLORS,
)
st.plotly_chart(fig, use_container_width=True)

# Hypothesis length
fig = px.histogram(
    df,
    x="hypothesis_words",
    color="label_name",
    nbins=60,
    title="Hypothesis Word Count Distribution by Label",
    labels={"hypothesis_words": "Word Count"},
    barmode="overlay",
    opacity=0.7,
    color_discrete_map=LABEL_COLORS,
)
st.plotly_chart(fig, use_container_width=True)

# Box plots
fig = px.box(
    df.melt(
        id_vars=["label_name"],
        value_vars=["premise_words", "hypothesis_words"],
        var_name="Text Type",
        value_name="Word Count",
    ),
    x="Text Type",
    y="Word Count",
    color="label_name",
    title="Word Count Box Plot (Premise vs Hypothesis by Label)",
    color_discrete_map=LABEL_COLORS,
)
st.plotly_chart(fig, use_container_width=True)

# ── Section 5: Token Budget Analysis ────────────────────────────────────────

st.header("5. Token Budget Analysis")

# Estimate tokens (premise + hypothesis combined for NLI input)
df["est_tokens_combined"] = ((df["premise_words"] + df["hypothesis_words"]) / 0.75).astype(int)

windows = [512, 1024, 2048, 4096]
budget_rows = []
for w in windows:
    fits = (df["est_tokens_combined"] <= w).sum()
    pct = fits / n_total * 100
    budget_rows.append({"Window": f"{w} tokens", "Fits": fits, "% of Data": round(pct, 1)})

st.dataframe(pd.DataFrame(budget_rows), use_container_width=True)

fig = px.bar(
    pd.DataFrame(budget_rows),
    x="Window",
    y="% of Data",
    title="% of NLI Pairs Fitting in Token Windows (Premise + Hypothesis)",
    text_auto=".1f",
    color="% of Data",
    color_continuous_scale="RdYlGn",
)
fig.update_layout(yaxis_range=[0, 105])
st.plotly_chart(fig, use_container_width=True)

# ── Section 6: Data Quality ──────────────────────────────────────────────────

st.header("6. Data Quality")

n_dup_premise = df.duplicated(subset=["premise"]).sum()
n_dup_pair = df.duplicated(subset=["premise", "hypothesis"]).sum()
n_short_premise = (df["premise_words"] < 5).sum()
n_short_hyp = (df["hypothesis_words"] < 3).sum()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Samples", f"{n_total:,}")
col2.metric("Duplicate Premises", f"{n_dup_premise:,}", delta=f"{n_dup_premise/n_total*100:.1f}%", delta_color="inverse")
col3.metric("Duplicate Pairs", f"{n_dup_pair:,}", delta=f"{n_dup_pair/n_total*100:.1f}%", delta_color="inverse")
col4.metric("Short Premises (<5 words)", f"{n_short_premise:,}", delta=f"{n_short_premise/n_total*100:.1f}%", delta_color="inverse")

# ── Section 7: LLM Training Role ────────────────────────────────────────────

st.header("7. LLM Training Role")

st.markdown("""
### ContractNLI in the Training Pipeline

| Attribute | Details |
|-----------|---------|
| **Task Role** | Reasoning / NLI |
| **Format** | Paired (premise + hypothesis) |
| **Use Case** | Train a contract reasoning model to validate claims against contract text |
| **Strengths** | Clean labels, multi-split, directly applicable to clause validation |
| **Weaknesses** | Premise length variability may exceed 512-token windows |

### Recommended Usage
- **Fine-tuning target**: Sequence classification (3-class: entailment / contradiction / neutral)
- **Input format**: `[CLS] premise [SEP] hypothesis [SEP]`
- **Recommended window**: Check token budget chart above
- **Split strategy**: Use provided train/validation/test splits
""")
