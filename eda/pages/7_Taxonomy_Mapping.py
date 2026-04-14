"""Taxonomy Mapping — Label Unification & Curation Design for Fine-Tuning + RAG."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Taxonomy Mapping", page_icon="🗂️", layout="wide")
st.title("🗂️ Taxonomy Mapping — Curation Design for Fine-Tuning + RAG")

st.markdown("""
This page answers the three open questions from the curation review:

> **Q1** — What is the CUAD → issue type mapping, and LEDGAR → issue type mapping?
> **Q2** — What is the final unified issue taxonomy (derived from the data)?
> **Q3** — *(Confirmed: fine-tuning + RAG + prompts)*

All mappings are **derived bottom-up from actual label distributions** in the data.
The taxonomy emerges from the intersection of what CUAD annotates, what LEDGAR classifies,
and what Veridict's reviewers need to flag.
""")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CUAD_CLAUSES = DATA_DIR / "atticus" / "cuad_clauses.parquet"
LEDGAR_FILE = DATA_DIR / "legal_clauses" / "ledgar.parquet"

# ── Unified Issue Taxonomy ──────────────────────────────────────────────────
# 13 issue types derived from the union of CUAD + LEDGAR label coverage.
# Each type is a distinct risk category that Veridict reviewers (Harvey/Kira) flag.

ISSUE_TAXONOMY = {
    "liability_exposure": {
        "label": "Liability Exposure",
        "description": "Uncapped/capped liability, liquidated damages, indemnities, penalties, releases, exclusions",
        "color": "#e74c3c",
    },
    "restriction_clause": {
        "label": "Restriction Clause",
        "description": "Non-compete, exclusivity, no-solicit, non-disparagement, no-waiver provisions",
        "color": "#e67e22",
    },
    "ip_risk": {
        "label": "IP Risk",
        "description": "IP ownership assignment, license grants and restrictions, source code escrow",
        "color": "#f39c12",
    },
    "financial_obligation": {
        "label": "Financial Obligation",
        "description": "Prices, payments, fees, minimum commitments, revenue sharing, taxes, interest",
        "color": "#2ecc71",
    },
    "termination_risk": {
        "label": "Termination Risk",
        "description": "Termination for convenience, renewal terms, notice periods, force majeure, events of default",
        "color": "#1abc9c",
    },
    "governance_risk": {
        "label": "Governance Risk",
        "description": "Change of control, ROFR/ROFO/ROFN, anti-assignment, transfers, voting, liens",
        "color": "#3498db",
    },
    "compliance_obligation": {
        "label": "Compliance Obligation",
        "description": "Audit rights, sanctions, anti-corruption, regulatory compliance, ERISA, record-keeping",
        "color": "#9b59b6",
    },
    "dispute_resolution": {
        "label": "Dispute Resolution",
        "description": "Arbitration, jury waiver, covenant not to sue, remedies clauses",
        "color": "#8e44ad",
    },
    "confidentiality_risk": {
        "label": "Confidentiality Risk",
        "description": "Confidential information obligations, permitted disclosures, information handling",
        "color": "#2980b9",
    },
    "warranty_and_insurance": {
        "label": "Warranty & Insurance",
        "description": "Warranty duration, insurance requirements, base coverage and limits",
        "color": "#27ae60",
    },
    "jurisdictional_risk": {
        "label": "Jurisdictional Risk",
        "description": "Governing law, consent to jurisdiction, choice of forum provisions",
        "color": "#16a085",
    },
    "representation_risk": {
        "label": "Representation Risk",
        "description": "Representations & warranties, disclosures, no-conflicts, no-defaults, non-reliance",
        "color": "#d35400",
    },
    "third_party_risk": {
        "label": "Third Party Risk",
        "description": "Third party beneficiary rights, affiliate obligations",
        "color": "#c0392b",
    },
}

ISSUE_COLOR_MAP = {v["label"]: v["color"] for v in ISSUE_TAXONOMY.values()}
ISSUE_COLOR_MAP["Boilerplate (excluded)"] = "#bdc3c7"

# ── CUAD: Keyword → Issue Type ──────────────────────────────────────────────
# CUAD clause_type values are the full question strings, e.g.:
# "Highlight the parts of this contract related to \"Non-Compete\"..."
# We match by substring against the lowercased question text.

CUAD_KEYWORD_MAP = [
    # Liability
    ("uncapped liability",              "liability_exposure"),
    ("cap on liability",                "liability_exposure"),
    ("liquidated damages",              "liability_exposure"),
    # Restrictions
    ("non-compete",                     "restriction_clause"),
    ("exclusivity",                     "restriction_clause"),
    ("no-solicit of customers",         "restriction_clause"),
    ("no-solicit of employees",         "restriction_clause"),
    ("competitive restriction",         "restriction_clause"),
    ("non-disparagement",               "restriction_clause"),
    # IP
    ("ip ownership",                    "ip_risk"),
    ("joint ip",                        "ip_risk"),
    ("license grant",                   "ip_risk"),
    ("non-transferable license",        "ip_risk"),
    ("affiliate license",               "ip_risk"),
    ("unlimited/all-you-can-eat",       "ip_risk"),
    ("irrevocable or perpetual license","ip_risk"),
    ("source code escrow",              "ip_risk"),
    # Financial
    ("price restrictions",              "financial_obligation"),
    ("minimum commitment",              "financial_obligation"),
    ("volume restriction",              "financial_obligation"),
    ("revenue/profit sharing",          "financial_obligation"),
    ("most favored nation",             "financial_obligation"),
    # Termination
    ("termination for convenience",     "termination_risk"),
    ("renewal term",                    "termination_risk"),
    ("notice period to terminate",      "termination_risk"),
    ("expiration date",                 "termination_risk"),
    ("post-termination services",       "termination_risk"),
    # Governance
    ("change of control",               "governance_risk"),
    ("rofr/rofo/rofn",                  "governance_risk"),
    ("anti-assignment",                 "governance_risk"),
    # Compliance
    ("audit rights",                    "compliance_obligation"),
    # Warranty / Insurance
    ("warranty duration",               "warranty_and_insurance"),
    ("insurance",                       "warranty_and_insurance"),
    # Dispute
    ("covenant not to sue",             "dispute_resolution"),
    # Third party
    ("third party beneficiary",         "third_party_risk"),
    # Jurisdictional
    ("governing law",                   "jurisdictional_risk"),
]


def map_cuad_clause_type(clause_type: str) -> str:
    ct_lower = str(clause_type).lower()
    for keyword, issue_type in CUAD_KEYWORD_MAP:
        if keyword in ct_lower:
            return issue_type
    return "boilerplate"


# ── LEDGAR: Label Name → Issue Type ────────────────────────────────────────
# LEDGAR uses integer labels 0-99. The code list has 131 items but only
# indices 0-99 appear in the actual data (labels at index 100+ are unreachable).
# This mapping covers all 100 active labels.

LEDGAR_LABELS_LIST = [
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
]  # 100 items (indices 0-99)

LEDGAR_LABEL_MAP = {
    "Adjustments":            "financial_obligation",
    "Agreements":             "boilerplate",
    "Amendments":             "boilerplate",
    "Anti-Corruption Laws":   "compliance_obligation",
    "Applicable Laws":        "compliance_obligation",
    "Approvals":              "boilerplate",
    "Arbitration":            "dispute_resolution",
    "Assignments":            "governance_risk",
    "Audits":                 "compliance_obligation",
    "Base Coverage and Limits": "warranty_and_insurance",
    "Benefits":               "financial_obligation",
    "Binding Effects":        "boilerplate",
    "Books":                  "compliance_obligation",
    "Brokers":                "boilerplate",
    "Capitalization":         "boilerplate",
    "Change In Control":      "governance_risk",
    "Claims":                 "liability_exposure",
    "Closing":                "boilerplate",
    "Compliance With Laws":   "compliance_obligation",
    "Conditions":             "boilerplate",
    "Confidential Information": "confidentiality_risk",
    "Consent To Jurisdiction": "jurisdictional_risk",
    "Consequences":           "liability_exposure",
    "Consideration":          "financial_obligation",
    "Construction":           "boilerplate",
    "Cooperation":            "boilerplate",
    "Costs":                  "financial_obligation",
    "Counterparts":           "boilerplate",
    "Death":                  "boilerplate",
    "Defined Terms":          "boilerplate",
    "Definitions":            "boilerplate",
    "Delivery":               "financial_obligation",
    "Disclosures":            "representation_risk",
    "Duties":                 "compliance_obligation",
    "Effectiveness":          "boilerplate",
    "Elections":              "boilerplate",
    "Eligibility":            "boilerplate",
    "Entire Agreements":      "boilerplate",
    "Erisa":                  "compliance_obligation",
    "Escrow":                 "financial_obligation",
    "Events":                 "termination_risk",
    "Exchanges":              "financial_obligation",
    "Exclusions":             "liability_exposure",
    "Exercise Of Options":    "financial_obligation",
    "Expenses":               "financial_obligation",
    "Fees":                   "financial_obligation",
    "Financial Statements":   "representation_risk",
    "Financings":             "financial_obligation",
    "Force Majeure":          "termination_risk",
    "Further Assurances":     "boilerplate",
    "General":                "boilerplate",
    "Governing Laws":         "jurisdictional_risk",
    "Grants":                 "ip_risk",
    "Headings":               "boilerplate",
    "Idemnities":             "liability_exposure",
    "Indemnifications":       "liability_exposure",
    "Information":            "confidentiality_risk",
    "Insurance":              "warranty_and_insurance",
    "Intellectual Property":  "ip_risk",
    "Interest":               "financial_obligation",
    "Interpretations":        "boilerplate",
    "Jurisdictions":          "jurisdictional_risk",
    "Landlords":              "boilerplate",
    "Leases":                 "financial_obligation",
    "Liens":                  "governance_risk",
    "Limitations":            "liability_exposure",
    "Loans":                  "financial_obligation",
    "Loss":                   "liability_exposure",
    "Maintenance":            "financial_obligation",
    "Miscellaneous":          "boilerplate",
    "Modifications":          "boilerplate",
    "No Conflicts":           "representation_risk",
    "No Defaults":            "representation_risk",
    "No Waivers":             "restriction_clause",
    "Non-Competition":        "restriction_clause",
    "Non-Disparagement":      "restriction_clause",
    "Non-Reliance":           "representation_risk",
    "Non-Solicitation":       "restriction_clause",
    "Notices":                "boilerplate",
    "Obligations":            "compliance_obligation",
    "Options":                "financial_obligation",
    "Organizations":          "boilerplate",
    "Participations":         "financial_obligation",
    "Partnerships":           "boilerplate",
    "Payments":               "financial_obligation",
    "Penalties":              "liability_exposure",
    "Powers":                 "governance_risk",
    "Prices":                 "financial_obligation",
    "Procedures":             "boilerplate",
    "Proceeds":               "financial_obligation",
    "Provisions":             "boilerplate",
    "Publications":           "boilerplate",
    "Qualifications":         "representation_risk",
    "Receivables":            "financial_obligation",
    "Records":                "compliance_obligation",
    "Redemptions":            "financial_obligation",
    "Registrations":          "compliance_obligation",
    "Releases":               "liability_exposure",
    "Remedies":               "dispute_resolution",
    "Removal":                "governance_risk",
}


def map_ledgar_label(label_name: str) -> str:
    return LEDGAR_LABEL_MAP.get(label_name, "boilerplate")


def issue_display_label(issue_type: str) -> str:
    if issue_type in ISSUE_TAXONOMY:
        return ISSUE_TAXONOMY[issue_type]["label"]
    return "Boilerplate (excluded)"


# ── Data Loading ─────────────────────────────────────────────────────────────

@st.cache_data
def load_cuad():
    if not CUAD_CLAUSES.exists():
        return pd.DataFrame()
    df = pd.read_parquet(CUAD_CLAUSES)
    df["issue_type"] = df["clause_type"].apply(map_cuad_clause_type)
    df["issue_label"] = df["issue_type"].apply(issue_display_label)
    return df


@st.cache_data
def load_ledgar():
    if not LEDGAR_FILE.exists():
        return pd.DataFrame()
    df = pd.read_parquet(LEDGAR_FILE)
    if "label" in df.columns and df["label"].dtype in ("int64", "int32", "float64"):
        df["label_name"] = df["label"].map(
            lambda x: LEDGAR_LABELS_LIST[int(x)] if int(x) < len(LEDGAR_LABELS_LIST) else f"Label_{int(x)}"
        )
    elif "label" in df.columns:
        df["label_name"] = df["label"].astype(str)
    else:
        df["label_name"] = "Unknown"
    df["issue_type"] = df["label_name"].apply(map_ledgar_label)
    df["issue_label"] = df["issue_type"].apply(issue_display_label)
    return df


if not CUAD_CLAUSES.exists() and not LEDGAR_FILE.exists():
    st.error("No datasets found. Run `python scripts/download_datasets.py` first.")
    st.stop()

cuad_df = load_cuad()
ledgar_df = load_ledgar()

# ── Section 1: The Label Incompatibility Problem ─────────────────────────────

st.header("1. The Label Incompatibility Problem")

st.markdown("""
CUAD and LEDGAR use **completely different label vocabularies** with zero exact-string overlap.
They cannot be naively merged — a unified taxonomy is required before any training.
""")

cuad_labels = set(cuad_df["clause_type"].unique()) if not cuad_df.empty else set()
ledgar_labels = set(ledgar_df["label_name"].unique()) if not ledgar_df.empty else set()
shared = cuad_labels & ledgar_labels

col1, col2, col3, col4 = st.columns(4)
col1.metric("CUAD Categories", len(cuad_labels) if cuad_labels else "N/A (file missing)")
col2.metric("LEDGAR Labels (active)", len(ledgar_labels) if ledgar_labels else "N/A (file missing)")
col3.metric("Exact Name Overlap", len(shared))
col4.metric(
    "LEDGAR Code List Size",
    "131 items (but only 100 used)",
    delta="indices 100–130 unreachable",
    delta_color="off",
)

if len(shared) == 0:
    st.error(
        "**Zero shared label names.** Even where CUAD and LEDGAR cover the same risk "
        "(e.g., non-compete, indemnification), they use different vocabulary. "
        "A semantic mapping layer is mandatory."
    )

st.markdown("""
**Root cause:** CUAD uses *question-style category names* derived from legal review checklists
(e.g., `"Highlight the parts related to 'Non-Compete'..."`), while LEDGAR uses
*provision type names* from SEC contract provision classification
(e.g., `"Non-Competition"`). Same concept, zero string overlap.

> **Finding (LEDGAR label list):** The `LEDGAR_LABELS` list in the codebase contains 131 items
> but LEDGAR only has 100 classes (integer labels 0–99). Labels at indices 100–130
> (`Renewals`, `Rent`, ..., `Warranties`) **never appear in the actual data** and
> must be excluded from any mapping or training pipeline.
""")

# ── Section 2: Unified Issue Taxonomy (Answer to Q2) ─────────────────────────

st.header("2. Unified Issue Taxonomy — Answer to Q2")

st.markdown("""
**13 issue types** derived from the intersection of CUAD coverage, LEDGAR coverage,
and Veridict's reviewer objectives. Every type maps to a risk a legal reviewer would flag.
""")

taxonomy_rows = []
for key, val in ISSUE_TAXONOMY.items():
    taxonomy_rows.append({
        "Issue Type (key)": f"`{key}`",
        "Display Label": val["label"],
        "What it covers": val["description"],
    })
taxonomy_df = pd.DataFrame(taxonomy_rows)
st.dataframe(taxonomy_df, use_container_width=True, hide_index=True)

st.markdown("""
**Design principle:** These 13 types are the *minimum viable taxonomy* —
broad enough to aggregate the fragmented 100-label LEDGAR space,
specific enough to be meaningful for fine-tuning agent behavior.

Anything not mappable to one of these 13 types is classified as **boilerplate**
and excluded from the reviewer training set (but kept for RAG corpus).
""")

# ── Section 3: CUAD → Issue Type Mapping ─────────────────────────────────────

st.header("3. CUAD → Issue Type Mapping — Answer to Q1 (Part A)")

if not cuad_df.empty:
    # Per-clause-type breakdown
    cuad_type_counts = (
        cuad_df.groupby(["clause_type", "issue_type", "issue_label"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )

    # Summary by issue type
    cuad_issue_counts = (
        cuad_df.groupby(["issue_label", "issue_type"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    cuad_issue_counts["pct"] = (cuad_issue_counts["count"] / len(cuad_df) * 100).round(1)

    n_cuad_total = len(cuad_df)
    n_cuad_boilerplate = (cuad_df["issue_type"] == "boilerplate").sum()
    n_cuad_usable = n_cuad_total - n_cuad_boilerplate

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total CUAD Clauses", f"{n_cuad_total:,}")
    col2.metric("Mapped to Issue Types", f"{n_cuad_usable:,}", delta=f"{n_cuad_usable/n_cuad_total*100:.1f}%")
    col3.metric("Boilerplate (excluded)", f"{n_cuad_boilerplate:,}", delta=f"-{n_cuad_boilerplate/n_cuad_total*100:.1f}%", delta_color="inverse")
    col4.metric("Issue Types Covered", cuad_df[cuad_df["issue_type"] != "boilerplate"]["issue_type"].nunique())

    # Bar chart — distribution by issue type (excluding boilerplate)
    cuad_mapped = cuad_issue_counts[cuad_issue_counts["issue_type"] != "boilerplate"]
    fig = px.bar(
        cuad_mapped.sort_values("count"),
        x="count",
        y="issue_label",
        orientation="h",
        title="CUAD Clause Distribution by Issue Type (after mapping, boilerplate excluded)",
        color="issue_label",
        color_discrete_map=ISSUE_COLOR_MAP,
        text_auto=True,
    )
    fig.update_layout(showlegend=False, height=450)
    st.plotly_chart(fig, use_container_width=True)

    # Full mapping table (expandable)
    with st.expander("Full CUAD → Issue Type mapping table (all clause types)"):
        display_cuad = cuad_type_counts.copy()
        display_cuad["issue_label"] = display_cuad["issue_label"].replace(
            "Boilerplate (excluded)", "⚠️ Boilerplate (excluded)"
        )
        # Normalize clause_type to show just the core category name
        def extract_cuad_category(q: str) -> str:
            import re
            m = re.search(r"['\"]([^'\"]{3,50})['\"]", q)
            return m.group(1) if m else q[:60]
        display_cuad["Category"] = display_cuad["clause_type"].apply(extract_cuad_category)
        st.dataframe(
            display_cuad[["Category", "issue_label", "count"]].rename(
                columns={"issue_label": "Issue Type", "count": "Clause Count"}
            ),
            use_container_width=True,
            hide_index=True,
        )
else:
    st.warning("CUAD clauses file not found. Run `python scripts/download_datasets.py`.")

# ── Section 4: LEDGAR → Issue Type Mapping ───────────────────────────────────

st.header("4. LEDGAR → Issue Type Mapping — Answer to Q1 (Part B)")

if not ledgar_df.empty:
    ledgar_label_counts = (
        ledgar_df.groupby(["label_name", "issue_type", "issue_label"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    ledgar_issue_counts = (
        ledgar_df.groupby(["issue_label", "issue_type"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    ledgar_issue_counts["pct"] = (ledgar_issue_counts["count"] / len(ledgar_df) * 100).round(1)

    n_ledgar_total = len(ledgar_df)
    n_ledgar_boilerplate = (ledgar_df["issue_type"] == "boilerplate").sum()
    n_ledgar_usable = n_ledgar_total - n_ledgar_boilerplate

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total LEDGAR Samples", f"{n_ledgar_total:,}")
    col2.metric("Mapped to Issue Types", f"{n_ledgar_usable:,}", delta=f"{n_ledgar_usable/n_ledgar_total*100:.1f}%")
    col3.metric("Boilerplate (excluded)", f"{n_ledgar_boilerplate:,}", delta=f"-{n_ledgar_boilerplate/n_ledgar_total*100:.1f}%", delta_color="inverse")
    col4.metric("Issue Types Covered", ledgar_df[ledgar_df["issue_type"] != "boilerplate"]["issue_type"].nunique())

    # Bar chart — by issue type
    ledgar_mapped = ledgar_issue_counts[ledgar_issue_counts["issue_type"] != "boilerplate"]
    fig = px.bar(
        ledgar_mapped.sort_values("count"),
        x="count",
        y="issue_label",
        orientation="h",
        title="LEDGAR Sample Distribution by Issue Type (after mapping, boilerplate excluded)",
        color="issue_label",
        color_discrete_map=ISSUE_COLOR_MAP,
        text_auto=True,
    )
    fig.update_layout(showlegend=False, height=450)
    st.plotly_chart(fig, use_container_width=True)

    # Small-sample labels (< 100 in mapped issue type)
    st.subheader("LEDGAR: Small-Sample Labels — Merge Candidates")
    st.markdown("""
    Labels with < 100 samples in their issue type group are fragile for fine-tuning.
    Within the same issue type they are already merged by the mapping.
    Labels listed here contribute fewer than 100 samples to their group.
    """)

    small_labels = ledgar_label_counts[
        (ledgar_label_counts["count"] < 100) &
        (ledgar_label_counts["issue_type"] != "boilerplate")
    ].sort_values("count")

    if not small_labels.empty:
        fig = px.bar(
            small_labels,
            x="count",
            y="label_name",
            orientation="h",
            color="issue_label",
            title="LEDGAR Labels with < 100 Samples (already merged into issue type groups)",
            color_discrete_map=ISSUE_COLOR_MAP,
            text_auto=True,
        )
        fig.update_layout(height=max(350, len(small_labels) * 22), showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
        st.info(
            f"{len(small_labels)} LEDGAR labels have < 100 samples individually, but the taxonomy "
            f"mapping aggregates them — no label is trained alone. "
            f"The smallest resulting **issue type group** is what matters for imbalance."
        )
    else:
        st.success("No LEDGAR labels with < 100 samples (after mapping).")

    with st.expander("Full LEDGAR → Issue Type mapping table (all 100 labels)"):
        display_ledgar = ledgar_label_counts.copy()
        display_ledgar["issue_label"] = display_ledgar["issue_label"].replace(
            "Boilerplate (excluded)", "⚠️ Boilerplate (excluded)"
        )
        st.dataframe(
            display_ledgar[["label_name", "issue_label", "count"]].rename(
                columns={"label_name": "LEDGAR Label", "issue_label": "Issue Type", "count": "Samples"}
            ),
            use_container_width=True,
            hide_index=True,
        )
else:
    st.warning("LEDGAR file not found. Run `python scripts/download_datasets.py`.")

# ── Section 5: Cross-Dataset Coverage Matrix ─────────────────────────────────

st.header("5. Cross-Dataset Coverage Matrix")

st.markdown("""
Which issue types are covered by both datasets vs. only one?
Coverage gaps mean the model will only learn from one source for that risk type.
""")

if not cuad_df.empty and not ledgar_df.empty:
    issue_types_ordered = [v["label"] for v in ISSUE_TAXONOMY.values()]

    cuad_by_issue = (
        cuad_df[cuad_df["issue_type"] != "boilerplate"]
        .groupby("issue_label")
        .size()
        .reindex(issue_types_ordered, fill_value=0)
    )
    ledgar_by_issue = (
        ledgar_df[ledgar_df["issue_type"] != "boilerplate"]
        .groupby("issue_label")
        .size()
        .reindex(issue_types_ordered, fill_value=0)
    )

    coverage_df = pd.DataFrame({
        "Issue Type": issue_types_ordered,
        "CUAD": cuad_by_issue.values,
        "LEDGAR": ledgar_by_issue.values,
    })
    coverage_df["Combined"] = coverage_df["CUAD"] + coverage_df["LEDGAR"]
    coverage_df["Coverage"] = coverage_df.apply(
        lambda r: "Both" if r["CUAD"] > 0 and r["LEDGAR"] > 0
        else ("CUAD only" if r["CUAD"] > 0 else ("LEDGAR only" if r["LEDGAR"] > 0 else "Neither")),
        axis=1
    )

    # Heatmap
    heatmap_data = coverage_df.set_index("Issue Type")[["CUAD", "LEDGAR"]]
    fig = px.imshow(
        heatmap_data,
        title="Sample Count per Issue Type × Dataset (log scale for readability)",
        color_continuous_scale="Viridis",
        text_auto=True,
        zmin=0,
    )
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)

    # Coverage summary
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Covered by Both", (coverage_df["Coverage"] == "Both").sum())
    col2.metric("CUAD Only", (coverage_df["Coverage"] == "CUAD only").sum())
    col3.metric("LEDGAR Only", (coverage_df["Coverage"] == "LEDGAR only").sum())
    col4.metric("Neither (gap)", (coverage_df["Coverage"] == "Neither").sum())

    # Coverage bar chart
    fig2 = px.bar(
        coverage_df.sort_values("Combined", ascending=True),
        x=["CUAD", "LEDGAR"],
        y="Issue Type",
        orientation="h",
        title="Sample Count per Issue Type by Dataset (stacked)",
        barmode="stack",
        color_discrete_map={"CUAD": "#3498db", "LEDGAR": "#e74c3c"},
        text_auto=True,
    )
    fig2.update_layout(height=500)
    st.plotly_chart(fig2, use_container_width=True)

    # Show gaps
    gaps = coverage_df[coverage_df["Coverage"] == "Neither"]
    if not gaps.empty:
        st.warning(
            f"**Coverage gaps:** {', '.join(gaps['Issue Type'].tolist())} — "
            "no training examples from either dataset. These will need synthetic generation "
            "or manual annotation."
        )
    only_one = coverage_df[coverage_df["Coverage"].isin(["CUAD only", "LEDGAR only"])]
    if not only_one.empty:
        st.info(
            f"**Single-source types:** {', '.join(only_one['Issue Type'].tolist())} — "
            "model learns these from one dataset only. Lower robustness for these types."
        )

# ── Section 6: Post-Mapping Imbalance Analysis ───────────────────────────────

st.header("6. Post-Mapping Imbalance Analysis")

st.markdown("""
The critical question after mapping: is the combined imbalance **better or worse** than
the raw per-label imbalance reported in the individual EDA pages?
""")

if not cuad_df.empty and not ledgar_df.empty:
    combined_issue = pd.concat([
        cuad_df[cuad_df["issue_type"] != "boilerplate"][["issue_label", "issue_type"]].assign(dataset="CUAD"),
        ledgar_df[ledgar_df["issue_type"] != "boilerplate"][["issue_label", "issue_type"]].assign(dataset="LEDGAR"),
    ], ignore_index=True)

    combined_counts = combined_issue["issue_label"].value_counts().reset_index()
    combined_counts.columns = ["Issue Type", "Count"]
    combined_counts["Pct"] = (combined_counts["Count"] / len(combined_issue) * 100).round(1)

    max_count = combined_counts["Count"].max()
    min_count = combined_counts["Count"].min()
    imbalance_ratio = max_count / min_count if min_count > 0 else float("inf")

    col1, col2, col3 = st.columns(3)
    col1.metric("Dominant Issue Type", combined_counts.iloc[0]["Issue Type"])
    col2.metric("Dominant Count", f"{max_count:,}")
    col3.metric("Post-Mapping Imbalance Ratio", f"{imbalance_ratio:.1f}×")

    if imbalance_ratio > 20:
        st.error(
            f"Still severely imbalanced ({imbalance_ratio:.0f}×) after taxonomy mapping. "
            "Weighted loss / oversampling is mandatory."
        )
    elif imbalance_ratio > 5:
        st.warning(
            f"Moderate imbalance ({imbalance_ratio:.0f}×). Stratified sampling recommended."
        )
    else:
        st.success(f"Well-balanced after mapping ({imbalance_ratio:.1f}×).")

    # Before vs after imbalance comparison
    if not cuad_df.empty:
        cuad_raw_counts = cuad_df["clause_type"].value_counts()
        cuad_raw_ratio = cuad_raw_counts.max() / cuad_raw_counts.min() if cuad_raw_counts.min() > 0 else float("inf")
    else:
        cuad_raw_ratio = None

    if not ledgar_df.empty:
        ledgar_raw_counts = ledgar_df["label_name"].value_counts()
        ledgar_raw_ratio = ledgar_raw_counts.max() / ledgar_raw_counts.min() if ledgar_raw_counts.min() > 0 else float("inf")
    else:
        ledgar_raw_ratio = None

    comparison_data = []
    if cuad_raw_ratio:
        comparison_data.append({"Stage": "CUAD raw (41 categories)", "Imbalance Ratio": round(cuad_raw_ratio, 1)})
    if ledgar_raw_ratio:
        comparison_data.append({"Stage": "LEDGAR raw (100 labels)", "Imbalance Ratio": round(ledgar_raw_ratio, 1)})
    comparison_data.append({"Stage": f"After taxonomy mapping (13 types)", "Imbalance Ratio": round(imbalance_ratio, 1)})

    comp_df = pd.DataFrame(comparison_data)
    fig = px.bar(
        comp_df,
        x="Stage",
        y="Imbalance Ratio",
        title="Imbalance Ratio: Before vs. After Taxonomy Mapping",
        color="Stage",
        text_auto=True,
        color_discrete_sequence=["#e74c3c", "#e67e22", "#2ecc71"],
    )
    fig.add_hline(y=10, line_dash="dash", line_color="orange", annotation_text="Moderate threshold (10×)")
    fig.add_hline(y=50, line_dash="dash", line_color="red", annotation_text="Severe threshold (50×)")
    st.plotly_chart(fig, use_container_width=True)

    # Per-issue-type distribution
    fig2 = px.bar(
        combined_counts.sort_values("Count"),
        x="Count",
        y="Issue Type",
        orientation="h",
        title="Combined Training Set Distribution by Issue Type",
        color="Issue Type",
        color_discrete_map=ISSUE_COLOR_MAP,
        text="Pct",
    )
    fig2.update_traces(texttemplate="%{text}%", textposition="outside")
    fig2.update_layout(showlegend=False, height=500)
    st.plotly_chart(fig2, use_container_width=True)

# ── Section 7: Boilerplate Exclusion Summary ─────────────────────────────────

st.header("7. Boilerplate Exclusion Summary")

st.markdown("""
Boilerplate clauses are **excluded from the fine-tuning training set** but are
**retained for the RAG corpus** — they provide context that retrieval can surface.
""")

if not cuad_df.empty or not ledgar_df.empty:
    bp_rows = []
    if not cuad_df.empty:
        cuad_bp = cuad_df[cuad_df["issue_type"] == "boilerplate"]["clause_type"].value_counts().reset_index()
        cuad_bp.columns = ["Original Label", "Count"]
        cuad_bp["Dataset"] = "CUAD"
        bp_rows.append(cuad_bp)

    if not ledgar_df.empty:
        ledgar_bp = ledgar_df[ledgar_df["issue_type"] == "boilerplate"]["label_name"].value_counts().reset_index()
        ledgar_bp.columns = ["Original Label", "Count"]
        ledgar_bp["Dataset"] = "LEDGAR"
        bp_rows.append(ledgar_bp)

    if bp_rows:
        bp_df = pd.concat(bp_rows, ignore_index=True)

        # Normalize CUAD labels for display
        def short_label(s: str) -> str:
            import re
            m = re.search(r"['\"]([^'\"]{3,50})['\"]", s)
            return m.group(1) if m else s[:50]
        bp_df["Label"] = bp_df["Original Label"].apply(short_label)

        top_bp = bp_df.nlargest(20, "Count")
        fig = px.bar(
            top_bp.sort_values("Count"),
            x="Count",
            y="Label",
            orientation="h",
            color="Dataset",
            title="Top 20 Excluded Boilerplate Labels (by sample count)",
            color_discrete_map={"CUAD": "#3498db", "LEDGAR": "#e74c3c"},
            text_auto=True,
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)

        total_excluded = bp_df["Count"].sum()
        st.info(
            f"Total boilerplate excluded from fine-tuning: **{total_excluded:,} samples** "
            f"→ kept in RAG retrieval corpus."
        )

# ── Section 8: Fine-Tuning + RAG Architecture ────────────────────────────────

st.header("8. Training Architecture — Fine-Tuning + RAG + Prompts")

st.markdown("""
Given the confirmed strategy of **fine-tuning + RAG + prompts**, here is how each
dataset maps to each component:
""")

arch_data = {
    "Component": [
        "Fine-tuning (reviewer)",
        "Fine-tuning (reviewer)",
        "Fine-tuning (validator)",
        "RAG corpus",
        "RAG corpus",
    ],
    "Dataset": [
        "Atticus / CUAD (mapped clauses)",
        "LEDGAR (mapped clauses)",
        "ContractNLI",
        "Material Contracts (SEC)",
        "RISCBAC (if available)",
    ],
    "Role": [
        "Issue-tagged clause examples for Harvey/Kira reviewer training",
        "High-volume provision examples, aggregated by issue type",
        "Entailment/contradiction pairs for hallucination filter training",
        "Long-form contract documents for retrieval and chunking",
        "Synthetic insurance contracts for domain coverage",
    ],
    "Format": [
        "agent-conditioned SFT: {clause_text, issue_type, severity, recommendation}",
        "agent-conditioned SFT: {clause_text, issue_type, severity, recommendation}",
        "3-class classification: entailment / contradiction / neutral",
        "512-token chunks with 128-token overlap, vector-indexed",
        "512-token chunks with 128-token overlap, vector-indexed",
    ],
}

st.dataframe(pd.DataFrame(arch_data), use_container_width=True, hide_index=True)

# Projected training set sizes
st.subheader("Projected Training Set Sizes")

if not cuad_df.empty or not ledgar_df.empty:
    n_cuad_train = len(cuad_df[cuad_df["issue_type"] != "boilerplate"]) if not cuad_df.empty else 0
    n_ledgar_train = len(ledgar_df[ledgar_df["issue_type"] != "boilerplate"]) if not ledgar_df.empty else 0

    # Apply rough quality filter estimate (15.5% CUAD duplicates, ~0% LEDGAR duplicates)
    n_cuad_clean = int(n_cuad_train * (1 - 0.155) * (1 - 0.117))  # dedup + short filter
    n_ledgar_clean = int(n_ledgar_train * 1.0)  # LEDGAR already clean

    size_data = {
        "Stage": [
            "CUAD: total mapped (issue types only)",
            "CUAD: after dedup + short filter (est.)",
            "LEDGAR: total mapped (issue types only)",
            "LEDGAR: already clean (no dedup needed)",
            "Combined reviewer training set (est.)",
            "ContractNLI (validator, all splits)",
        ],
        "Samples": [
            n_cuad_train,
            n_cuad_clean,
            n_ledgar_train,
            n_ledgar_clean,
            n_cuad_clean + n_ledgar_clean,
            9788,
        ],
    }
    size_df = pd.DataFrame(size_data)
    size_df["Samples"] = size_df["Samples"].apply(lambda x: f"{x:,}")

    st.dataframe(size_df, use_container_width=True, hide_index=True)

    st.markdown(f"""
**Bottom line:**

- Reviewer fine-tuning set ≈ **{n_cuad_clean + n_ledgar_clean:,} examples** across 13 issue types
- After imbalance correction (weighted loss or capped oversampling): model sees balanced issue distribution
- Validator fine-tuning set: **~9,788 examples** (ContractNLI) with contradiction oversampled to ~30–40%
- RAG corpus: Material Contracts + RISCBAC → chunked at 512 tokens, vector-indexed
- Prompts: agent-conditioned templates per role (issue_discovery / false_positive_challenge / exploitability)
""")

st.success(
    "✅ Q1 answered: CUAD → 13 issue types via keyword matching; "
    "LEDGAR → 13 issue types via label name lookup. Full mapping tables above.  \n"
    "✅ Q2 answered: 13-type unified taxonomy derived from data coverage (Section 2).  \n"
    "✅ Q3 confirmed: Fine-tuning + RAG + prompts — architecture shown in Section 8."
)
