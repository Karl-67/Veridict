#!/usr/bin/env python3
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
"""
curate_dataset.py — Data Curation Pipeline

Produces:
  data/curated/dataset_a/reviewer_{train,val,test}.jsonl  — Reviewer SFT (Dataset A)
  data/curated/dataset_b/validator_{train,val,test}.jsonl — Validator SFT (Dataset B)
  data/curated/dataset_c/maud_{train,val,test}.jsonl      — M&A Reviewer SFT (Dataset C)
  data/curated/rl_pool.jsonl                              — RL curation pool (no split)
  data/curated/boilerplate_archive.jsonl                  — Preserved for RAG
  data/curated/split_manifest.json                        — Split ledger for curate_golden.py

Phases:
  A — Load + clean  (CUAD dedup + short filter wc>=10; LEDGAR label decode; MAUD dedup + wc>=10)
  B — Taxonomy projection  (-> 13 unified issue types; MAUD keeps native categories)
  C — Boilerplate archive  (excluded from SFT, kept for RAG)
  G — Document-level split  (BEFORE weak supervision, prevents leakage)
  D — Weak supervision  (description, recommendation, severity=weak label)
  E — Role augmentation  (3 roles × 1 branch per clause)
  F — Imbalance correction  (class_weight field primary; capped oversampling secondary)
  H — ContractNLI validator dataset  (retain/reject/uncertain + contradiction oversampling)
  I — MAUD M&A reviewer dataset  (deal-point QA + rare-category oversampling)
  J — RL pool  (train-split rows from A+B+C combined, no split applied)

Design notes (from review):
  - Branch (harvey/kira) reflects context source, NOT role:
      harvey = internal policy context (liability, IP, financial, termination, …)
      kira   = compliance / regulatory context (compliance, jurisdiction, representation, confidentiality)
  - agent_role is independent of branch (all 3 roles apply to both branches)
  - severity is a weak/heuristic label; carries severity_confidence="weak"
  - Oversampling is capped at MAX_COPIES_PER_ROW per unique row; class_weight is the primary signal
  - Boilerplate is archived, not discarded
  - MAUD splits are official document-level splits — used as-is, no re-splitting
  - ContractNLI dev split -> renamed val for consistency
"""

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = DATA_DIR / "curated"
CUAD_FILE = DATA_DIR / "atticus" / "cuad_clauses.parquet"
LEDGAR_FILE = DATA_DIR / "legal_clauses" / "ledgar.parquet"
CNLI_FILE = DATA_DIR / "contractnli" / "contractnli.parquet"
MAUD_FILE = DATA_DIR / "maud" / "maud.parquet"

for _d in [OUT_DIR, OUT_DIR / "dataset_a", OUT_DIR / "dataset_b", OUT_DIR / "dataset_c", OUT_DIR / "golden"]:
    _d.mkdir(parents=True, exist_ok=True)

random.seed(42)

MAX_COPIES_PER_ROW = 3   # cap for oversampling (beyond this, rely on class_weight)

# ══════════════════════════════════════════════════════════════════════════════
# Taxonomy — copied from eda/pages/7_Taxonomy_Mapping.py (no Streamlit import)
# ══════════════════════════════════════════════════════════════════════════════

ISSUE_TAXONOMY = {
    "liability_exposure":   {"label": "Liability Exposure"},
    "restriction_clause":   {"label": "Restriction Clause"},
    "ip_risk":              {"label": "IP Risk"},
    "financial_obligation": {"label": "Financial Obligation"},
    "termination_risk":     {"label": "Termination Risk"},
    "governance_risk":      {"label": "Governance Risk"},
    "compliance_obligation":{"label": "Compliance Obligation"},
    "dispute_resolution":   {"label": "Dispute Resolution"},
    "confidentiality_risk": {"label": "Confidentiality Risk"},
    "warranty_and_insurance":{"label": "Warranty & Insurance"},
    "jurisdictional_risk":  {"label": "Jurisdictional Risk"},
    "representation_risk":  {"label": "Representation Risk"},
    "third_party_risk":     {"label": "Third Party Risk"},
}

CUAD_KEYWORD_MAP = [
    ("uncapped liability",               "liability_exposure"),
    ("cap on liability",                 "liability_exposure"),
    ("liquidated damages",               "liability_exposure"),
    ("non-compete",                      "restriction_clause"),
    ("exclusivity",                      "restriction_clause"),
    ("no-solicit of customers",          "restriction_clause"),
    ("no-solicit of employees",          "restriction_clause"),
    ("competitive restriction",          "restriction_clause"),
    ("non-disparagement",                "restriction_clause"),
    ("ip ownership",                     "ip_risk"),
    ("joint ip",                         "ip_risk"),
    ("license grant",                    "ip_risk"),
    ("non-transferable license",         "ip_risk"),
    ("affiliate license",                "ip_risk"),
    ("unlimited/all-you-can-eat",        "ip_risk"),
    ("irrevocable or perpetual license", "ip_risk"),
    ("source code escrow",               "ip_risk"),
    ("price restrictions",               "financial_obligation"),
    ("minimum commitment",               "financial_obligation"),
    ("volume restriction",               "financial_obligation"),
    ("revenue/profit sharing",           "financial_obligation"),
    ("most favored nation",              "financial_obligation"),
    ("termination for convenience",      "termination_risk"),
    ("renewal term",                     "termination_risk"),
    ("notice period to terminate",       "termination_risk"),
    ("expiration date",                  "termination_risk"),
    ("post-termination services",        "termination_risk"),
    ("change of control",                "governance_risk"),
    ("rofr/rofo/rofn",                   "governance_risk"),
    ("anti-assignment",                  "governance_risk"),
    ("audit rights",                     "compliance_obligation"),
    ("warranty duration",                "warranty_and_insurance"),
    ("insurance",                        "warranty_and_insurance"),
    ("covenant not to sue",              "dispute_resolution"),
    ("third party beneficiary",          "third_party_risk"),
    ("governing law",                    "jurisdictional_risk"),
]

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


def map_cuad_clause_type(clause_type: str) -> str:
    ct_lower = str(clause_type).lower()
    for keyword, issue_type in CUAD_KEYWORD_MAP:
        if keyword in ct_lower:
            return issue_type
    return "boilerplate"


def map_ledgar_label(label_name: str) -> str:
    return LEDGAR_LABEL_MAP.get(label_name, "boilerplate")


# ══════════════════════════════════════════════════════════════════════════════
# Branch assignment — based on context source, independent of agent_role
#   harvey = internal policy / commercial context
#   kira   = compliance / regulatory context
# ══════════════════════════════════════════════════════════════════════════════

KIRA_ISSUE_TYPES = {
    "compliance_obligation",
    "jurisdictional_risk",
    "representation_risk",
    "confidentiality_risk",
}


def get_branch(issue_type: str) -> str:
    return "kira" if issue_type in KIRA_ISSUE_TYPES else "harvey"


# ══════════════════════════════════════════════════════════════════════════════
# Severity — weak/heuristic label. NOT gold. Use severity_confidence field.
# ══════════════════════════════════════════════════════════════════════════════

SEVERITY_MAP = {
    "liability_exposure":    "high",
    "ip_risk":               "high",
    "termination_risk":      "high",
    "governance_risk":       "high",
    "restriction_clause":    "medium",
    "financial_obligation":  "medium",
    "compliance_obligation": "medium",
    "confidentiality_risk":  "medium",
    "representation_risk":   "medium",
    "warranty_and_insurance":"medium",
    "dispute_resolution":    "low",
    "jurisdictional_risk":   "low",
    "third_party_risk":      "low",
}

# ══════════════════════════════════════════════════════════════════════════════
# Issue templates — 13 types × 3 roles = 39 entries
# ══════════════════════════════════════════════════════════════════════════════

ROLES = ["issue_discovery", "false_positive_challenge", "exploitability_impact"]

ISSUE_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "liability_exposure": {
        "issue_discovery": {
            "desc": "This clause raises a liability concern that may expose the client to uncapped or disproportionate financial risk.",
            "rec":  "Negotiate a mutual liability cap tied to contract value, exclude consequential damages, and define indemnification triggers precisely.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this liability provision may reflect standard mutual indemnification practice common in this contract type.",
            "rec":  "Verify whether the liability exposure is mutual and proportionate to the deal size before escalating to the client.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could leverage this clause to seek damages well beyond the contract value following a minor breach.",
            "rec":  "Insert a liquidated damages cap, negotiate a consequential loss exclusion, and add a materiality threshold for claims.",
        },
    },
    "restriction_clause": {
        "issue_discovery": {
            "desc": "This clause imposes a competitive restriction that may significantly limit the client's operational freedom.",
            "rec":  "Narrow the scope (geography, duration, activities) and ensure restrictions are mutual or justified by the deal context.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this restriction may be a standard non-compete that is proportionate to the deal and enforceable in the jurisdiction.",
            "rec":  "Confirm the restriction's geographic and temporal scope before recommending renegotiation.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could use this restriction clause to block the client from entering adjacent markets after termination.",
            "rec":  "Limit post-termination restrictions to 12 months, narrow to directly competitive activities, and add a geographic carve-out.",
        },
    },
    "ip_risk": {
        "issue_discovery": {
            "desc": "This clause involves an IP transfer or license grant that may expose the client to loss of key intellectual property rights.",
            "rec":  "Clarify ownership, limit license scope to the deal purpose, and retain rights to background IP and improvements.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this IP provision may be a standard license grant limited in scope and duration typical in this industry.",
            "rec":  "Confirm that the license is non-exclusive and field-of-use restricted before escalating as a risk item.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could interpret this clause as a broad assignment of all IP developed during the engagement.",
            "rec":  "Replace 'assign' with 'license', add a work-for-hire carve-out for background IP, and specify that improvements remain with the creator.",
        },
    },
    "financial_obligation": {
        "issue_discovery": {
            "desc": "This clause creates a financial obligation that may exceed the client's expected commitment under the contract.",
            "rec":  "Cap total payment exposure, add payment milestones tied to deliverables, and negotiate a most-favored-nation pricing clause.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this financial obligation may reflect a standard fee structure that is market-rate and well-defined.",
            "rec":  "Compare the payment terms to market benchmarks and verify that all fees are clearly defined before flagging as a risk.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could invoke this clause to demand accelerated payment or impose penalties for minor payment delays.",
            "rec":  "Add a cure period before any default is triggered, cap late fees, and ensure payment triggers require written notice.",
        },
    },
    "termination_risk": {
        "issue_discovery": {
            "desc": "This clause contains termination rights or renewal terms that may create operational continuity risk for the client.",
            "rec":  "Negotiate reasonable notice periods, limit termination-for-convenience rights, and add auto-renewal opt-out provisions.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this termination clause may provide standard bilateral rights that protect both parties equally.",
            "rec":  "Verify whether termination rights are mutual and whether notice periods are adequate before escalating.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could terminate this agreement with minimal notice, leaving the client without a key service or supply relationship.",
            "rec":  "Require a minimum 90-day notice period, add a transition assistance obligation, and restrict termination during active project milestones.",
        },
    },
    "governance_risk": {
        "issue_discovery": {
            "desc": "This clause touches on change of control, assignment, or transfer rights that may affect contract continuity.",
            "rec":  "Add anti-assignment restrictions, require consent for change of control, and include step-in rights in case of counterparty insolvency.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this governance clause may reflect standard anti-assignment provisions found in most commercial contracts.",
            "rec":  "Confirm that assignment restrictions are mutual and that carve-outs for corporate reorganizations are present before escalating.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could assign this contract to a competitor or a less creditworthy entity without the client's consent.",
            "rec":  "Require prior written consent for any assignment, define change of control explicitly, and add a termination right upon unauthorized transfer.",
        },
    },
    "compliance_obligation": {
        "issue_discovery": {
            "desc": "This clause imposes a compliance or regulatory obligation that may require significant internal process changes.",
            "rec":  "Identify all affected regulatory regimes, allocate compliance costs, and include a material change clause for future regulatory shifts.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this compliance obligation may be a standard audit rights provision that is non-intrusive in practice.",
            "rec":  "Confirm the audit scope, frequency, and notice requirements before treating this as a substantive risk.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could use this compliance clause to conduct frequent or intrusive audits that disrupt client operations.",
            "rec":  "Limit audit frequency to once per year, require 30 days advance notice, and restrict audit scope to compliance-specific records.",
        },
    },
    "dispute_resolution": {
        "issue_discovery": {
            "desc": "This clause establishes a dispute resolution mechanism that may limit the client's litigation options.",
            "rec":  "Review arbitration rules, venue, and seat; ensure the client retains injunctive relief rights; and negotiate a cost-allocation provision.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this arbitration clause may be standard and may actually reduce dispute costs compared to litigation.",
            "rec":  "Evaluate whether arbitration is advantageous given the contract value and typical dispute types before recommending changes.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could rely on this clause to force arbitration in an inconvenient jurisdiction, increasing the client's dispute resolution costs.",
            "rec":  "Specify a neutral venue, require English-language proceedings, and ensure discovery rights are preserved in any arbitration clause.",
        },
    },
    "confidentiality_risk": {
        "issue_discovery": {
            "desc": "This clause contains confidentiality obligations that may be overly broad or inadequately protect the client's information.",
            "rec":  "Define confidential information precisely, include standard exceptions (public domain, independently developed), and set a clear term.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this confidentiality provision may reflect a standard NDA structure with balanced obligations.",
            "rec":  "Verify that confidentiality obligations are mutual and that the definition of confidential information is appropriately scoped.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could interpret this clause to prevent the client from disclosing information required by regulators or auditors.",
            "rec":  "Add explicit carve-outs for regulatory disclosures, court orders, and professional advisors; narrow the confidentiality term to 3–5 years.",
        },
    },
    "warranty_and_insurance": {
        "issue_discovery": {
            "desc": "This clause contains warranty or insurance requirements that may create unanticipated obligations for the client.",
            "rec":  "Verify insurance coverage requirements against existing policies, negotiate warranty exclusions, and cap warranty liability separately.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this warranty provision may reflect standard commercial warranty terms that are well-defined and time-limited.",
            "rec":  "Confirm that warranty scope is limited to the specific deliverables and that the warranty period is reasonable.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could use this warranty clause to demand extensive remediation or replacement of services for minor defects.",
            "rec":  "Define acceptance criteria precisely, limit warranty remedies to repair or replacement, and exclude implied warranties by name.",
        },
    },
    "jurisdictional_risk": {
        "issue_discovery": {
            "desc": "This clause establishes a governing law or forum selection that may be unfavorable to the client.",
            "rec":  "Negotiate a neutral jurisdiction, add a choice-of-law clause specifying the client's preferred state, and ensure enforcement is practical.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this governing law clause may select a well-established commercial law jurisdiction that is neutral and predictable.",
            "rec":  "Assess the counterparty's jurisdiction and confirm that the selected governing law does not disadvantage the client.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could rely on this jurisdiction clause to litigate disputes in a foreign court, significantly increasing enforcement costs.",
            "rec":  "Negotiate for the client's home jurisdiction or a mutually agreed neutral forum, and add a reciprocal enforcement clause.",
        },
    },
    "representation_risk": {
        "issue_discovery": {
            "desc": "This clause contains representations or disclosures that may expose the client to liability for inaccuracies.",
            "rec":  "Qualify all representations to the client's knowledge, add materiality thresholds, and include a sandbagging protection clause.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this representation may be a standard 'no conflicts' provision that is routinely made in commercial contracts.",
            "rec":  "Verify whether the representation is knowledge-qualified and whether exceptions and schedules are appropriately comprehensive.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could invoke this representation clause to claim breach based on minor disclosure gaps or technical inaccuracies.",
            "rec":  "Add a materiality qualifier to all representations, limit reliance to disclosed information, and include a cure period before breach is actionable.",
        },
    },
    "third_party_risk": {
        "issue_discovery": {
            "desc": "This clause creates or excludes third party rights in a way that may affect the client's obligations or protections.",
            "rec":  "Clarify which third parties can enforce the contract, exclude unintended beneficiaries by name, and limit inuring benefits to the parties.",
        },
        "false_positive_challenge": {
            "desc": "While flagged, this third party beneficiary clause may simply formalize affiliate rights that are expected and mutual.",
            "rec":  "Confirm that third party rights are limited to affiliates and that no unintended parties gain enforcement rights.",
        },
        "exploitability_impact": {
            "desc": "A counterparty could rely on this clause to allow affiliated entities to enforce obligations the client believed were bilateral.",
            "rec":  "Explicitly disclaim third party beneficiary rights for all parties other than named affiliates, and add a no-assignment of beneficiary rights provision.",
        },
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def make_excerpt(text: str, max_chars: int = 80) -> str:
    """Return up to max_chars of text, truncated at a word boundary."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:")


def row_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def short_id(prefix: str, text: str, role: str) -> str:
    digest = row_hash(f"{text}|{role}")[:8]
    return f"{prefix}_{digest}_{role[:4]}"


# ══════════════════════════════════════════════════════════════════════════════
# Phase A — Load + clean
# ══════════════════════════════════════════════════════════════════════════════


def load_cuad() -> pd.DataFrame:
    df = pd.read_parquet(CUAD_FILE)
    before = len(df)
    df = df.drop_duplicates(subset=["clause_text"])
    after_dedup = len(df)
    # wc>=10: removes is_impossible answer fragments (22% of raw CUAD are <10 words)
    df = df[df["clause_text"].str.split().str.len() >= 10].copy()
    after_short = len(df)
    print(f"CUAD: {before:,} total -> {after_dedup:,} after dedup -> {after_short:,} after short-text filter (wc>=10)")
    return df.reset_index(drop=True)


def load_maud() -> pd.DataFrame:
    """Load MAUD, deduplicate on passage text, filter very-short rows."""
    df = pd.read_parquet(MAUD_FILE)
    before = len(df)
    df = df.drop_duplicates(subset=["text"])
    after_dedup = len(df)
    df = df[df["text"].astype(str).str.split().str.len() >= 10].copy()
    after_short = len(df)
    # normalise split names: validation -> val
    df["split"] = df["split"].str.lower().replace({"validation": "val", "dev": "val"})
    print(f"MAUD: {before:,} total -> {after_dedup:,} after dedup -> {after_short:,} after short-text filter (wc>=10)")
    return df.reset_index(drop=True)


def load_ledgar() -> pd.DataFrame:
    df = pd.read_parquet(LEDGAR_FILE)
    if df["label"].dtype in ("int64", "int32", "float64"):
        df["label_name"] = df["label"].map(
            lambda x: LEDGAR_LABELS_LIST[int(x)] if 0 <= int(x) < len(LEDGAR_LABELS_LIST) else f"Label_{int(x)}"
        )
    else:
        df["label_name"] = df["label"].astype(str)
    print(f"LEDGAR: {len(df):,} rows loaded")
    return df.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# Phase B+C — Taxonomy projection + boilerplate archive
# ══════════════════════════════════════════════════════════════════════════════


def project_cuad(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["issue_type"] = df["clause_type"].apply(map_cuad_clause_type)
    usable = df[df["issue_type"] != "boilerplate"].copy()
    boilerplate = df[df["issue_type"] == "boilerplate"].copy()
    print(f"  CUAD -> {len(usable):,} usable, {len(boilerplate):,} boilerplate")
    return usable, boilerplate


def project_ledgar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["issue_type"] = df["label_name"].apply(map_ledgar_label)
    usable = df[df["issue_type"] != "boilerplate"].copy()
    boilerplate = df[df["issue_type"] == "boilerplate"].copy()
    print(f"  LEDGAR -> {len(usable):,} usable, {len(boilerplate):,} boilerplate")
    return usable, boilerplate


def save_boilerplate_archive(cuad_bp: pd.DataFrame, ledgar_bp: pd.DataFrame) -> None:
    rows = []
    for _, r in cuad_bp.iterrows():
        rows.append({
            "source": "cuad",
            "clause_text": str(r.get("clause_text", "")),
            "original_label": str(r.get("clause_type", "")),
            "contract_id": str(r.get("contract_title", "")),
        })
    for _, r in ledgar_bp.iterrows():
        rows.append({
            "source": "ledgar",
            "clause_text": str(r.get("text", "")),
            "original_label": str(r.get("label_name", "")),
        })
    out = OUT_DIR / "boilerplate_archive.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Boilerplate archive: {len(rows):,} rows -> {out}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase G — Document-level split (BEFORE weak supervision)
# ══════════════════════════════════════════════════════════════════════════════


def split_cuad(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split by contract_title so all clauses from a contract go to one bucket."""
    contracts = list(df["contract_title"].unique())

    # Stratify by the most common issue_type per contract
    type_to_contracts: dict[str, list[str]] = defaultdict(list)
    for ct in contracts:
        primary = df[df["contract_title"] == ct]["issue_type"].mode()[0]
        type_to_contracts[primary].append(ct)

    train_c, val_c, test_c, golden_c = [], [], [], []
    for issue_type, ct_list in type_to_contracts.items():
        random.shuffle(ct_list)
        n = len(ct_list)
        n_train = max(1, round(n * 0.70))
        n_val   = max(1, round(n * 0.10))
        n_test  = max(1, round(n * 0.10))
        # remainder -> golden
        train_c.extend(ct_list[:n_train])
        val_c.extend(ct_list[n_train:n_train + n_val])
        test_c.extend(ct_list[n_train + n_val:n_train + n_val + n_test])
        golden_c.extend(ct_list[n_train + n_val + n_test:])

    splits = {"train": set(train_c), "val": set(val_c), "test": set(test_c), "golden": set(golden_c)}

    def tag(r: pd.Series) -> str:
        ct = r["contract_title"]
        for s, ct_set in splits.items():
            if ct in ct_set:
                return s
        return "train"

    df = df.copy()
    df["split"] = df.apply(tag, axis=1)

    parts = {s: df[df["split"] == s].copy() for s in ["train", "val", "test", "golden"]}
    print(
        f"  CUAD splits: train={len(parts['train']):,} val={len(parts['val']):,} "
        f"test={len(parts['test']):,} golden={len(parts['golden']):,} "
        f"(across {len(contracts)} contracts)"
    )
    return parts["train"], parts["val"], parts["test"], parts["golden"]


def split_ledgar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Use the official split column; divide test 50/50 into test + golden candidates."""
    train  = df[df["split"] == "train"].copy()
    val    = df[df["split"] == "validation"].copy()
    test_all = df[df["split"] == "test"].sample(frac=1, random_state=42).reset_index(drop=True)

    mid    = len(test_all) // 2
    test   = test_all.iloc[:mid].copy()
    golden = test_all.iloc[mid:].copy()

    train["split"]  = "train"
    val["split"]    = "val"
    test["split"]   = "test"
    golden["split"] = "golden"

    print(
        f"  LEDGAR splits: train={len(train):,} val={len(val):,} "
        f"test={len(test):,} golden={len(golden):,}"
    )
    return train, val, test, golden


def save_split_manifest(
    cuad_train: pd.DataFrame, cuad_val: pd.DataFrame, cuad_test: pd.DataFrame, cuad_golden: pd.DataFrame,
    ledgar_train: pd.DataFrame, ledgar_val: pd.DataFrame, ledgar_test: pd.DataFrame, ledgar_golden: pd.DataFrame,
    maud_df: Optional[pd.DataFrame] = None,
) -> None:
    manifest: dict = {
        "cuad_contracts": {
            "train":  sorted(cuad_train["contract_title"].unique().tolist()),
            "val":    sorted(cuad_val["contract_title"].unique().tolist()),
            "test":   sorted(cuad_test["contract_title"].unique().tolist()),
            "golden": sorted(cuad_golden["contract_title"].unique().tolist()),
        },
        "ledgar_row_indices": {
            "train":  sorted(ledgar_train.index.tolist()),
            "val":    sorted(ledgar_val.index.tolist()),
            "test":   sorted(ledgar_test.index.tolist()),
            "golden": sorted(ledgar_golden.index.tolist()),
        },
    }
    if maud_df is not None and "contract_name" in maud_df.columns and "split" in maud_df.columns:
        manifest["maud_contracts"] = {
            s: sorted(maud_df[maud_df["split"] == s]["contract_name"].unique().tolist())
            for s in ["train", "val", "test"]
        }
    out = OUT_DIR / "split_manifest.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Split manifest -> {out}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase D+E — Weak supervision + role augmentation
# ══════════════════════════════════════════════════════════════════════════════


def generate_reviewer_rows(df: pd.DataFrame, source: str) -> list[dict]:
    """Generate 3 output rows per clause (one per role). Branch is fixed by issue_type."""
    rows = []
    text_col = "clause_text" if "clause_text" in df.columns else "text"

    for _, row in df.iterrows():
        issue_type = row["issue_type"]
        templates  = ISSUE_TEMPLATES.get(issue_type)
        if not templates:
            continue

        clause_text = str(row.get(text_col, "")).strip()
        if not clause_text:
            continue

        excerpt    = make_excerpt(clause_text)
        severity   = SEVERITY_MAP.get(issue_type, "medium")
        branch     = get_branch(issue_type)
        split      = str(row.get("split", "train"))
        contract_id = str(row.get("contract_title", row.get("label_name", "")))

        for role in ROLES:
            tmpl = templates[role]
            description = f'The clause provides that "{excerpt}". {tmpl["desc"]}'
            rec_id = short_id(source, clause_text, role)

            rows.append({
                "id":                   rec_id,
                "source":               source,
                "contract_id":          contract_id,
                "clause_text":          clause_text,
                "issue_type":           issue_type,
                "severity":             severity,
                "severity_confidence":  "weak",   # heuristic — not gold
                "description":          description,
                "recommendation":       tmpl["rec"],
                "agent_role":           role,
                "branch":               branch,
                "split":                split,
            })

    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Phase F — Imbalance correction (train split only)
#   Primary:   class_weight field (inverse frequency) — used by training loop
#   Secondary: limited oversampling, capped at MAX_COPIES_PER_ROW per unique row
# ══════════════════════════════════════════════════════════════════════════════


def correct_imbalance(rows: list[dict]) -> list[dict]:
    train = [r for r in rows if r["split"] == "train"]
    other = [r for r in rows if r["split"] != "train"]

    # ── compute class weights for all rows ────────────────────────────────────
    counts = Counter(r["issue_type"] for r in train)
    total  = sum(counts.values())
    n_cls  = len(counts)
    weights: dict[str, float] = {
        it: total / (n_cls * cnt) for it, cnt in counts.items()
    }

    for r in rows:
        r["class_weight"] = round(weights.get(r["issue_type"], 1.0), 4)

    # ── limited oversampling (training only) ───────────────────────────────────
    median_count = sorted(counts.values())[len(counts) // 2]
    target_floor = max(500, median_count)

    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in train:
        by_type[r["issue_type"]].append(r)

    print(f"\n[Phase F] Imbalance correction (train only, floor={target_floor}):")
    oversampled: list[dict] = []

    for issue_type in sorted(by_type):
        type_rows = by_type[issue_type]
        cnt = len(type_rows)

        if cnt >= target_floor:
            oversampled.extend(type_rows)
            print(f"  {issue_type:<28} {cnt:>6}  (no oversampling needed)")
            continue

        needed         = target_floor - cnt
        max_additional = cnt * MAX_COPIES_PER_ROW
        actual_add     = min(needed, max_additional)

        pool = type_rows * (MAX_COPIES_PER_ROW + 1)
        random.shuffle(pool)
        extra = [dict(r) | {"oversampled": True} for r in pool[:actual_add]]

        oversampled.extend(type_rows)
        oversampled.extend(extra)
        print(f"  {issue_type:<28} {cnt:>6} -> {cnt + actual_add:>6} (+{actual_add}, cap={MAX_COPIES_PER_ROW}x)")

    counts_after = Counter(r["issue_type"] for r in oversampled)
    ratio_before = max(counts.values()) / max(min(counts.values()), 1)
    ratio_after  = max(counts_after.values()) / max(min(counts_after.values()), 1)
    print(f"  Imbalance ratio: {ratio_before:.1f}× -> {ratio_after:.1f}×")

    return oversampled + other


# ══════════════════════════════════════════════════════════════════════════════
# Phase H — ContractNLI validator dataset
# ══════════════════════════════════════════════════════════════════════════════

NLI_VERDICT_MAP = {"entailment": "retain", "contradiction": "reject", "neutral": "uncertain"}


def load_contractnli() -> list[dict]:
    df = pd.read_parquet(CNLI_FILE)

    # detect label column
    label_col = None
    for col in ("label", "label_name"):
        if col in df.columns:
            # prefer string col
            if df[col].dtype == object or label_col is None:
                label_col = col
    if label_col is None:
        raise ValueError("ContractNLI: no label column found")

    rows = []
    for i, row in df.iterrows():
        label   = str(row[label_col]).lower().strip()
        verdict = NLI_VERDICT_MAP.get(label, "uncertain")
        split   = str(row.get("split", "train")).lower()
        if split in ("validation", "dev"):
            split = "val"

        rows.append({
            "id":        f"cnli_{i:05d}",
            "source":    "contractnli",
            "premise":   str(row.get("premise", "")),
            "hypothesis":str(row.get("hypothesis", "")),
            "nli_label": label,
            "verdict":   verdict,
            "split":     split,
        })

    return rows


def oversample_contradiction(rows: list[dict], target_pct: float = 0.35) -> list[dict]:
    """Bring contradiction share in training set to target_pct via capped oversampling."""
    train = [r for r in rows if r["split"] == "train"]
    other = [r for r in rows if r["split"] != "train"]

    contra = [r for r in train if r["verdict"] == "reject"]
    rest   = [r for r in train if r["verdict"] != "reject"]
    cur_pct = len(contra) / max(len(train), 1)

    print(f"\n[Phase H] ContractNLI contradiction: {len(contra)}/{len(train)} = {cur_pct:.1%}")

    if cur_pct < target_pct and contra:
        target_n = int(len(rest) * target_pct / (1 - target_pct))
        needed   = target_n - len(contra)
        max_add  = len(contra) * MAX_COPIES_PER_ROW
        actual   = min(needed, max_add)

        pool  = contra * (MAX_COPIES_PER_ROW + 1)
        extra = [dict(r) | {"oversampled": True} for r in pool[:actual]]

        new_train = rest + contra + extra
        random.shuffle(new_train)
        new_pct = sum(1 for r in new_train if r["verdict"] == "reject") / len(new_train)
        print(f"  Oversampled contradiction: {len(contra)} -> {len(contra) + actual} rows")
        print(f"  New contradiction %: {new_pct:.1%}")
        return new_train + other

    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Phase I — MAUD M&A reviewer dataset
# ══════════════════════════════════════════════════════════════════════════════

# MAUD category -> imbalance floor (rows per category in train after oversampling)
MAUD_CATEGORY_FLOOR = 400

# Map MAUD categories to a rough issue-type label for RL pool tagging
MAUD_CATEGORY_ISSUE_MAP = {
    "Material Adverse Effect":                "termination_risk",
    "Deal Protection and Related Provisions":  "governance_risk",
    "Conditions to Closing":                  "representation_risk",
    "Operating and Efforts Covenant":         "compliance_obligation",
    "Knowledge":                              "representation_risk",
    "General Information":                    "boilerplate",
    "Remedies":                               "dispute_resolution",
}


def generate_maud_rows(df: pd.DataFrame) -> list[dict]:
    """Convert MAUD passages into deal-point QA records for Dataset C."""
    rows = []
    for i, row in df.iterrows():
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        rows.append({
            "id":          f"maud_{i:06d}",
            "source":      "maud",
            "contract_id": str(row.get("contract_name", "")),
            "passage":     text,
            "question":    str(row.get("question", "")),
            "answer":      str(row.get("answer", "")),
            "category":    str(row.get("category", "")),
            "text_type":   str(row.get("text_type", "")),
            "issue_type":  MAUD_CATEGORY_ISSUE_MAP.get(str(row.get("category", "")), "boilerplate"),
            "split":       str(row.get("split", "train")),
        })
    return rows


def oversample_maud_categories(rows: list[dict]) -> list[dict]:
    """Bring rare MAUD categories in the train split up to MAUD_CATEGORY_FLOOR."""
    train = [r for r in rows if r["split"] == "train"]
    other = [r for r in rows if r["split"] != "train"]

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in train:
        by_cat[r["category"]].append(r)

    print(f"\n[Phase I] MAUD category oversampling (floor={MAUD_CATEGORY_FLOOR}):")
    oversampled: list[dict] = []
    for cat in sorted(by_cat):
        cat_rows = by_cat[cat]
        cnt = len(cat_rows)
        if cnt >= MAUD_CATEGORY_FLOOR:
            oversampled.extend(cat_rows)
            print(f"  {cat[:45]:<45} {cnt:>5}  (no oversampling)")
            continue
        needed   = MAUD_CATEGORY_FLOOR - cnt
        max_add  = cnt * MAX_COPIES_PER_ROW
        actual   = min(needed, max_add)
        pool = cat_rows * (MAX_COPIES_PER_ROW + 1)
        random.shuffle(pool)
        extra = [dict(r) | {"oversampled": True} for r in pool[:actual]]
        oversampled.extend(cat_rows)
        oversampled.extend(extra)
        print(f"  {cat[:45]:<45} {cnt:>5} -> {cnt + actual:>5} (+{actual})")

    return oversampled + other


# ══════════════════════════════════════════════════════════════════════════════
# Phase J — RL pool (train rows from A + B + C, no split)
# ══════════════════════════════════════════════════════════════════════════════


def build_rl_pool(
    reviewer_rows: list[dict],
    cnli_rows: list[dict],
    maud_rows: list[dict],
) -> list[dict]:
    """Combine train-split rows from all three datasets into a single RL pool."""
    pool: list[dict] = []
    for r in reviewer_rows:
        if r["split"] == "train":
            pool.append(dict(r) | {"split": "rl_pool", "rl_source": "reviewer_sft"})
    for r in cnli_rows:
        if r["split"] == "train":
            pool.append(dict(r) | {"split": "rl_pool", "rl_source": "validator_sft"})
    for r in maud_rows:
        if r["split"] == "train":
            pool.append(dict(r) | {"split": "rl_pool", "rl_source": "maud_sft"})
    random.shuffle(pool)
    print(f"\n[Phase J] RL pool: {len(pool):,} rows (reviewer={sum(1 for r in pool if r['rl_source']=='reviewer_sft'):,}"
          f"  validator={sum(1 for r in pool if r['rl_source']=='validator_sft'):,}"
          f"  maud={sum(1 for r in pool if r['rl_source']=='maud_sft'):,})")
    return pool


# ══════════════════════════════════════════════════════════════════════════════
# Stats + output
# ══════════════════════════════════════════════════════════════════════════════


def write_jsonl(rows: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def print_final_stats(reviewer_rows: list[dict], cnli_rows: list[dict], maud_rows: list[dict]) -> None:
    print("\n" + "=" * 60)
    print("FINAL STATS")
    print("=" * 60)

    # Reviewer dataset
    print("\nDataset A — Reviewer SFT (per split, per source):")
    for split in ["train", "val", "test"]:
        sub = [r for r in reviewer_rows if r["split"] == split]
        by_src = Counter(r["source"] for r in sub)
        print(f"  {split:6}: {len(sub):>7,}  ({dict(by_src)})")

    print("\nDataset A — Issue type distribution (train):")
    train_rows = [r for r in reviewer_rows if r["split"] == "train"]
    counts = Counter(r["issue_type"] for r in train_rows)
    for it, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {it:<28} {cnt:>7,}")

    # Validator dataset
    print("\nDataset B — Validator SFT (per split):")
    for split in ["train", "val", "test"]:
        sub = [r for r in cnli_rows if r["split"] == split]
        by_v = Counter(r["verdict"] for r in sub)
        print(f"  {split:6}: {len(sub):>7,}  ({dict(by_v)})")

    # MAUD dataset
    print("\nDataset C — M&A Reviewer SFT (per split, per category):")
    for split in ["train", "val", "test"]:
        sub = [r for r in maud_rows if r["split"] == split]
        by_cat = Counter(r["category"] for r in sub)
        print(f"  {split:6}: {len(sub):>7,}")
        for cat, cnt in sorted(by_cat.items(), key=lambda x: -x[1]):
            print(f"    {cat[:45]:<45} {cnt:>6,}")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    print("=" * 60)
    print("Data Curation Pipeline")
    print("=" * 60)

    # ── Phase A ───────────────────────────────────────────────────────────────
    print("\n[Phase A] Loading + cleaning...")
    cuad_raw   = load_cuad()
    ledgar_raw = load_ledgar()
    maud_raw   = load_maud()

    # ── Phase B+C ─────────────────────────────────────────────────────────────
    print("\n[Phase B+C] Taxonomy projection + boilerplate archive...")
    cuad_usable,   cuad_bp   = project_cuad(cuad_raw)
    ledgar_usable, ledgar_bp = project_ledgar(ledgar_raw)
    save_boilerplate_archive(cuad_bp, ledgar_bp)

    # ── Phase G ───────────────────────────────────────────────────────────────
    print("\n[Phase G] Document-level splits...")
    cuad_train, cuad_val, cuad_test, cuad_golden         = split_cuad(cuad_usable)
    ledgar_train, ledgar_val, ledgar_test, ledgar_golden = split_ledgar(ledgar_usable)
    # MAUD: use official document-level splits as-is
    maud_train = maud_raw[maud_raw["split"] == "train"].copy()
    maud_val   = maud_raw[maud_raw["split"] == "val"].copy()
    maud_test  = maud_raw[maud_raw["split"] == "test"].copy()
    print(f"  MAUD splits (official): train={len(maud_train):,} val={len(maud_val):,} test={len(maud_test):,}")
    save_split_manifest(
        cuad_train, cuad_val, cuad_test, cuad_golden,
        ledgar_train, ledgar_val, ledgar_test, ledgar_golden,
        maud_df=maud_raw,
    )

    # ── Phase D+E ─────────────────────────────────────────────────────────────
    print("\n[Phase D+E] Weak supervision + role augmentation...")
    sft_parts = pd.concat([cuad_train, cuad_val, cuad_test], ignore_index=True)
    led_parts = pd.concat([ledgar_train, ledgar_val, ledgar_test], ignore_index=True)

    # Golden contracts are reserved — not in SFT output
    cuad_rows   = generate_reviewer_rows(sft_parts, "cuad")
    ledgar_rows = generate_reviewer_rows(led_parts, "ledgar")
    reviewer_rows = cuad_rows + ledgar_rows
    print(f"  Generated {len(reviewer_rows):,} rows total (before imbalance correction)")

    # ── Phase F ───────────────────────────────────────────────────────────────
    reviewer_rows = correct_imbalance(reviewer_rows)

    # ── Write Dataset A ───────────────────────────────────────────────────────
    print("\nWriting Dataset A (reviewer SFT)...")
    for split in ["train", "val", "test"]:
        split_rows = [r for r in reviewer_rows if r["split"] == split]
        out = OUT_DIR / "dataset_a" / f"reviewer_{split}.jsonl"
        write_jsonl(split_rows, out)
        print(f"  {out.name}: {len(split_rows):,} rows")

    # ── Phase H ───────────────────────────────────────────────────────────────
    print("\n[Phase H] ContractNLI validator dataset...")
    cnli_rows = load_contractnli()
    cnli_rows = oversample_contradiction(cnli_rows)

    # ── Write Dataset B ───────────────────────────────────────────────────────
    print("\nWriting Dataset B (validator SFT)...")
    for split in ["train", "val", "test"]:
        split_rows = [r for r in cnli_rows if r["split"] == split]
        out = OUT_DIR / "dataset_b" / f"validator_{split}.jsonl"
        write_jsonl(split_rows, out)
        print(f"  {out.name}: {len(split_rows):,} rows")

    # ── Phase I ───────────────────────────────────────────────────────────────
    print("\n[Phase I] MAUD M&A reviewer dataset...")
    maud_sft = pd.concat([maud_train, maud_val, maud_test], ignore_index=True)
    maud_rows = generate_maud_rows(maud_sft)
    maud_rows = oversample_maud_categories(maud_rows)

    print("\nWriting Dataset C (M&A reviewer SFT)...")
    for split in ["train", "val", "test"]:
        split_rows = [r for r in maud_rows if r["split"] == split]
        out = OUT_DIR / "dataset_c" / f"maud_{split}.jsonl"
        write_jsonl(split_rows, out)
        print(f"  {out.name}: {len(split_rows):,} rows")

    # ── Phase J — RL pool ─────────────────────────────────────────────────────
    rl_pool = build_rl_pool(reviewer_rows, cnli_rows, maud_rows)
    out = OUT_DIR / "rl_pool.jsonl"
    write_jsonl(rl_pool, out)
    print(f"  rl_pool.jsonl: {len(rl_pool):,} rows -> {out}")

    # ── Stats ─────────────────────────────────────────────────────────────────
    print_final_stats(reviewer_rows, cnli_rows, maud_rows)

    # ── Golden candidate counts ───────────────────────────────────────────────
    print("\nGolden candidates reserved (not in SFT — use curate_golden.py):")
    print(f"  CUAD contracts: {cuad_golden['contract_title'].nunique()} contracts, {len(cuad_golden):,} clauses")
    print(f"  LEDGAR rows:    {len(ledgar_golden):,}")
    print("\nDone. Run `python scripts/curate_golden.py` next.")


if __name__ == "__main__":
    main()
