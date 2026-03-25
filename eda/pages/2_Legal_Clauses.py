"""Legal Clauses (LEDGAR) Dataset EDA Dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

st.set_page_config(page_title="LEDGAR EDA", page_icon="📑", layout="wide")
st.title("📑 Legal Clauses (LEDGAR) — EDA")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "legal_clauses"
DATA_FILE = DATA_DIR / "ledgar.parquet"

# LEDGAR label names (100 most common provision types)
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
def load_data():
    df = pd.read_parquet(DATA_FILE)
    # Map numeric label to name if available
    if "label" in df.columns and df["label"].dtype in ("int64", "int32", "float64"):
        if len(LEDGAR_LABELS) > df["label"].max():
            df["label_name"] = df["label"].map(lambda x: LEDGAR_LABELS[x] if x < len(LEDGAR_LABELS) else f"Label_{x}")
        else:
            df["label_name"] = df["label"].astype(str)
    elif "label" in df.columns:
        df["label_name"] = df["label"].astype(str)
    else:
        df["label_name"] = "Unknown"
    return df


if not DATA_FILE.exists():
    st.error("Dataset not found. Run `python scripts/download_datasets.py` first.")
    st.stop()

df = load_data()

# ── Section 1: Overview ─────────────────────────────────────────────────────

st.header("1. Overview")

text_col = "text" if "text" in df.columns else df.columns[0]
df["_word_count"] = df[text_col].astype(str).str.split().str.len()

n_total = len(df)
n_labels = df["label_name"].nunique()
avg_len = df["_word_count"].mean()
splits = df["split"].value_counts().to_dict() if "split" in df.columns else {}

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Samples", f"{n_total:,}")
col2.metric("Unique Provision Types", f"{n_labels}")
col3.metric("Avg Word Count", f"{avg_len:.1f}")
col4.metric("Splits", ", ".join(f"{k}: {v:,}" for k, v in splits.items()) if splits else "N/A")

st.subheader("Data Sample")
st.dataframe(df.head(10), use_container_width=True)

# ── Section 2: Missing Data Analysis ────────────────────────────────────────

st.header("2. Missing Data Analysis")

null_counts = df.isnull().sum()
null_pct = (df.isnull().sum() / len(df) * 100).round(2)
missing_df = pd.DataFrame({"Null Count": null_counts, "Null %": null_pct})
missing_df = missing_df[missing_df["Null Count"] > 0]

if missing_df.empty:
    st.success("No missing values detected!")
else:
    st.dataframe(missing_df, use_container_width=True)

# Heatmap
null_matrix = df.isnull().astype(int)
sample_size = min(300, len(null_matrix))
null_sample = null_matrix.sample(sample_size, random_state=42) if len(null_matrix) > sample_size else null_matrix

fig = px.imshow(
    null_sample.T,
    color_continuous_scale=["#2ecc71", "#e74c3c"],
    labels=dict(color="Is Null"),
    title="Missing Data Heatmap (sample)",
    aspect="auto",
)
fig.update_layout(height=300)
st.plotly_chart(fig, use_container_width=True)

# ── Section 3: Clause Type Distribution ─────────────────────────────────────

st.header("3. Provision Type Distribution")

label_counts = df["label_name"].value_counts().reset_index()
label_counts.columns = ["Provision Type", "Count"]

# Show top 30 for readability
top_n = st.slider("Show top N provision types", 10, min(100, len(label_counts)), 30)
display_counts = label_counts.head(top_n)

fig = px.bar(
    display_counts,
    x="Count",
    y="Provision Type",
    orientation="h",
    title=f"Top {top_n} Provision Types by Frequency",
    color="Count",
    color_continuous_scale="Viridis",
)
fig.update_layout(height=max(500, top_n * 20), yaxis=dict(autorange="reversed"))
st.plotly_chart(fig, use_container_width=True)

# ── Section 4: Text Length Distribution ─────────────────────────────────────

st.header("4. Text Length Distribution")

col1, col2, col3 = st.columns(3)
col1.metric("Mean Word Count", f"{df['_word_count'].mean():.1f}")
col2.metric("Median Word Count", f"{df['_word_count'].median():.0f}")
col3.metric("Max Word Count", f"{df['_word_count'].max():,}")

fig = px.histogram(
    df,
    x="_word_count",
    nbins=100,
    title="Word Count Distribution",
    labels={"_word_count": "Word Count"},
    color_discrete_sequence=["#3498db"],
)
fig.update_layout(bargap=0.05)
st.plotly_chart(fig, use_container_width=True)

# By split
if "split" in df.columns:
    fig = px.histogram(
        df,
        x="_word_count",
        color="split",
        nbins=80,
        title="Word Count Distribution by Split",
        labels={"_word_count": "Word Count"},
        barmode="overlay",
        opacity=0.7,
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Section 5: Data Quality ─────────────────────────────────────────────────

st.header("5. Data Quality")

n_duplicates = df.duplicated(subset=[text_col]).sum()
n_short = (df["_word_count"] < 5).sum()
n_empty = df[text_col].astype(str).str.strip().eq("").sum()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Samples", f"{n_total:,}")
col2.metric("Duplicates", f"{n_duplicates:,}", delta=f"{n_duplicates/n_total*100:.1f}%", delta_color="inverse")
col3.metric("Very Short (<5 words)", f"{n_short:,}", delta=f"{n_short/n_total*100:.1f}%", delta_color="inverse")
col4.metric("Empty", f"{n_empty:,}", delta=f"{n_empty/n_total*100:.1f}%", delta_color="inverse")

# Distribution by split
if "split" in df.columns:
    split_stats = df.groupby("split").agg(
        count=(text_col, "count"),
        mean_words=("_word_count", "mean"),
        median_words=("_word_count", "median"),
    ).round(1)
    st.subheader("Stats by Split")
    st.dataframe(split_stats, use_container_width=True)
