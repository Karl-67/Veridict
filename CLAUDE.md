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

## Kira fine-tuning (updated 2026-04-29)

QLoRA SFT for the Kira reviewer agent runs on a runpod box (RTX A5000, 24 GB VRAM, 503 GB RAM). Full step-by-step in `KIRA_QLORA_RUNBOOK.md`.

**Target model:** `unsloth/gemma-4-26B-A4B-it` (26B-param MoE, 4B active, 128 experts, multimodal). No pre-quantized bnb-4bit variant exists for this repo — only GGUF and MLX. We download the 51 GB bf16 source and quantize on the fly with CPU offload.

**Stack on the box:** torch 2.10.0+cu128, transformers 5.5.0, accelerate 1.13.0, bitsandbytes 0.49.2, unsloth 2026.4.8. Venv lives at `/home/student1/kira_env`; model cache at `/workspace/hf_cache`.

**SSH from Windows git-bash:** no sshpass needed; use `SSH_ASKPASS_REQUIRE=force` with a helper script that echoes the password. See runbook §"SSH from Windows git-bash".

**Non-obvious gotchas (any of these, individually, breaks the run):**
- `bnb_4bit_use_double_quant=True` triggers a meta-tensor crash in `QuantState.as_dict` during accelerate dispatch — must be `False`.
- transformers 5.5/5.7 passes `_is_hf_initialized` to `Params4bit.__new__`, which bnb 0.49 rejects — monkey-patch `Params4bit.__new__` to drop the kwarg.
- `device_map={"": 0}` OOMs at ~33% of weight load (bf16 weights pile up before quantization). Use `max_memory={0: "20GiB", "cpu": "300GiB"}` to stream through CPU.
- `llm_int8_enable_fp32_cpu_offload=True` is required in `BitsAndBytesConfig` once any module spills to CPU.
- `/workspace` is MooseFS with a per-user quota ~60 GB (despite `df` showing 192 TB free). Keep venv on `/home`, not `/workspace`.

**Training data:** chat-format JSONL at `/workspace/verdict_training/data/ft/{train,val,test}.jsonl` (22858 / 5327 / 5273 examples), `messages: [{role, content}]`. Output adapter lands at `/workspace/verdict_training/kira_adapter`.
