"""Combined Dataset Analysis & LLM Training Readiness Dashboard (All 5 Datasets)."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Combined EDA", page_icon="🔗", layout="wide")
st.title("🔗 Combined Dataset Analysis — All 5 Datasets")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# Dataset file paths
CUAD_CLAUSES = DATA_DIR / "atticus" / "cuad_clauses.parquet"
LEDGAR_FILE = DATA_DIR / "legal_clauses" / "ledgar.parquet"
CONTRACTNLI_FILE = DATA_DIR / "contractnli" / "contractnli.parquet"
MATERIAL_FILE = DATA_DIR / "material" / "sec_contracts.parquet"
RISCBAC_FILE = DATA_DIR / "riscbac" / "riscbac.parquet"

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

# Dataset task roles
TASK_ROLES = {
    "atticus": "Supervised / Classification",
    "legal_clauses": "Supervised / Classification",
    "contractnli": "Reasoning / NLI",
    "material": "Raw / Pretraining",
    "riscbac": "Raw / Pretraining",
}

DATASET_COLORS = {
    "atticus": "#3498db",
    "legal_clauses": "#e74c3c",
    "contractnli": "#2ecc71",
    "material": "#f39c12",
    "riscbac": "#9b59b6",
}

DATASET_LABELS = {
    "atticus": "Atticus (CUAD)",
    "legal_clauses": "LEDGAR",
    "contractnli": "ContractNLI",
    "material": "Material (SEC)",
    "riscbac": "RISCBAC",
}


def find_riscbac_text_col(df: pd.DataFrame) -> str:
    for candidate in ["text", "contract", "content", "contract_text", "document"]:
        if candidate in df.columns:
            return candidate
    for col in df.columns:
        if df[col].dtype == object:
            avg_len = df[col].astype(str).str.len().mean()
            if avg_len > 200:
                return col
    return df.columns[0]


@st.cache_data
def load_all_datasets():
    dfs = []
    loaded = []

    # ── Atticus (CUAD clauses) ───────────────────────────────────────────────
    if CUAD_CLAUSES.exists():
        cuad = pd.read_parquet(CUAD_CLAUSES)
        cuad_norm = pd.DataFrame({
            "dataset": "atticus",
            "text": cuad["clause_text"].astype(str),
            "contract_type": cuad.get("contract_title", pd.Series(dtype=str)),
            "label": cuad["clause_type"],
            "task_role": "Supervised / Classification",
            "granularity": "clause",
        })
        dfs.append(cuad_norm)
        loaded.append("atticus")

    # ── LEDGAR ──────────────────────────────────────────────────────────────
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
            "text": ledgar[text_col].astype(str),
            "contract_type": pd.NA,
            "label": label_names,
            "task_role": "Supervised / Classification",
            "granularity": "clause",
        })
        dfs.append(ledgar_norm)
        loaded.append("legal_clauses")

    # ── ContractNLI ─────────────────────────────────────────────────────────
    if CONTRACTNLI_FILE.exists():
        cnli = pd.read_parquet(CONTRACTNLI_FILE)
        label_map = {0: "contradiction", 1: "entailment", 2: "neutral"}
        if "label_name" in cnli.columns:
            label_col = cnli["label_name"]
        elif "label" in cnli.columns and cnli["label"].dtype in ("int64", "int32", "float64"):
            label_col = cnli["label"].map(label_map)
        else:
            label_col = cnli["label"].astype(str) if "label" in cnli.columns else "Unknown"
        cnli_norm = pd.DataFrame({
            "dataset": "contractnli",
            "text": cnli["premise"].astype(str),
            "contract_type": pd.NA,
            "label": label_col,
            "task_role": "Reasoning / NLI",
            "granularity": "clause",
        })
        dfs.append(cnli_norm)
        loaded.append("contractnli")

    # ── Material Contracts (SEC) ─────────────────────────────────────────────
    if MATERIAL_FILE.exists():
        mat = pd.read_parquet(MATERIAL_FILE)
        text_col = "full_text" if "full_text" in mat.columns else "file_content"
        doc_type = mat["doc_type"] if "doc_type" in mat.columns else pd.NA
        mat_norm = pd.DataFrame({
            "dataset": "material",
            "text": mat[text_col].astype(str),
            "contract_type": doc_type,
            "label": doc_type if "doc_type" in mat.columns else "unknown",
            "task_role": "Raw / Pretraining",
            "granularity": "document",
        })
        dfs.append(mat_norm)
        loaded.append("material")

    # ── RISCBAC ──────────────────────────────────────────────────────────────
    if RISCBAC_FILE.exists():
        risc = pd.read_parquet(RISCBAC_FILE)
        text_col = find_riscbac_text_col(risc)
        risc_norm = pd.DataFrame({
            "dataset": "riscbac",
            "text": risc[text_col].astype(str),
            "contract_type": "automobile_insurance",
            "label": "insurance_contract",
            "task_role": "Raw / Pretraining",
            "granularity": "document",
        })
        dfs.append(risc_norm)
        loaded.append("riscbac")

    if not dfs:
        return pd.DataFrame(), []

    combined = pd.concat(dfs, ignore_index=True)
    combined["word_count"] = combined["text"].str.split().str.len()
    combined["est_tokens"] = (combined["word_count"] / 0.75).astype(int)
    combined["dataset_label"] = combined["dataset"].map(DATASET_LABELS)
    combined["task_role"] = combined["dataset"].map(TASK_ROLES)
    return combined, loaded


available_files = [f for f in [CUAD_CLAUSES, LEDGAR_FILE, CONTRACTNLI_FILE, MATERIAL_FILE, RISCBAC_FILE] if f.exists()]
if not available_files:
    st.error("No datasets found. Run `python scripts/download_datasets.py` first.")
    st.stop()

df, loaded_datasets = load_all_datasets()
if df.empty:
    st.error("No data loaded.")
    st.stop()

# ── Pipeline Overview ────────────────────────────────────────────────────────

st.header("Pipeline Overview")

st.markdown("""
The 5 datasets are organized into **3 task roles**:

| Role | Datasets | Purpose |
|------|---------|---------|
| 🟢 **Supervised / Classification** | Atticus (CUAD), LEDGAR | Clause classification, tagging, supervised fine-tuning |
| 🔵 **Reasoning / NLI** | ContractNLI | Entailment detection, claim validation, reasoning |
| 🟠 **Raw / Pretraining** | Material Contracts (SEC), RISCBAC | Pretraining, embedding, retrieval, long-context testing |
""")

loaded_info = " | ".join([f"**{DATASET_LABELS.get(d, d)}** ✅" for d in loaded_datasets])
missing = [d for d in ["atticus", "legal_clauses", "contractnli", "material", "riscbac"] if d not in loaded_datasets]
if missing:
    st.warning(f"Datasets not yet downloaded: {', '.join(DATASET_LABELS.get(d, d) for d in missing)}. Run `python scripts/download_datasets.py`.")

st.markdown(f"Loaded: {loaded_info}")

# ── Section 1: Dataset Contribution ─────────────────────────────────────────

st.header("1. Dataset Contribution")

ds_counts = df.groupby("dataset").agg(
    Samples=("text", "count"),
    Task_Role=("task_role", "first"),
    Granularity=("granularity", "first"),
).reset_index()
ds_counts["Dataset"] = ds_counts["dataset"].map(DATASET_LABELS)
ds_counts["Color"] = ds_counts["dataset"].map(DATASET_COLORS)

col1, col2 = st.columns(2)

with col1:
    fig = px.pie(
        ds_counts,
        values="Samples",
        names="Dataset",
        title="Sample Count by Dataset",
        color="Dataset",
        color_discrete_map={DATASET_LABELS[k]: v for k, v in DATASET_COLORS.items()},
    )
    st.plotly_chart(fig, use_container_width=True)

with col2:
    fig = px.bar(
        ds_counts.sort_values("Samples", ascending=True),
        x="Samples",
        y="Dataset",
        orientation="h",
        title="Sample Count by Dataset",
        color="Task_Role",
        color_discrete_sequence=["#2ecc71", "#3498db", "#f39c12"],
        text_auto=True,
    )
    st.plotly_chart(fig, use_container_width=True)

# Task role contribution
role_counts = df["task_role"].value_counts().reset_index()
role_counts.columns = ["Task Role", "Samples"]
fig = px.pie(
    role_counts,
    values="Samples",
    names="Task Role",
    title="Samples by Task Role",
    color_discrete_sequence=["#2ecc71", "#3498db", "#f39c12"],
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Dataset Summary Table")
st.dataframe(
    ds_counts[["Dataset", "Samples", "Task_Role", "Granularity"]].rename(columns={"Task_Role": "Task Role"}),
    use_container_width=True,
)

# ── Section 2: Text Length Comparison ───────────────────────────────────────

st.header("2. Text Length Comparison")

length_stats = df.groupby("dataset").agg(
    Mean=("word_count", "mean"),
    Median=("word_count", "median"),
    Min=("word_count", "min"),
    Max=("word_count", "max"),
    P95=("word_count", lambda x: x.quantile(0.95)),
).round(0).reset_index()
length_stats["Dataset"] = length_stats["dataset"].map(DATASET_LABELS)
st.dataframe(length_stats[["Dataset", "Mean", "Median", "Min", "Max", "P95"]], use_container_width=True)

# Overlaid histograms — clause-level only (more comparable)
clause_df = df[df["granularity"] == "clause"]
if not clause_df.empty:
    fig = px.histogram(
        clause_df,
        x="word_count",
        color="dataset_label",
        nbins=100,
        title="Word Count Distribution — Clause-Level Datasets",
        labels={"word_count": "Word Count", "dataset_label": "Dataset"},
        barmode="overlay",
        opacity=0.7,
        color_discrete_map={DATASET_LABELS[k]: v for k, v in DATASET_COLORS.items()},
    )
    st.plotly_chart(fig, use_container_width=True)

# All datasets — box plot
fig = px.box(
    df,
    x="dataset_label",
    y="word_count",
    color="task_role",
    title="Word Count Box Plot by Dataset",
    labels={"dataset_label": "Dataset", "word_count": "Word Count"},
    color_discrete_sequence=["#2ecc71", "#3498db", "#f39c12"],
    log_y=True,
)
fig.update_layout(xaxis_title="Dataset")
st.plotly_chart(fig, use_container_width=True)

# Bar chart: mean word count per dataset
mean_wc = df.groupby("dataset_label")["word_count"].mean().reset_index()
mean_wc.columns = ["Dataset", "Mean Word Count"]
fig = px.bar(
    mean_wc.sort_values("Mean Word Count", ascending=True),
    x="Mean Word Count",
    y="Dataset",
    orientation="h",
    title="Mean Word Count by Dataset",
    color="Mean Word Count",
    color_continuous_scale="Viridis",
    text_auto=".0f",
)
st.plotly_chart(fig, use_container_width=True)

# ── Section 3: Global Label Distribution (Supervised datasets only) ──────────

st.header("3. Label Distribution (Supervised Datasets)")

supervised_df = df[df["task_role"] == "Supervised / Classification"]
if not supervised_df.empty:
    label_counts = supervised_df["label"].value_counts().reset_index()
    label_counts.columns = ["Label", "Count"]

    top_n = st.slider("Show top N labels", 10, min(80, len(label_counts)), 40, key="combined_topn")
    display = label_counts.head(top_n)

    fig = px.bar(
        display,
        x="Count",
        y="Label",
        orientation="h",
        title=f"Top {top_n} Labels — Supervised Datasets (Atticus + LEDGAR)",
        color="Count",
        color_continuous_scale="Viridis",
    )
    fig.update_layout(height=max(500, top_n * 20), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

# ContractNLI labels
cnli_df = df[df["dataset"] == "contractnli"]
if not cnli_df.empty:
    cnli_counts = cnli_df["label"].value_counts().reset_index()
    cnli_counts.columns = ["Label", "Count"]
    cnli_colors = {"entailment": "#2ecc71", "contradiction": "#e74c3c", "neutral": "#3498db"}
    fig = px.bar(
        cnli_counts,
        x="Label",
        y="Count",
        title="ContractNLI Label Distribution",
        color="Label",
        color_discrete_map=cnli_colors,
        text_auto=True,
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Section 4: Cross-Dataset Label Overlap ──────────────────────────────────

st.header("4. Cross-Dataset Label Overlap (Supervised)")

if not supervised_df.empty and supervised_df["dataset"].nunique() >= 2:
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
        overlap_data, x="Category", y="Count",
        title="Label Overlap Between Supervised Datasets",
        color="Category",
        color_discrete_sequence=["#2ecc71", "#3498db", "#e74c3c"],
        text_auto=True,
    )
    st.plotly_chart(fig, use_container_width=True)

    if shared:
        with st.expander("Shared label names"):
            st.write(sorted(shared))

# ── Section 5: LLM Training Readiness ──────────────────────────────────────

st.header("5. LLM Training Readiness")

st.subheader("Token Budget Analysis")

windows = [512, 1024, 2048, 4096, 8192]
budget_rows = []
for ds_name in df["dataset"].unique():
    sub = df[df["dataset"] == ds_name]
    row = {"Dataset": DATASET_LABELS.get(ds_name, ds_name)}
    for w in windows:
        pct = (sub["est_tokens"] <= w).sum() / len(sub) * 100
        row[f"{w}tok"] = f"{pct:.0f}%"
    budget_rows.append(row)

budget_df = pd.DataFrame(budget_rows)
st.dataframe(budget_df.set_index("Dataset"), use_container_width=True)

# Token distribution per dataset
fig = px.histogram(
    df,
    x="est_tokens",
    color="dataset_label",
    nbins=100,
    title="Estimated Token Count Distribution by Dataset",
    labels={"est_tokens": "Estimated Tokens", "dataset_label": "Dataset"},
    barmode="overlay",
    opacity=0.6,
    color_discrete_map={DATASET_LABELS[k]: v for k, v in DATASET_COLORS.items()},
    log_y=True,
)
st.plotly_chart(fig, use_container_width=True)

# Chunking requirement
needs_chunking = (df["est_tokens"] > 2048).sum()
st.metric(
    "Samples Needing Chunking (>2048 tokens)", f"{needs_chunking:,}",
    delta=f"{needs_chunking/len(df)*100:.1f}% of total", delta_color="inverse",
)

# ── Section 6: Interpretation & LLM Insights ───────────────────────────────

st.header("6. Interpretation & LLM Training Design")

# Class imbalance (supervised only)
if not supervised_df.empty:
    st.subheader("Class Imbalance (Supervised Datasets)")
    label_freq = supervised_df["label"].value_counts()
    imbalance_ratio = label_freq.max() / label_freq.min() if label_freq.min() > 0 else float("inf")

    col1, col2, col3 = st.columns(3)
    col1.metric("Most Common Label", label_freq.index[0])
    col2.metric("Most Common Count", f"{label_freq.iloc[0]:,}")
    col3.metric("Imbalance Ratio (max/min)", f"{imbalance_ratio:.1f}x")

    if imbalance_ratio > 10:
        st.warning(f"Significant class imbalance ({imbalance_ratio:.0f}x). Use weighted loss or oversample minority classes.")
    elif imbalance_ratio > 5:
        st.info(f"Moderate class imbalance ({imbalance_ratio:.0f}x). Stratified sampling recommended.")
    else:
        st.success("Class distribution is relatively balanced.")

# Training strategy
st.subheader("Recommended Training Strategy")
st.markdown(f"""
Based on dataset structure and task roles:

#### Dataset A — Supervised / Classification
**Datasets:** Atticus (CUAD) + LEDGAR
**Task:** Clause classification, provision labeling
**Split:** 80/10/10 stratified by `label`
- Train: ~{int(supervised_df.shape[0]*0.8):,} samples
- Val: ~{int(supervised_df.shape[0]*0.1):,} samples
- Test: ~{int(supervised_df.shape[0]*0.1):,} samples

#### Dataset B — Reasoning / NLI
**Dataset:** ContractNLI
**Task:** Entailment classification (3-class)
**Split:** Use provided train/validation/test splits

#### Dataset C — Raw / Pretraining
**Datasets:** Material Contracts (SEC) + RISCBAC
**Task:** Continued pretraining, document embedding, retrieval
**Chunking:** Slide 512-token windows with 128-token overlap
""")

# Token summary
st.subheader("Token Budget Summary")
col1, col2, col3 = st.columns(3)
median_tokens = clause_df["est_tokens"].median() if not clause_df.empty else 0
p95_tokens = clause_df["est_tokens"].quantile(0.95) if not clause_df.empty else 0
p99_tokens = clause_df["est_tokens"].quantile(0.99) if not clause_df.empty else 0
col1.metric("Clause-Level Median Tokens", f"{median_tokens:.0f}")
col2.metric("Clause-Level 95th Percentile", f"{p95_tokens:.0f}")
col3.metric("Clause-Level 99th Percentile", f"{p99_tokens:.0f}")

recommended_window = 512 if p95_tokens <= 512 else (1024 if p95_tokens <= 1024 else (2048 if p95_tokens <= 2048 else 4096))
st.info(f"Recommended context window for clause-level tasks: **{recommended_window} tokens** (covers 95th percentile)")
