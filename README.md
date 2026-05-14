# Veridict — AI Contract Review Platform

![CI](https://github.com/Karl-67/Veridict/actions/workflows/ci.yml/badge.svg)

**Team:** Karim Assi, Abdel Rahman El Kouche, Karl Gerges  
**Course:** EECE503N — AI Engineering, American University of Beirut  
**Live deployment:** `http://136.110.220.144/`

---

## Overview

Veridict is a deployed AI-powered contract review platform for legal and business teams. Users upload a contract, and the system runs a structured multi-stage pipeline — parsing, evidence retrieval, AI risk analysis, and admin merge — before presenting findings to a human reviewer who can comment, redline, and export the final output.

The key engineering idea is **role separation**. Contract review is not treated as a single large prompt over a PDF. Instead, it is broken into durable, independently debuggable stages:

```
create_run → ingest_pdf → parse_ocr_normalize → clause_index →
harvey_context_load → kira_review_block → admin_merge →
awaiting_human_review → finalized
```

This makes the system easier to evaluate, easier to retry on failure, and more defensible than a generic chatbot workflow.

---

## The Problem

Manual contract review is slow, expensive, and hard to standardize. Reviewers must compare dense legal text against firm policies, identify risk, explain business impact, and produce usable revisions. Generic LLM upload workflows can summarize contracts but typically lack structured stages, evidence anchors, workspace scoping, and auditability.

**Target users:**
- **Legal reviewers** — need clause-level findings, policy evidence, comments, and redlines
- **Business users** — need understandable risk summaries and recommended changes
- **Workspace admins** — manage users, workspaces, invites, permissions, and policy documents

---

## Architecture

Veridict is composed of three services — API, worker, and frontend — backed by PostgreSQL with pgvector and RunPod-hosted LLM inference.

```
React / Vite frontend
        │
  FastAPI backend ──── PostgreSQL + pgvector
        │
  Async worker
    ├── PDF Parser (Docling → OCR → pdfplumber fallback)
    ├── Harvey  ──── RAG retrieval (pgvector)
    ├── Kira    ──── RunPod llama.cpp / Gemma endpoint
    └── Admin   ──── Merge + normalize findings
```

### AI Pipeline Roles

| Role | Responsibility |
|---|---|
| **Harvey 1 — Contradiction Finder** | Flags clauses that directly conflict with the organization's policy documents or prior versions. Every finding requires a RAG citation. |
| **Harvey 2 — Regression Challenger** | Identifies clauses where the new contract is materially worse than prior agreements, templates, or established standards in the knowledge base. |
| **Harvey 3 — Downstream Risk** | Detects enforcement gaps, liability exposure, exploitable loopholes, missing remedies, or language that could be used as a policy waiver in litigation. |
| **Kira** | Fine-tuned LLM reviewer. Analyzes contract text and produces structured risk findings with severity, explanation, worst-case impact, and evidence spans. Does not query RAG directly — receives Harvey-provided context. |
| **Admin** | Receives Harvey and Kira outputs, deduplicates and normalizes findings, and produces the final reviewable result. |

Harvey's three roles run **sequentially** — each stage receives the previous stage's output as input, so the regression challenger filters the contradiction finder's results, and the downstream risk stage enriches what survives. Their combined output is then passed to Admin alongside Kira's findings.

---

## Kira — Fine-Tuned Model

Kira is a PEFT LoRA adapter fine-tuned on top of `unsloth/gemma-4-26B-A4B-it` (a 26B MoE model). It was trained specifically for structured legal contract risk analysis.

**Training data:** CUAD and MAUD legal datasets were enriched using **knowledge distillation** — DeepSeek v4 Pro acted as the teacher labeler, adding risk type, severity, explanation, worst-case impact, and evidence spans to each training example. The labeled data was then exported into Gemma chat-format JSONL and used for QLoRA supervised fine-tuning.

**Training summary:**

| Metric | Value |
|---|---|
| Training examples | 22,858 |
| Validation examples | 5,327 |
| Training steps | 477 |
| Trainable parameters | 505M / 26.3B total (1.92%) |
| Final train loss | 0.9633 |
| Final eval loss | 0.6779 |
| GPU | NVIDIA A100-SXM4-80GB |

The adapter is hosted on Hugging Face: [`nothingsometimes/kira-gemma4-adapter`](https://huggingface.co/nothingsometimes/kira-gemma4-adapter)

**Validation:** A lawyer reviewed Kira's findings and approved **77.5%** as correct. An LLM-as-judge evaluation using ChatGPT 5.5 and Claude Opus 4.7 as independent judges reached an **85% success rate** across the same reviewed contracts.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite, Tailwind CSS, React Query, Framer Motion |
| Backend | FastAPI, Python, Alembic migrations |
| Database | PostgreSQL with pgvector |
| Worker | Async Python worker with durable stage state |
| PDF Parsing | Docling (primary), OCR (fallback), pdfplumber (final fallback) |
| LLM Inference | RunPod-hosted llama.cpp, OpenAI-compatible REST endpoints |
| Model | Gemma 4 26B-A4B + QLoRA Kira adapter |
| Containerization | Docker (API, worker, frontend), Docker Compose |
| Orchestration | Kubernetes (GKE) |
| Cloud | GCP / Google Kubernetes Engine, Google Artifact Registry |
| GPU Inference | RunPod (A100 SXM4 80GB) |
| Monitoring | Prometheus, Grafana |
| CI/CD | GitHub Actions (test → build → eval gate → deploy → smoke test → rollback) |

---

## Deployment

Veridict is live at **`http://136.110.220.144/`**. The application runs on Google Kubernetes Engine (GKE) with RunPod handling GPU inference. For setup and ops details, see [`DEPLOYMENT.md`](DEPLOYMENT.md) and [`docs/DEPLOY_GUIDE.md`](docs/DEPLOY_GUIDE.md).

---

## Key Features

- **Run-based pipeline** with durable, retryable stage state
- **Role-separated AI** — Harvey (RAG), Kira (fine-tuned review), Admin (merge)
- **PDF parsing fallback chain** — Docling → OCR → pdfplumber
- **RAG evidence retrieval** with pgvector, ingestion jobs, and retrieval traces
- **Human-in-the-loop review** with sign-off, comment, redline, and export
- **Workspace and organization access control** with invite-based onboarding
- **JWT authentication**, admin roles, rate limiting via `slowapi`
- **DOCX/PDF export** of reviewed contracts
- **Prometheus/Grafana monitoring** with API, worker, and model-serving scrape targets
- **Full CI/CD pipeline** — backend tests, frontend build, Docker build, eval gate, GKE deploy, smoke test, rollback

---

## Repository Structure

```
app/
  backend/         FastAPI app, agents, worker, routes, services, models
  frontend/        React / Vite frontend
configs/           Environment and model configurations
docs/              RAG design, deployment guides, runbook
infra/             GCP Terraform infrastructure
k8s/               Kubernetes manifests (GKE)
monitoring/        Prometheus and Grafana configuration
scripts/           Distillation pipeline, training scripts
tests/             Backend integration and unit tests
docker-compose.yml Local development stack
```

---

## CI / CD Workflow

Five GitHub Actions workflows cover the full delivery pipeline:

| Workflow | Purpose |
|---|---|
| `ci.yml` | Backend tests, frontend build, Docker build |
| `build-push.yml` | Build and push API, worker, frontend images to Google Artifact Registry |
| `eval.yml` | Eval gate — runs model quality checks; blocks promotion on failure |
| `promote.yml` | Deploy to GKE and run smoke test |
| `rollback.yml` | Roll back to the previous image on smoke test failure |

---

## Testing

The test suite lives in `tests/` and runs with `pytest` (async mode enabled). Key coverage areas:

| Test file | What it covers |
|---|---|
| `test_run_lifecycle.py` | End-to-end run state transitions |
| `test_stage_topology.py` | Stage ordering and dependency validation |
| `test_harvey_trio_consensus.py` | Harvey 3-stage sequential pipeline and consensus logic |
| `test_rag_ingestion.py` | RAG document ingestion and chunk storage |
| `test_rag_retrieval.py` | Vector and text retrieval against pgvector |
| `test_parser_confidence.py` | PDF parser fallback chain and confidence gating |
| `test_validator_evidence.py` | Finding citation and evidence anchor validation |
| `test_eval_metrics.py` | Eval gate metric thresholds |

Run tests locally:
```bash
cd app/backend
pytest
```

---

## Evaluation and Limitations

The current evaluation establishes training completion and initial human and LLM-judge validation. Broader legal-task benchmarking (issue-type F1, severity calibration, hallucination rate, citation accuracy) across more jurisdictions and document types remains the primary remaining work.

Known limitations:
- **Teacher-label bias** — DeepSeek labels may over-rank severity, making Kira more cautious than ideal
- **Jurisdiction coverage** — initial lawyer validation was grounded in Lebanese legal practice; foreign-law clauses require wider review
- **Metric breadth** — task-specific benchmarks across clause types, risk categories, and jurisdictions are not yet complete

---

## License

This project was developed as part of EECE503N at the American University of Beirut. All rights reserved by the authors.
