# Project Context (Claude Code)

Managed by the AI Orchestrator. Claude Code reads this file on startup.

## Project Architecture
See `orchestrator.md` in this directory for a full project summary, folder structure, architecture overview, and notes on what each component does.

## Memory

All persistent memory lives in `.orchestrator/`:
- `bugs.md` · `decisions.md` · `key_facts.md` · `issues.md` · `memory.yaml`

Check these before making architectural changes or debugging known issues.
Run `/init` to have Qwen populate them from the codebase if they are empty.

**Current State**

The project is not yet at the architecture in the diagram. It has partial foundations, but the executable system is still the old prototype.

The strongest pieces already in place are the typed schema contract in [schemas.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/models/schemas.py), the provider boundary in [base.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/providers/base.py) and [google_provider.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/providers/google_provider.py), the DB/session layer in [session.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/db/session.py), and a first pass at reviewer/validator role classes in [reviewer.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/reviewer.py) and [validator.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/validator.py).

What is still required to finalize Phase 1 is the actual runtime architecture:

1. Real ingestion and parsing:
   [contracts.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/routes/contracts.py) still uses `pdfplumber` and truncates text. You need Docling-first parsing, OCR fallback, clause indexing, and evidence anchors.

2. Real orchestration:
   There is no `run_service`, no `state_machine`, no worker, no stage queue execution, no retries, and no blocked-state handling.

3. Real branch execution:
   Harvey and Kira reviewer classes exist conceptually, but there is no branch context loader for Kira, no admin layer, no agreement checker, and no final reviewer loop.

4. Real persistence and streaming:
   There is no event stream service, no SSE endpoint, no persisted replay logic, and no run-driven frontend.

5. Human review gate:
   The required gate is modeled in schema only. There is no backend implementation and no frontend panel.

6. Frontend replacement:
   [App.tsx](C:/Users/PinkPanther/PycharmProjects/Verdict/app/frontend/src/App.tsx), [PipelineTracker.tsx](C:/Users/PinkPanther/PycharmProjects/Verdict/app/frontend/src/components/PipelineTracker.tsx), [api.ts](C:/Users/PinkPanther/PycharmProjects/Verdict/app/frontend/src/lib/api.ts), and [types/index.ts](C:/Users/PinkPanther/PycharmProjects/Verdict/app/frontend/src/types/index.ts) are still demo-mode.

**Important Gaps / Breakages**

A few files are not just incomplete, they currently conflict with each other:

- [contracts.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/routes/contracts.py) imports `review_contract`, but [reviewer.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/reviewer.py) no longer defines it.
- [reviewer.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/reviewer.py) calls the provider synchronously and expects `(raw, response_id)`, but [base.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/providers/base.py) defines an async method returning one dict, and [google_provider.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/providers/google_provider.py) returns one parsed object.
- [validator.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/validator.py) has the same sync/async mismatch.
- [models.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/db/models.py) and [0001_initial_architecture.py](C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/alembic/versions/0001_initial_architecture.py) do not match. The migration and ORM are describing different schemas.
- [README.md](C:/Users/PinkPanther/PycharmProjects/Verdict/app/README.md) is outdated and still references Anthropic.

**What I Recommend Next**

If we continue with Google now and preserve the local-agent future, the next implementation order should be:

1. Freeze one authoritative run/state contract.
2. Fix provider-agent contract mismatches.
3. Replace `/api/upload` with `POST /api/runs` plus run detail and SSE.
4. Build parser service and clause index.
5. Add `compliance_repository.py`, `admin.py`, `run_service.py`, `event_stream.py`, `state_machine.py`, and `worker.py`.
6. Rebuild the frontend around `run_id` + SSE + human review.
7. Start logging raw provider I/O, validated findings, admin merges, and human edits as future fine-tuning data.

That path is compatible with your long-term plan. If done correctly, Gemini becomes just the first provider behind the same orchestration.

*(body trimmed to stay within the 400-word limit)*
