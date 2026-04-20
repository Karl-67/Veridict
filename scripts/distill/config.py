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

# Gemma 4 fine-tuning
GEMMA_MODEL_ID      = "google/gemma-4-E4B"   # 4B MoE — swap to 26B-A4B-it for more capacity
GEMMA_CHECKPOINTS   = DISTILL_DIR / "checkpoints"
GEMMA_OUTPUT_DIR    = DISTILL_DIR / "model"
LORA_RANK           = 16
LORA_ALPHA          = 32
TRAIN_EPOCHS        = 3
TRAIN_BATCH_SIZE    = 2
GRAD_ACCUM_STEPS    = 8     # effective batch = 16
LEARNING_RATE       = 2e-4
MAX_SEQ_LENGTH      = 1024

BATCHES_DIR   = DISTILL_DIR / "batches"
RESULTS_DIR   = DISTILL_DIR / "results"
ANNOTATED_DIR = DISTILL_DIR / "annotated"
GEMMA_DIR     = DISTILL_DIR / "gemma"

for _d in [DISTILL_DIR, BATCHES_DIR, RESULTS_DIR, ANNOTATED_DIR, GEMMA_DIR,
           GEMMA_CHECKPOINTS, GEMMA_OUTPUT_DIR]:
    _d.mkdir(parents=True, exist_ok=True)
