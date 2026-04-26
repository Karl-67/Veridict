"""Atticus (CUAD) Dataset EDA Dashboard."""

import html as _html
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path


def _short_label(s: str) -> str:
    """Extract the clause-type name from a CUAD question string."""
    if '"' in s:
        start = s.index('"') + 1
        end = s.index('"', start)
        return s[start:end]
    return s[:60]

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

# ── Section 8: Contract Explorer ────────────────────────────────────────────

st.header("8. Contract Explorer")
st.markdown("Select a contract to browse its full text and all annotated clause spans.")

if clauses_df is not None and not clauses_df.empty and raw_df is not None:
    all_contracts = sorted(clauses_df["contract_title"].unique())
    selected_contract = st.selectbox("Choose a contract", all_contracts, key="contract_select")

    contract_clauses = clauses_df[clauses_df["contract_title"] == selected_contract].copy()
    contract_context = contract_clauses["context"].iloc[0] if "context" in contract_clauses.columns else ""

    # Summary row
    col1, col2 = st.columns(2)
    col1.metric("Annotated clause spans", len(contract_clauses))
    col2.metric("Unique clause types", contract_clauses["clause_type"].nunique())

    # Clause type quick-filter
    st.markdown("**Filter by clause type (optional)**")
    all_types_in_contract = sorted(contract_clauses["clause_type"].unique())
    type_labels = {t: _short_label(t) for t in all_types_in_contract}
    label_to_type = {v: k for k, v in type_labels.items()}
    selected_labels = st.multiselect(
        "Clause types to highlight",
        options=list(label_to_type.keys()),
        default=list(label_to_type.keys())[:5],
        key="clause_type_filter",
    )
    selected_types = [label_to_type[l] for l in selected_labels] if selected_labels else []

    # ── Clause list ──────────────────────────────────────────────────────────
    st.subheader("Clause Spans in this Contract")
    display_df = contract_clauses[["clause_type", "clause_text"]].copy()
    display_df["clause_type"] = display_df["clause_type"].map(type_labels)
    if selected_types:
        display_df = display_df[contract_clauses["clause_type"].isin(selected_types)]
    st.dataframe(display_df.reset_index(drop=True), use_container_width=True, height=300)

    # ── Full-text with highlights ────────────────────────────────────────────
    st.subheader("Full Contract Text (with highlighted clauses)")

    # colour palette cycling for different clause types
    PALETTE = [
        "#ffd6a5", "#caffbf", "#9bf6ff", "#ffc6ff",
        "#fdffb6", "#a0c4ff", "#ffadad", "#d4e09b",
    ]
    type_color = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(all_types_in_contract)}

    # Build span list for selected types
    spans: list[tuple[int, int, str, str]] = []  # (start, end, clause_type, clause_text)
    if selected_types and contract_context:
        for _, row in contract_clauses[contract_clauses["clause_type"].isin(selected_types)].iterrows():
            ct = str(row["clause_text"])
            idx = contract_context.find(ct)
            if idx != -1:
                spans.append((idx, idx + len(ct), row["clause_type"], ct))

    # Remove overlapping spans (keep longest)
    spans.sort(key=lambda x: x[0])
    merged: list[tuple[int, int, str, str]] = []
    for sp in spans:
        if merged and sp[0] < merged[-1][1]:
            if sp[1] - sp[0] > merged[-1][1] - merged[-1][0]:
                merged[-1] = sp
        else:
            merged.append(sp)

    # Render HTML
    if contract_context:
        parts = []
        cursor = 0
        for start, end, ctype, _ in merged:
            if start > cursor:
                parts.append(_html.escape(contract_context[cursor:start]))
            color = type_color.get(ctype, "#ffffcc")
            label = _short_label(ctype)
            snippet = _html.escape(contract_context[start:end])
            parts.append(
                f'<mark style="background:{color};border-radius:3px;padding:1px 3px;" '
                f'title="{_html.escape(label)}">{snippet}'
                f'<sup style="font-size:0.65em;color:#555;margin-left:2px">[{_html.escape(label)}]</sup></mark>'
            )
            cursor = end
        parts.append(_html.escape(contract_context[cursor:]))

        highlighted_html = (
            '<div style="font-family:monospace;font-size:0.82rem;line-height:1.6;'
            'white-space:pre-wrap;border:1px solid #ddd;border-radius:6px;'
            'padding:16px;max-height:520px;overflow-y:auto;background:#fafafa;color:#1a1a1a">'
            + "".join(parts)
            + "</div>"
        )
        # Legend
        legend_items = "".join(
            f'<span style="background:{type_color[t]};padding:2px 8px;border-radius:3px;'
            f'margin:2px;display:inline-block;font-size:0.75rem">{_html.escape(_short_label(t))}</span>'
            for t in selected_types
        )
        st.markdown(
            f'<div style="margin-bottom:6px">{"Legend: " + legend_items if legend_items else ""}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(highlighted_html, unsafe_allow_html=True)
    else:
        st.info("No contract text available for this contract.")
else:
    st.info("Contract Explorer requires both cuad.parquet and cuad_clauses.parquet.")

# ── Section 9: Clause Browser ────────────────────────────────────────────────

st.header("9. Clause Type Browser")
st.markdown("Pick a clause type and browse sample annotated spans across all contracts.")

if clauses_df is not None and not clauses_df.empty:
    all_types = sorted(clauses_df["clause_type"].unique())
    short_labels_all = [_short_label(t) for t in all_types]
    label_to_full = dict(zip(short_labels_all, all_types))

    selected_type_label = st.selectbox("Clause type", short_labels_all, key="browser_type")
    selected_full_type = label_to_full[selected_type_label]

    type_rows = clauses_df[clauses_df["clause_type"] == selected_full_type].copy()
    type_rows["word_count"] = type_rows["clause_text"].str.split().str.len()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total spans", len(type_rows))
    col2.metric("Unique contracts", type_rows["contract_title"].nunique())
    col3.metric("Avg word count", f"{type_rows['word_count'].mean():.1f}")

    # Word count histogram for this clause type
    fig_wc = px.histogram(
        type_rows,
        x="word_count",
        nbins=40,
        title=f'Word Count Distribution — "{selected_type_label}"',
        labels={"word_count": "Word Count"},
        color_discrete_sequence=["#e74c3c"],
    )
    fig_wc.update_layout(height=300, bargap=0.05)
    st.plotly_chart(fig_wc, use_container_width=True)

    # Sample cards
    n_samples = st.slider("Number of samples to display", 3, 20, 5, key="n_samples")
    sample_rows = type_rows.sample(min(n_samples, len(type_rows)), random_state=42)

    st.markdown(f"**{min(n_samples, len(type_rows))} random samples:**")
    for i, (_, row) in enumerate(sample_rows.iterrows(), 1):
        with st.expander(f"#{i} — {row['contract_title'][:70]}…", expanded=(i == 1)):
            st.markdown(
                f'<div style="background:#f0f4ff;border-left:4px solid #3498db;'
                f'padding:10px 14px;border-radius:4px;font-size:0.85rem;'
                f'white-space:pre-wrap;font-family:monospace;color:#1a1a1a">{_html.escape(str(row["clause_text"]))}</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"Word count: {row['word_count']}  |  Contract: {row['contract_title']}")
else:
    st.info("Clause Browser requires cuad_clauses.parquet.")
