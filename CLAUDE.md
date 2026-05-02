# Project Context (Claude Code)

Managed by the AI Orchestrator. Claude Code reads this file on startup.

## Project Architecture
See `orchestrator.md` in this directory for a full project summary, folder structure, architecture overview, and notes on what each component does.

## Memory

All persistent memory lives in `.orchestrator/`:
- `bugs.md` · `decisions.md` · `key_facts.md` · `issues.md` · `memory.yaml`

Check these before making architectural changes or debugging known issues.
Run `/init` to have Qwen populate them from the codebase if they are empty.

**Current State (updated 2026-04-19)**

Phase 1 pipeline fully implemented and verified end-to-end (all 12 stages). Full auth system, multi-tenant org/workspace model, contract reader with PDF highlights, collaborative comments, and admin panel are all live.

**Startup:**
```bash
python3 -m uvicorn app.backend.main:app --host 0.0.0.0 --port 8000 --reload
python3 -m app.backend.worker
cd app/frontend && npm run dev
```
Requires Ollama running locally.

**LLM Provider:** Local Ollama (`LLM_PROVIDER=ollama`). Change only `OLLAMA_MODEL` in `.env` to swap models — no code changes needed.

**What is running:**
- Backend: FastAPI on port 8000
- Worker: `python3 -m app.backend.worker` (processes all 12 stages)
- Frontend: React/Vite on port 5173
- PostgreSQL on localhost:5432, database `veridict`
- Ollama: local inference at `http://localhost:11434/v1`

**All 12 stages verified:** create_run → ingest_pdf → parse_ocr_normalize → clause_index → harvey_context_load → kira_context_load → harvey_review_block → kira_review_block → admin_merge → final_review_block → awaiting_human_review → finalized

**What remains open:**
- Export Report — not yet implemented (button is no-op)
- Email sending for invites — manual link copy only
- Schedule Partner Review — postponed
- Parser extraction confidence not yet propagated (RISK-001)
- Automated corpus ETL from parquet files (RISK-002) — corpus seeded manually
- Small-model quality ceiling (RISK-008) — llama3.2:3b works but larger models recommended for production
