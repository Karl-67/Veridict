# Project Context (Codex)

Managed by the AI Orchestrator. Codex CLI reads this file on startup.

## Project Architecture
See `orchestrator.md` in this directory for a full project summary, folder structure, architecture overview, and notes on what each component does.

## Memory

All persistent memory lives in `.orchestrator/`:
- `bugs.md` · `decisions.md` · `key_facts.md` · `issues.md` · `memory.yaml`

Check these before making architectural changes or debugging known issues.
Run `/init` to have Qwen populate them from the codebase if they are empty.

**Current State**

The repo is not yet at the architecture in your diagram. It has useful scaffolding, but the live product path is still the old prototype:

- Backend runtime is still one synchronous upload route in [contracts.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/routes/contracts.py), including `pdfplumber` extraction and hard truncation at [contracts.py:38](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/routes/contracts.py:38).
- Frontend is still a simulated pipeline in [App.tsx](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/frontend/src/App.tsx) and [PipelineTracker.tsx](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/frontend/src/components/PipelineTracker.tsx:17), with polling at [App.tsx:62](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/frontend/src/App.tsx:62).
- The good news is the provider boundary, typed schemas, DB session layer, ORM models, and reviewer scaffolding already exist in [base.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/providers/base.py), [google_provider.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/providers/google_provider.py), [schemas.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/models/schemas.py), [models.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/db/models.py), and [reviewer.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/reviewer.py).

**What Is Still Required**

To finalize the architecture with Google now and local agents later, these are the remaining required pieces:

- Build the real run-based API: `POST /api/runs`, `GET /api/runs/{id}`, SSE events, and human review submission. The current `/api/upload` path has to be replaced.
- Add the actual orchestrator runtime: parser service, compliance repository, run service, event stream, state machine, worker, and admin agents.
- Replace fake frontend flow with backend-driven state, run IDs, SSE subscription, real stage rendering, and a human review panel.
- Unify the persistence contract. Right now [schemas.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/models/schemas.py), [models.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/db/models.py), and [0001_initial_architecture.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/alembic/versions/0001_initial_architecture.py) do not describe the same database shape.
- Replace `pdfplumber`-first parsing with Docling + OCR fallback.
- Update docs and config wiring. [app/README.md](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/README.md:20) still references Anthropic, and [main.py](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/main.py) still uses hardcoded CORS.

**Critical Code Blockers**

These should be fixed before deeper architecture work:

- [contracts.py:5](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/routes/contracts.py:5) imports `review_contract`, but that function no longer exists.
- [validator.py:18](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/validator.py:18) and [validator.py:24](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/validator.py:24) use inconsistent import paths.
- Provider interface is async in [base.py:144](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/providers/base.py:144), but reviewer methods are sync in [reviewer.py:345](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/reviewer.py:345), [reviewer.py:405](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/reviewer.py:405), and [reviewer.py:464](/C:/Users/PinkPanther/PycharmProjects/Verdict/app/backend/agents/reviewer.py:464). That contract needs one direction.

I updated [AGENTS.md](/C:/Users/PinkPanther/PycharmProjects/Verdict/AGENTS.md) to reflect the real repo state.

**Clarifications I Need Before Implementing Phase 1**

1. For Harvey, should conflict checking be only against prior versions of the same policy family, or against all tenant policies?
2. For Kira, do you want only internal policy/playbook checks for phase 1, or internal + external compliance corpora now?
3. After Admin, should the final 3 reviewers review only merged findings, or also be allowed to introduce brand-new findings?
4. When the final local system replaces Google, do you want one local model behind role prompts, or separate fine-tuned models per role?

I did not run the full app or DB migrations. I only inspected code and did a syntax-level parse pass.
