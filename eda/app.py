"""Veridict — Legal Contract Dataset EDA Dashboard.

Multi-page Streamlit app for exploring legal contract datasets.
Run with: streamlit run eda/app.py
"""

import streamlit as st

st.set_page_config(
    page_title="Veridict — Legal Contract EDA",
    page_icon="⚖️",
    layout="wide",
)

st.title("⚖️ Veridict — Legal Contract Dataset EDA")

st.markdown("""
Welcome to the **Veridict** EDA pipeline. Use the sidebar to navigate between dashboards:

- **Atticus (CUAD)** — 510 contracts, 13k+ clause annotations, 41 clause categories
- **Legal Clauses (LEDGAR)** — Contract provision classification, 100 provision types
- **Combined** — Cross-dataset analysis, LLM training readiness

### Getting Started

1. Run `python scripts/download_datasets.py` to download datasets
2. Navigate to individual dataset pages via the sidebar
3. Explore distributions, quality metrics, and LLM readiness analysis
""")

st.sidebar.success("Select a dashboard above.")
