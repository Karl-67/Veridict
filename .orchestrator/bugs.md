# Bug Log

Automatically maintained by AI Orchestrator and the project-memory skill.
Tracks bugs with root causes, solutions, and prevention notes.

---

## 2026-04-09 — Ollama Migration + End-to-End Pipeline Verification

### BUG-011 — AsyncOpenAI.aclose() does not exist
- **File**: `app/backend/providers/openrouter_provider.py`
- **Root Cause**: `await self._client.aclose()` — the `openai` SDK's `AsyncOpenAI` exposes `.close()`, not `.aclose()`.
- **Fix**: Changed to `await self._client.close()`.

### BUG-012 — _stage_output() no ORDER BY — wrong round returned for multi-round stages
- **File**: `app/backend/orchestration/state_machine.py`
- **Root Cause**: `_stage_output()` used `.first()` with no ordering. `harvey_review_block` and `kira_review_block` can have multiple rounds (rerun_required=True produces a new row). `.first()` returned round 1 (no `validated_output`) instead of the final round.
- **Fix**: Changed to order by `round_number DESC`, prefer rows containing `validated_output` key. Falls back to latest row with any output.
- **Prevention**: Any stage that can produce multiple execution rows must always be queried with explicit ordering on `round_number`.

### BUG-013 — Small-model enum violations crash Pydantic validation
- **Files**: `app/backend/agents/reviewer.py`, `app/backend/agents/validator.py`
- **Root Cause**: llama3.2 (3B) returns values outside the strict `Literal` enums — e.g. `issue_type='indemnification'`, `correctness_score=3` (0-10 scale instead of 0-1), `accepted_finding_keys=0` (int instead of list).
- **Fix**: Added `_normalize_finding_item()` and `_normalize_vote_raw()` coercion helpers in `reviewer.py`. Coercion applied before every `Finding(...)` or `ReviewerVote(...)` construction. Validator's `_deduplicate_overlapping_findings` also coerces `normalised_severity`/`normalised_issue_type` via imported helpers.
- **Prevention**: Any model output that feeds a Pydantic model with strict Literals needs a coercion layer — never construct directly from raw LLM dict.

### BUG-014 — Small-model produces malformed/truncated JSON
- **File**: `app/backend/providers/openrouter_provider.py`
- **Root Cause**: llama3.2 (3B) frequently produces JSON with syntax errors or truncates mid-object, especially for long multi-finding outputs. `json.loads()` raises `JSONDecodeError`.
- **Fix**: `_parse_json_response` now tries `json_repair.repair_json()` as fallback before raising `InvalidSchemaOutputError`. `max_output_tokens` for Ollama raised from 4096 → 8192.
- **Prevention**: Always install `json-repair` and use it as fallback for any small local model.

### BUG-015 — daily quota 429 triggers 3× retry loop burning requests
- **File**: `app/backend/providers/openrouter_provider.py`
- **Root Cause**: `free-models-per-day` 429 had `retry_after_seconds` of ~13h. Code treated it as retryable, looping 3 times pointlessly.
- **Fix**: Any 429 with `retry_after_seconds > 600` is now classified as `NonRetryableProviderError` — fails immediately without retrying.

---

## 2026-04-08 — Full Diagnostic Session (10 bugs found and fixed)

### BUG-001 — MissingGreenlet crash on every POST /api/runs (CRITICAL)
- **Files**: `event_stream.py`, `run_service.py`
- **Root Cause**: `append_run_event` was sync, called `session.flush()` on `sync_session` from an asyncpg `AsyncSession` inside an async FastAPI handler.
- **Fix**: Added `async_append_run_event(AsyncSession)` with `await session.scalar/flush`. All 4 call sites in `run_service.py` updated. Sync version kept for worker.

### BUG-002 — FastAPI/Starlette version mismatch
- **Root Cause**: FastAPI 0.104.1 + Starlette 0.52.1 → `ValueError: too many values to unpack` on every request.
- **Fix**: Upgraded FastAPI to 0.135.3.

### BUG-003 — Gemini 400: additionalProperties in structured output schemas
- **File**: `agents/reviewer.py`
- **Root Cause**: All three schemas had `"additionalProperties": False` — rejected by Gemini's response_schema API.
- **Fix**: Removed from `_FINDING_ITEM_SCHEMA`, `REVIEWER_OUTPUT_SCHEMA`, `REVIEWER_VOTE_SCHEMA`.

### BUG-004 — Gemini 400: minimum/maximum in vote schema
- **File**: `agents/reviewer.py`
- **Root Cause**: `"minimum"`/`"maximum"` constraints in `REVIEWER_VOTE_SCHEMA` — also rejected by Gemini.
- **Fix**: Removed from `supported_reviewer_indexes` items and `correctness_score`.

### BUG-005 — ModuleNotFoundError: pytesseract (unconditional import)
- **File**: `services/parser.py`
- **Root Cause**: `import pytesseract` at top of function body, not inside the OCR fallback branch.
- **Fix**: Moved inside `if settings.enable_ocr_fallback:` block.

### BUG-006 — alembic ModuleNotFoundError: app (wrong sys.path)
- **File**: `alembic/env.py`
- **Root Cause**: `_backend_dir` (app/backend/) on sys.path; imports need project root.
- **Fix**: Changed to `_project_root` (3 levels up from env.py).

### BUG-007 — alembic TypeError: comment= on create_index
- **Fix**: Removed `comment=` args from `ix_stage_executions_claim` and `ix_run_events_replay_order`.

### BUG-008 — Gemini 404: gemini-1.5-flash no longer exists
- **Fix**: Changed `GEMINI_MODEL_NAME` in `.env` to `gemini-2.0-flash-lite`.

### BUG-009 — Frontend TypeScript error: unused Upload import
- **File**: `frontend/src/components/UploadForm.tsx`
- **Fix**: Removed `Upload` from lucide-react import line.

### BUG-010 — @fontsource/playfair-display missing from node_modules
- **Fix**: `npm install @fontsource/playfair-display`.
