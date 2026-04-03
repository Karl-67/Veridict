# Bug Log

Automatically maintained by AI Orchestrator and the project-memory skill.
Tracks bugs with root causes, solutions, and prevention notes.

### 2026-04-03 - App.tsx state machine does not include backend run states (created, st
- **Issue**: App.tsx state machine does not include backend run states (created, stage_running, awaiting_human_review, finalized, blocked, failed)
- **Root Cause**: Frontend was built as a fake static demo with hardcoded pipeline animation, not wired to real backend state machine
- **Solution**: Replace AppState union with backend run states; create run via POST /api/runs, store run_id, subscribe to SSE events, drive all UI transitions from event stream
- **Prevention**: Frontend state types should be generated from or validated against the canonical run-state contract in schemas.py

### 2026-04-03 - Polling at 300ms intervals in 'waiting' state is wasteful and races wi
- **Issue**: Polling at 300ms intervals in 'waiting' state is wasteful and races with API completion
- **Root Cause**: Dual async paths (fake pipeline animation + real API call) need synchronization; polling used as a crutch instead of event-driven updates
- **Solution**: Remove polling entirely; SSE event stream provides real-time stage_started/stage_completed/run_finalized events
- **Prevention**: Never use polling intervals as synchronization mechanism when an event stream is available

### 2026-04-03 - No error state rendering — upload failures are console.error'd but UI
- **Issue**: No error state rendering — upload failures are console.error'd but UI stays in pipeline/waiting
- **Root Cause**: catch block only logs error, never transitions state to a 'failed' or 'blocked' UI
- **Solution**: Add 'failed' to AppState union; transition to it in catch blocks; render error UI with retry option
- **Prevention**: Every async operation must have explicit error state handling in the UI state machine

### 2026-04-03 - PipelineTracker.tsx advances stages via setTimeout timers instead of r
- **Issue**: PipelineTracker.tsx advances stages via setTimeout timers instead of real backend stage statuses
- **Root Cause**: Component was built as a fake static demo animation, not wired to SSE event stream or run state
- **Solution**: Replace timer-based progression with SSE subscription; drive stage states from stage_started/stage_completed/stage_failed/stage_retrying events
- **Prevention**: Pipeline UI components must accept run_id and derive all visual state from the SSE event stream — no hardcoded timers or stage lists

### 2026-04-03 - PipelineTracker.tsx stage definitions don't match the canonical 10-sta
- **Issue**: PipelineTracker.tsx stage definitions don't match the canonical 10-stage backend graph
- **Root Cause**: Frontend stages were invented ad-hoc (Harvey, Kira, Reviewer 1-3, Validators, Verdict) without reference to the locked stage graph in orchestrator.md
- **Solution**: Replace STAGES constant with the canonical stage list from the backend stage graph; include parse, admin_merge, agreement_check, awaiting_human, finalize
- **Prevention**: Frontend stage definitions should be generated from or validated against the canonical stage graph — consider a shared types file

### 2026-04-03 - PipelineTracker.tsx has no visual states for retrying, blocked, or fai
- **Issue**: PipelineTracker.tsx has no visual states for retrying, blocked, or failed stages
- **Root Cause**: Only three states implemented (done/running/pending); stage_retrying, stage_failed, and run_blocked SSE events have no corresponding UI representation
- **Solution**: Add retrying (amber/orange indicator with retry count), blocked (red terminal state), and failed (error icon with message) visual states
- **Prevention**: UI state coverage must match all canonical SSE event types — audit against the event type enumeration in schemas.py
