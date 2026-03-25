"""Combined Dataset Analysis & LLM Training Readiness Dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Combined EDA", page_icon="🔗", layout="wide")
st.title("🔗 Combined Dataset Analysis")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CUAD_CLAUSES = DATA_DIR / "atticus" / "cuad_clauses.parquet"
LEDGAR_FILE = DATA_DIR / "legal_clauses" / "ledgar.parquet"

# LEDGAR label names
LEDGAR_LABELS = [
    "Adjustments", "Agreements", "Amendments", "Anti-Corruption Laws",
    "Applicable Laws", "Approvals", "Arbitration", "Assignments",
    "Audits", "Base Coverage and Limits", "Benefits", "Binding Effects",
    "Books", "Brokers", "Capitalization", "Change In Control",
    "Claims", "Closing", "Compliance With Laws", "Conditions",
    "Confidential Information", "Consent To Jurisdiction", "Consequences",
    "Consideration", "Construction", "Cooperation", "Costs",
    "Counterparts", "Death", "Defined Terms", "Definitions",
    "Delivery", "Disclosures", "Duties", "Effectiveness",
    "Elections", "Eligibility", "Entire Agreements", "Erisa",
    "Escrow", "Events", "Exchanges", "Exclusions",
    "Exercise Of Options", "Expenses", "Fees", "Financial Statements",
    "Financings", "Force Majeure", "Further Assurances", "General",
    "Governing Laws", "Grants", "Headings", "Idemnities",
    "Indemnifications", "Information", "Insurance", "Intellectual Property",
    "Interest", "Interpretations", "Jurisdictions", "Landlords",
    "Leases", "Liens", "Limitations", "Loans",
    "Loss", "Maintenance", "Miscellaneous", "Modifications",
    "No Conflicts", "No Defaults", "No Waivers", "Non-Competition",
    "Non-Disparagement", "Non-Reliance", "Non-Solicitation", "Notices",
    "Obligations", "Options", "Organizations", "Participations",
    "Partnerships", "Payments", "Penalties", "Powers",
    "Prices", "Procedures", "Proceeds", "Provisions",
    "Publications", "Qualifications", "Receivables", "Records",
    "Redemptions", "Registrations", "Releases", "Remedies",
    "Removal", "Renewals", "Rent", "Repairs",
    "Representations", "Resignation", "Returns", "Rights",
    "Sales", "Sanctions", "Securities", "Severability",
    "Sharing", "Solicitation", "Staffing", "Standards",
    "Subordination", "Successors", "Survival", "Tax",
    "Taxes", "Terminations", "Terms", "Time",
    "Transfers", "Use", "Vacancies", "Vesting",
    "Voting", "Waiver Of Jury Trials", "Waivers", "Warranties",
]


@st.cache_data
def load_combined():
    """Load and normalize both datasets to a common schema."""
    dfs = []

    # Load CUAD clauses
    if CUAD_CLAUSES.exists():
        cuad = pd.read_parquet(CUAD_CLAUSES)
        cuad_norm = pd.DataFrame({
            "dataset": "atticus",
            "text": cuad["clause_text"],
            "contract_type": cuad.get("contract_title", pd.Series(dtype=str)),
            "clause_type": cuad["clause_type"],
            "label": cuad["clause_type"],
        })
        dfs.append(cuad_norm)

    # Load LEDGAR
    if LEDGAR_FILE.exists():
        ledgar = pd.read_parquet(LEDGAR_FILE)
        text_col = "text" if "text" in ledgar.columns else ledgar.columns[0]
        if "label" in ledgar.columns and ledgar["label"].dtype in ("int64", "int32", "float64"):
            label_names = ledgar["label"].map(
                lambda x: LEDGAR_LABELS[x] if x < len(LEDGAR_LABELS) else f"Label_{x}"
            )
        else:
            label_names = ledgar["label"].astype(str) if "label" in ledgar.columns else "Unknown"

        ledgar_norm = pd.DataFrame({
            "dataset": "legal_clauses",
            "text": ledgar[text_col],
            "contract_type": pd.NA,
            "clause_type": label_names,
            "label": label_names,
        })
        dfs.append(ledgar_norm)

    if not dfs:
        return pd.DataFrame()

    combined = pd.concat(dfs, ignore_index=True)
    combined["word_count"] = combined["text"].astype(str).str.split().str.len()
    # Rough token estimate: ~0.75 words per token for English
    combined["est_tokens"] = (combined["word_count"] / 0.75).astype(int)
    return combined


if not CUAD_CLAUSES.exists() and not LEDGAR_FILE.exists():
    st.error("No datasets found. Run `python scripts/download_datasets.py` first.")
    st.stop()

df = load_combined()
if df.empty:
    st.error("No data loaded.")
    st.stop()

# ── Section 1: Dataset Contribution ─────────────────────────────────────────

st.header("1. Dataset Contribution")

ds_counts = df["dataset"].value_counts().reset_index()
ds_counts.columns = ["Dataset", "Samples"]

col1, col2 = st.columns(2)

with col1:
    fig = px.pie(
        ds_counts,
        values="Samples",
        names="Dataset",
        title="Sample Count by Dataset",
        color_discrete_sequence=["#3498db", "#e74c3c"],
    )
    st.plotly_chart(fig, use_container_width=True)

with col2:
    fig = px.bar(
        ds_counts,
        x="Dataset",
        y="Samples",
        title="Sample Count by Dataset",
        color="Dataset",
        color_discrete_sequence=["#3498db", "#e74c3c"],
        text_auto=True,
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Section 2: Global Label Distribution ────────────────────────────────────

st.header("2. Global Label Distribution")

label_counts = df["label"].value_counts().reset_index()
label_counts.columns = ["Label", "Count"]

top_n = st.slider("Show top N labels", 10, min(60, len(label_counts)), 30, key="combined_topn")
display = label_counts.head(top_n)

fig = px.bar(
    display,
    x="Count",
    y="Label",
    orientation="h",
    title=f"Top {top_n} Labels (Combined)",
    color="Count",
    color_continuous_scale="Viridis",
)
fig.update_layout(height=max(500, top_n * 20), yaxis=dict(autorange="reversed"))
st.plotly_chart(fig, use_container_width=True)

# ── Section 3: Text Length Comparison ───────────────────────────────────────

st.header("3. Text Length Comparison")

col1, col2 = st.columns(2)
for ds_name, col in zip(df["dataset"].unique(), [col1, col2]):
    subset = df[df["dataset"] == ds_name]
    col.metric(f"{ds_name} — Mean Words", f"{subset['word_count'].mean():.1f}")
    col.metric(f"{ds_name} — Median Words", f"{subset['word_count'].median():.0f}")

fig = px.histogram(
    df,
    x="word_count",
    color="dataset",
    nbins=100,
    title="Word Count Distribution by Dataset",
    labels={"word_count": "Word Count"},
    barmode="overlay",
    opacity=0.7,
    color_discrete_sequence=["#3498db", "#e74c3c"],
)
st.plotly_chart(fig, use_container_width=True)

fig = px.box(
    df,
    x="dataset",
    y="word_count",
    color="dataset",
    title="Word Count Box Plot by Dataset",
    color_discrete_sequence=["#3498db", "#e74c3c"],
)
st.plotly_chart(fig, use_container_width=True)

# ── Section 4: Cross-Dataset Overlap ────────────────────────────────────────

st.header("4. Cross-Dataset Overlap")

atticus_labels = set(df[df["dataset"] == "atticus"]["label"].dropna().unique())
ledgar_labels = set(df[df["dataset"] == "legal_clauses"]["label"].dropna().unique())

shared = atticus_labels & ledgar_labels
only_atticus = atticus_labels - ledgar_labels
only_ledgar = ledgar_labels - atticus_labels

col1, col2, col3 = st.columns(3)
col1.metric("Shared Labels", len(shared))
col2.metric("Only in Atticus", len(only_atticus))
col3.metric("Only in LEDGAR", len(only_ledgar))

overlap_data = pd.DataFrame({
    "Category": ["Shared", "Atticus Only", "LEDGAR Only"],
    "Count": [len(shared), len(only_atticus), len(only_ledgar)],
})

fig = px.bar(
    overlap_data,
    x="Category",
    y="Count",
    title="Label Overlap Between Datasets",
    color="Category",
    color_discrete_sequence=["#2ecc71", "#3498db", "#e74c3c"],
    text_auto=True,
)
st.plotly_chart(fig, use_container_width=True)

if shared:
    with st.expander("Shared label names"):
        st.write(sorted(shared))
if only_atticus:
    with st.expander("Atticus-only labels"):
        st.write(sorted(only_atticus))
if only_ledgar:
    with st.expander("LEDGAR-only labels"):
        st.write(sorted(only_ledgar))

# ── Section 5: LLM Training Readiness ──────────────────────────────────────

st.header("5. LLM Training Readiness")

st.subheader("Token Length Distribution")

fig = px.histogram(
    df,
    x="est_tokens",
    color="dataset",
    nbins=100,
    title="Estimated Token Count Distribution",
    labels={"est_tokens": "Estimated Tokens"},
    barmode="overlay",
    opacity=0.7,
    color_discrete_sequence=["#3498db", "#e74c3c"],
)
st.plotly_chart(fig, use_container_width=True)

# Token window analysis
st.subheader("Token Budget Analysis")

windows = [512, 1024, 2048, 4096]
budget_rows = []
for w in windows:
    fits = (df["est_tokens"] <= w).sum()
    pct = fits / len(df) * 100
    budget_rows.append({"Window": f"{w} tokens", "Fits": fits, "% of Data": round(pct, 1)})

budget_df = pd.DataFrame(budget_rows)
st.dataframe(budget_df, use_container_width=True)

fig = px.bar(
    budget_df,
    x="Window",
    y="% of Data",
    title="% of Samples Fitting in Token Windows",
    text_auto=".1f",
    color="% of Data",
    color_continuous_scale="RdYlGn",
)
fig.update_layout(yaxis_range=[0, 105])
st.plotly_chart(fig, use_container_width=True)

# Samples needing chunking
needs_chunking = (df["est_tokens"] > 2048).sum()
st.metric("Samples Needing Chunking (>2048 tokens)", f"{needs_chunking:,}",
          delta=f"{needs_chunking/len(df)*100:.1f}% of total", delta_color="inverse")

# ── Section 6: Interpretation & LLM Insights ───────────────────────────────

st.header("6. Interpretation & LLM Insights")

# Class imbalance
st.subheader("Class Imbalance Analysis")
label_freq = df["label"].value_counts()
imbalance_ratio = label_freq.max() / label_freq.min() if label_freq.min() > 0 else float("inf")

col1, col2, col3 = st.columns(3)
col1.metric("Most Common Label", label_freq.index[0])
col2.metric("Most Common Count", f"{label_freq.iloc[0]:,}")
col3.metric("Imbalance Ratio (max/min)", f"{imbalance_ratio:.1f}x")

if imbalance_ratio > 10:
    st.warning(f"Significant class imbalance detected (ratio: {imbalance_ratio:.0f}x). "
               "Consider oversampling minority classes or using weighted loss.")
elif imbalance_ratio > 5:
    st.info(f"Moderate class imbalance (ratio: {imbalance_ratio:.0f}x). "
            "Stratified sampling recommended.")
else:
    st.success("Class distribution is relatively balanced.")

# Sampling strategy
st.subheader("Recommended Sampling Strategy")
st.markdown(f"""
Based on the dataset analysis:

- **Total combined samples**: {len(df):,}
- **Recommended train/val/test split**: 80/10/10
  - Train: ~{int(len(df)*0.8):,} samples
  - Validation: ~{int(len(df)*0.1):,} samples
  - Test: ~{int(len(df)*0.1):,} samples
- **Stratification**: Split by `label` to maintain class distribution
- **Cross-dataset**: Ensure both datasets are represented in all splits
""")

# Token budget summary
st.subheader("Token Budget Summary")
median_tokens = df["est_tokens"].median()
p95_tokens = df["est_tokens"].quantile(0.95)
p99_tokens = df["est_tokens"].quantile(0.99)

col1, col2, col3 = st.columns(3)
col1.metric("Median Tokens", f"{median_tokens:.0f}")
col2.metric("95th Percentile", f"{p95_tokens:.0f}")
col3.metric("99th Percentile", f"{p99_tokens:.0f}")

recommended_window = 512 if p95_tokens <= 512 else (1024 if p95_tokens <= 1024 else (2048 if p95_tokens <= 2048 else 4096))
st.info(f"Recommended context window: **{recommended_window} tokens** (covers 95th percentile of data)")
