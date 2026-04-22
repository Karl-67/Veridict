"""Combined Dataset Analysis & LLM Training Readiness Dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Combined EDA", page_icon="🔗", layout="wide")
st.title("🔗 Combined Dataset Analysis — All 4 Datasets")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

CUAD_CLAUSES = DATA_DIR / "atticus" / "cuad_clauses.parquet"
LEDGAR_FILE = DATA_DIR / "legal_clauses" / "ledgar.parquet"
CONTRACTNLI_FILE = DATA_DIR / "contractnli" / "contractnli.parquet"
MAUD_FILE = DATA_DIR / "maud" / "maud.parquet"

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
    "Removal",
]

TASK_ROLES = {
    "atticus":       "Supervised / Classification",
    "legal_clauses": "Supervised / Classification",
    "contractnli":   "Reasoning / NLI",
    "maud":          "Expert Annotation / M&A QA",
}

DATASET_COLORS = {
    "atticus":       "#3498db",
    "legal_clauses": "#e74c3c",
    "contractnli":   "#2ecc71",
    "maud":          "#9b59b6",
}

DATASET_LABELS = {
    "atticus":       "Atticus (CUAD)",
    "legal_clauses": "LEDGAR",
    "contractnli":   "ContractNLI",
    "maud":          "MAUD",
}


@st.cache_data
def load_all_datasets():
    dfs = []
    loaded = []

    # ── Atticus (CUAD clauses) ───────────────────────────────────────────────
    if CUAD_CLAUSES.exists():
        cuad = pd.read_parquet(CUAD_CLAUSES)
        cuad_norm = pd.DataFrame({
            "dataset":       "atticus",
            "text":          cuad["clause_text"].astype(str),
            "contract_type": cuad.get("contract_title", pd.Series(dtype=str)),
            "label":         cuad["clause_type"],
            "task_role":     "Supervised / Classification",
            "granularity":   "clause",
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
            "dataset":       "legal_clauses",
            "text":          ledgar[text_col].astype(str),
            "contract_type": pd.NA,
            "label":         label_names,
            "task_role":     "Supervised / Classification",
            "granularity":   "clause",
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
            "dataset":       "contractnli",
            "text":          cnli["premise"].astype(str),
            "contract_type": pd.NA,
            "label":         label_col,
            "task_role":     "Reasoning / NLI",
            "granularity":   "clause",
        })
        dfs.append(cnli_norm)
        loaded.append("contractnli")

    # ── MAUD ────────────────────────────────────────────────────────────────
    if MAUD_FILE.exists():
        maud = pd.read_parquet(MAUD_FILE)
        maud_norm = pd.DataFrame({
            "dataset":       "maud",
            "text":          maud["text"].astype(str),
            "contract_type": maud["contract_name"] if "contract_name" in maud.columns else pd.NA,
            "label":         maud["category"] if "category" in maud.columns else "unknown",
            "task_role":     "Expert Annotation / M&A QA",
            "granularity":   "passage",
        })
        dfs.append(maud_norm)
        loaded.append("maud")

    if not dfs:
        return pd.DataFrame(), []

    combined = pd.concat(dfs, ignore_index=True)
    combined["word_count"] = combined["text"].str.split().str.len()
    combined["est_tokens"] = (combined["word_count"] / 0.75).astype(int)
    combined["dataset_label"] = combined["dataset"].map(DATASET_LABELS)
    combined["task_role"] = combined["dataset"].map(TASK_ROLES)
    return combined, loaded


available_files = [f for f in [CUAD_CLAUSES, LEDGAR_FILE, CONTRACTNLI_FILE, MAUD_FILE] if f.exists()]
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
The 4 datasets are organized into **3 task roles**:

| Role | Datasets | Purpose |
|------|---------|---------|
| 🟢 **Supervised / Classification** | Atticus (CUAD), LEDGAR | Clause classification, provision tagging, reviewer SFT |
| 🔵 **Reasoning / NLI** | ContractNLI | Entailment detection, claim validation, validator SFT |
| 🟣 **Expert Annotation / M&A QA** | MAUD | M&A deal-point reviewer SFT, RL reward signal |
""")

loaded_info = " | ".join([f"**{DATASET_LABELS.get(d, d)}** ✅" for d in loaded_datasets])
missing = [d for d in ["atticus", "legal_clauses", "contractnli", "maud"] if d not in loaded_datasets]
if missing:
    st.warning(
        f"Datasets not yet downloaded: {', '.join(DATASET_LABELS.get(d, d) for d in missing)}. "
        "Run `python scripts/download_datasets.py`."
    )
st.markdown(f"Loaded: {loaded_info}")

# ── Section 1: Dataset Contribution ─────────────────────────────────────────

st.header("1. Dataset Contribution")

ds_counts = df.groupby("dataset").agg(
    Samples=("text", "count"),
    Task_Role=("task_role", "first"),
    Granularity=("granularity", "first"),
).reset_index()
ds_counts["Dataset"] = ds_counts["dataset"].map(DATASET_LABELS)

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
        color_discrete_sequence=["#2ecc71", "#3498db", "#9b59b6"],
        text_auto=True,
    )
    st.plotly_chart(fig, use_container_width=True)

role_counts = df["task_role"].value_counts().reset_index()
role_counts.columns = ["Task Role", "Samples"]
fig = px.pie(
    role_counts,
    values="Samples",
    names="Task Role",
    title="Samples by Task Role",
    color_discrete_sequence=["#2ecc71", "#3498db", "#9b59b6"],
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Dataset Summary Table")
st.dataframe(
    ds_counts[["Dataset", "Samples", "Task_Role", "Granularity"]].rename(
        columns={"Task_Role": "Task Role"}
    ),
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

# Clause-level overlay (CUAD, LEDGAR, ContractNLI)
clause_df = df[df["granularity"].isin(["clause"])]
if not clause_df.empty:
    fig = px.histogram(
        clause_df,
        x="word_count",
        color="dataset_label",
        nbins=100,
        title="Word Count Distribution — Clause-Level Datasets (CUAD, LEDGAR, ContractNLI)",
        labels={"word_count": "Word Count", "dataset_label": "Dataset"},
        barmode="overlay",
        opacity=0.7,
        color_discrete_map={DATASET_LABELS[k]: v for k, v in DATASET_COLORS.items()},
    )
    st.plotly_chart(fig, use_container_width=True)

# MAUD separately (much longer passages)
maud_df = df[df["dataset"] == "maud"]
if not maud_df.empty:
    fig2 = px.histogram(
        maud_df,
        x="word_count",
        nbins=80,
        title="Word Count Distribution — MAUD Passages",
        labels={"word_count": "Word Count"},
        color_discrete_sequence=["#9b59b6"],
    )
    fig2.add_vline(x=150, line_dash="dash", line_color="orange",
                   annotation_text="Medium/Long boundary")
    st.plotly_chart(fig2, use_container_width=True)

# Box plot (log scale — datasets span very different ranges)
fig3 = px.box(
    df,
    x="dataset_label",
    y="word_count",
    color="task_role",
    title="Word Count Box Plot by Dataset (log scale)",
    labels={"dataset_label": "Dataset", "word_count": "Word Count"},
    color_discrete_sequence=["#2ecc71", "#3498db", "#9b59b6"],
    log_y=True,
)
fig3.update_layout(xaxis_title="Dataset")
st.plotly_chart(fig3, use_container_width=True)

# ── Section 3: Length Buckets ────────────────────────────────────────────────

st.header("3. Length Buckets (Short / Medium / Long)")

df["length_bucket"] = pd.cut(
    df["word_count"],
    bins=[0, 30, 150, 99999],
    labels=["Short (≤30)", "Medium (31–150)", "Long (>150)"],
)

bucket_ds = df.groupby(["dataset_label", "length_bucket"]).size().reset_index(name="Count")
fig = px.bar(
    bucket_ds,
    x="dataset_label",
    y="Count",
    color="length_bucket",
    barmode="stack",
    title="Length Bucket Breakdown per Dataset",
    labels={"dataset_label": "Dataset", "length_bucket": "Bucket"},
    color_discrete_sequence=["#2ecc71", "#f39c12", "#e74c3c"],
)
st.plotly_chart(fig, use_container_width=True)

bucket_pct = df.groupby(["dataset_label", "length_bucket"]).size().reset_index(name="Count")
total_per_ds = bucket_pct.groupby("dataset_label")["Count"].transform("sum")
bucket_pct["Pct"] = (bucket_pct["Count"] / total_per_ds * 100).round(1)
fig2 = px.bar(
    bucket_pct,
    x="dataset_label",
    y="Pct",
    color="length_bucket",
    barmode="stack",
    title="Length Bucket % per Dataset",
    labels={"dataset_label": "Dataset", "Pct": "% of Rows", "length_bucket": "Bucket"},
    color_discrete_sequence=["#2ecc71", "#f39c12", "#e74c3c"],
    text="Pct",
)
fig2.update_traces(texttemplate="%{text}%", textposition="inside")
st.plotly_chart(fig2, use_container_width=True)

# ── Section 4: Label Distribution (Supervised + NLI datasets) ───────────────

st.header("4. Label Distribution (Supervised + NLI Datasets)")

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
        title=f"Top {top_n} Labels — Supervised Datasets (CUAD + LEDGAR)",
        color="Count",
        color_continuous_scale="Viridis",
    )
    fig.update_layout(height=max(500, top_n * 20), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

# ContractNLI
cnli_df = df[df["dataset"] == "contractnli"]
if not cnli_df.empty:
    cnli_counts = cnli_df["label"].value_counts().reset_index()
    cnli_counts.columns = ["Label", "Count"]
    cnli_colors = {"entailment": "#2ecc71", "contradiction": "#e74c3c", "neutral": "#3498db"}
    fig = px.bar(
        cnli_counts, x="Label", y="Count",
        title="ContractNLI Label Distribution",
        color="Label",
        color_discrete_map=cnli_colors,
        text_auto=True,
    )
    st.plotly_chart(fig, use_container_width=True)

# MAUD category
if not maud_df.empty:
    maud_cat = maud_df["label"].value_counts().reset_index()
    maud_cat.columns = ["Category", "Count"]
    fig = px.bar(
        maud_cat.sort_values("Count"),
        x="Count", y="Category", orientation="h",
        title="MAUD Category Distribution",
        color="Count",
        color_continuous_scale="Purples",
        text_auto=True,
    )
    fig.update_layout(height=350)
    st.plotly_chart(fig, use_container_width=True)

# ── Section 5: Cross-Dataset Deduplication Summary ──────────────────────────

st.header("5. Deduplication Summary")

dedup_data = [
    {"Dataset": "CUAD",         "Total Rows": 13823, "Exact Text Dupes": 2140,  "% Dupes": "15.5%", "Unique Texts": 11683, "Reason": "Same span → multiple QA questions"},
    {"Dataset": "LEDGAR",       "Total Rows": 80000, "Exact Text Dupes": 0,     "% Dupes": "0.0%",  "Unique Texts": 80000, "Reason": "Clean — one provision per row"},
    {"Dataset": "ContractNLI",  "Total Rows": 9788,  "Exact Text Dupes": 5085,  "% Dupes": "52.0%", "Unique Texts": 4703,  "Reason": "Same premise → multiple hypotheses"},
    {"Dataset": "MAUD",         "Total Rows": 39231, "Exact Text Dupes": 31005, "% Dupes": "79.0%", "Unique Texts": 8226,  "Reason": "Same passage → 92 deal-point questions"},
]
dedup_df = pd.DataFrame(dedup_data)
st.dataframe(dedup_df, use_container_width=True, hide_index=True)
total_unique = sum(d["Unique Texts"] for d in dedup_data)
total_rows = sum(d["Total Rows"] for d in dedup_data)
st.info(
    f"**Total unique clause/passage texts across all datasets: ~{total_unique:,}** "
    f"(vs {total_rows:,} total rows). "
    "For LLM labeling, deduplicate on text first — this saves ~{:.0f}% of labeling cost.".format(
        (1 - total_unique / total_rows) * 100
    )
)

cross_overlap = 11
st.metric("Cross-dataset exact text matches (CUAD vs LEDGAR)", f"{cross_overlap}", delta="negligible")

# ── Section 6: LLM Training Readiness — Token Budget ────────────────────────

st.header("6. LLM Training Readiness — Token Budget")

windows = [512, 1024, 2048, 4096]
budget_rows_list = []
for ds_name in ["atticus", "legal_clauses", "contractnli", "maud"]:
    sub = df[df["dataset"] == ds_name]
    if sub.empty:
        continue
    row = {"Dataset": DATASET_LABELS.get(ds_name, ds_name)}
    for w in windows:
        pct = (sub["est_tokens"] <= w).sum() / len(sub) * 100
        row[f"{w} tok"] = f"{pct:.0f}%"
    budget_rows_list.append(row)

budget_df = pd.DataFrame(budget_rows_list)
st.dataframe(budget_df.set_index("Dataset"), use_container_width=True)

fig = px.histogram(
    df[df["dataset"] != "maud"],  # clause-level only for clarity
    x="est_tokens",
    color="dataset_label",
    nbins=100,
    title="Estimated Token Count — Clause-Level Datasets",
    labels={"est_tokens": "Estimated Tokens", "dataset_label": "Dataset"},
    barmode="overlay",
    opacity=0.6,
    color_discrete_map={DATASET_LABELS[k]: v for k, v in DATASET_COLORS.items() if k != "maud"},
    log_y=True,
)
st.plotly_chart(fig, use_container_width=True)

needs_chunking = (df["est_tokens"] > 2048).sum()
st.metric(
    "Samples Needing Chunking (> 2048 tokens)", f"{needs_chunking:,}",
    delta=f"{needs_chunking / len(df) * 100:.1f}% of total", delta_color="inverse",
)

# ── Section 7: Class Imbalance Summary ──────────────────────────────────────

st.header("7. Class Imbalance Summary")

if not supervised_df.empty:
    label_freq = supervised_df["label"].value_counts()
    imbalance_ratio = label_freq.max() / label_freq.min() if label_freq.min() > 0 else float("inf")

    col1, col2, col3 = st.columns(3)
    col1.metric("Most Common Label", label_freq.index[0])
    col2.metric("Most Common Count", f"{label_freq.iloc[0]:,}")
    col3.metric("Imbalance Ratio (max/min)", f"{imbalance_ratio:.1f}×")

    if imbalance_ratio > 10:
        st.error(
            f"Significant class imbalance ({imbalance_ratio:.0f}×). "
            "Use weighted loss or oversample minority classes. "
            "Cap dominant classes at 1,500 examples before LLM labeling."
        )

# ── Section 8: Training Strategy ────────────────────────────────────────────

st.header("8. Recommended Training Strategy")

st.markdown(f"""
Based on dataset structure, task roles, and deduplication findings:

#### Dataset A — Reviewer SFT (Supervised / Classification)
**Sources:** Atticus (CUAD) + LEDGAR
**Task:** Clause classification by issue type → reviewer fine-tuning
**Split strategy:** Document-level for CUAD (510 contracts); row-level stratified for LEDGAR
- Train: ~{int(supervised_df.shape[0]*0.8):,} samples
- Val: ~{int(supervised_df.shape[0]*0.1):,} samples
- Test: ~{int(supervised_df.shape[0]*0.1):,} samples

#### Dataset B — Validator SFT (Reasoning / NLI)
**Source:** ContractNLI
**Task:** Entailment classification (3-class) → validator fine-tuning
**Split strategy:** Use provided train/dev/test splits directly

#### Dataset C — M&A Reviewer SFT (Expert Annotation / M&A QA)
**Source:** MAUD
**Task:** M&A deal-point review, missing clause detection in merger agreements
**Split strategy:** Use provided document-level train/val/test splits directly

#### RL Pool (all sources, not split)
**Sources:** Curated pool from all 4 datasets
**Task:** Reward model training / RLHF / RLAIF
**Note:** No train/val/test split — single undivided pool, disjoint from SFT train set
""")

st.subheader("Token Budget Summary")
col1, col2, col3 = st.columns(3)
clause_tokens = df[df["granularity"] == "clause"]["est_tokens"]
if not clause_tokens.empty:
    col1.metric("Clause-Level Median Tokens", f"{clause_tokens.median():.0f}")
    col2.metric("Clause-Level 95th Percentile", f"{clause_tokens.quantile(0.95):.0f}")
    col3.metric("Clause-Level 99th Percentile", f"{clause_tokens.quantile(0.99):.0f}")
    p95 = clause_tokens.quantile(0.95)
    recommended_window = 512 if p95 <= 512 else (1024 if p95 <= 1024 else (2048 if p95 <= 2048 else 4096))
    st.info(
        f"Recommended context window for clause-level tasks: **{recommended_window} tokens** (covers 95th percentile).  \n"
        "MAUD passages require **≥ 2048 tokens** or passage truncation to ≤ 150 words."
    )
