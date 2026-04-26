from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
CURATED_DIR = DATA_DIR / "curated"
DISTILL_DIR = DATA_DIR / "distillation"
SEC_FILE = DATA_DIR / "material" / "sec_contracts.parquet"

# Teacher models — gpt-5.4 for all datasets
TEACHER_CLAUSE = "gpt-5.4"
TEACHER_CONTRACT = "gpt-5.4"

MAX_OUTPUT_TOKENS = 280
BATCH_MAX_REQUESTS = 45_000   # OpenAI hard cap is 50k; stay under

# Contracts whose estimated input token count exceeds this threshold are written
# to separate  *_large_batch_*.jsonl  files and processed last.  This preserves
# the per-session rate-limit budget for smaller contracts (faster throughput per
# token spent) while still labeling large contracts when limits reset.
# ~3,500 input tokens ≈ 2,600 words ≈ a medium-to-large commercial contract.
LARGE_CONTRACT_TOKENS = 3_500

# SEC chunking — word-based (~1.35 tokens/word → 380 words ≈ 512 tokens)
SEC_CHUNK_WORDS = 380
SEC_CHUNK_OVERLAP_WORDS = 100

SCORE_LABELS = {
    0: "No risk — standard boilerplate",
    1: "Low — informational only",
    2: "Moderate — worth noting",
    3: "Significant — recommend review",
    4: "High — recommend redline",
    5: "Critical — recommend rejection",
}

ISSUE_TYPE_DISPLAY = {
    "liability_exposure":    "Liability Exposure",
    "restriction_clause":    "Restriction Clause",
    "ip_risk":               "IP Risk",
    "financial_obligation":  "Financial Obligation",
    "termination_risk":      "Termination Risk",
    "governance_risk":       "Governance Risk",
    "compliance_obligation": "Compliance Obligation",
    "dispute_resolution":    "Dispute Resolution",
    "confidentiality_risk":  "Confidentiality Risk",
    "warranty_and_insurance":"Warranty & Insurance",
    "jurisdictional_risk":   "Jurisdictional Risk",
    "representation_risk":   "Representation Risk",
    "third_party_risk":      "Third Party Risk",
}

# ── Gemma 4 26B — three-checkpoint training pipeline ─────────────────────────
# Use the 26B MoE instruction-tuned variant for production.
# Swap to "google/gemma-4-E4B" for fast dev iterations.
GEMMA_MODEL_ID = "google/gemma-4-26B-A4B-it"

# Sequence lengths — default for Harvey/Kira clause+context; long for MAUD passages
MAX_SEQ_LENGTH      = 1024
MAX_SEQ_LENGTH_MAUD = 1536

# LoRA / training hyperparameters
LORA_RANK        = 16
LORA_ALPHA       = 32
TRAIN_EPOCHS     = 3
TRAIN_BATCH_SIZE = 2
GRAD_ACCUM_STEPS = 8     # effective batch = 16
LEARNING_RATE    = 2e-4

# ── Branch-specific directories ───────────────────────────────────────────────
# Raw (pre-export) training sets — written by build_branch_datasets.py
HARVEY_DIR    = DISTILL_DIR / "harvey"
KIRA_DIR      = DISTILL_DIR / "kira"
VALIDATOR_DIR = DISTILL_DIR / "validator"
MAUD_DIR      = DISTILL_DIR / "maud"

# Exported fine-tuning sets — written by export_branch.py
HARVEY_FT_DIR    = DISTILL_DIR / "harvey_ft"
KIRA_FT_DIR      = DISTILL_DIR / "kira_ft"
VALIDATOR_FT_DIR = DISTILL_DIR / "validator_ft"

# Fine-tuned model output directories
HARVEY_OUTPUT_DIR    = DISTILL_DIR / "model_harvey"
KIRA_OUTPUT_DIR      = DISTILL_DIR / "model_kira"
VALIDATOR_OUTPUT_DIR = DISTILL_DIR / "model_validator"

# Checkpoint directories
HARVEY_CHECKPOINTS    = DISTILL_DIR / "checkpoints_harvey"
KIRA_CHECKPOINTS      = DISTILL_DIR / "checkpoints_kira"
VALIDATOR_CHECKPOINTS = DISTILL_DIR / "checkpoints_validator"

# Legacy single-model paths (kept for backward compatibility with export_gemma.py)
GEMMA_MODEL_ID_4B   = "google/gemma-4-E4B"
GEMMA_CHECKPOINTS   = DISTILL_DIR / "checkpoints"
GEMMA_OUTPUT_DIR    = DISTILL_DIR / "model"
GEMMA_DIR           = DISTILL_DIR / "gemma"

BATCHES_DIR   = DISTILL_DIR / "batches"
RESULTS_DIR   = DISTILL_DIR / "results"
ANNOTATED_DIR = DISTILL_DIR / "annotated"

# ── Kira DeepSeek-labeling pipeline ──────────────────────────────────────────
import os as _os

CONTEXT_SENTENCES_CUAD = 8
MAX_SEQ_LENGTH_KIRA    = 2048
DEEPSEEK_MODEL         = _os.getenv("DEEPSEEK_MODEL", "")   # set in .env when ready
DEEPSEEK_BASE_URL      = "https://api.deepseek.com/v1"
KIRA_RAW_DIR           = DATA_DIR / "kira" / "raw"
KIRA_LABELED_DIR       = DATA_DIR / "kira" / "labeled"
KIRA_FT_DIR            = DATA_DIR / "kira" / "ft"

for _d in [
    DISTILL_DIR,
    BATCHES_DIR, RESULTS_DIR, ANNOTATED_DIR,
    GEMMA_DIR, GEMMA_CHECKPOINTS, GEMMA_OUTPUT_DIR,
    HARVEY_DIR, KIRA_DIR, VALIDATOR_DIR, MAUD_DIR,
    HARVEY_FT_DIR, KIRA_FT_DIR, VALIDATOR_FT_DIR,
    HARVEY_OUTPUT_DIR, KIRA_OUTPUT_DIR, VALIDATOR_OUTPUT_DIR,
    HARVEY_CHECKPOINTS, KIRA_CHECKPOINTS, VALIDATOR_CHECKPOINTS,
    KIRA_RAW_DIR, KIRA_LABELED_DIR, KIRA_FT_DIR,
]:
    _d.mkdir(parents=True, exist_ok=True)
