# Verdict — Agent Architecture Design

> Design decisions, rationale, and known trade-offs for the multi-agent review pipeline.
> Updated 2026-04-27.

---

## 1. What the system does

Verdict accepts a PDF contract and runs it through a two-branch agentic pipeline that produces
two distinct outputs per clause:

- **`intra_comment`** — what is wrong *within* this contract (Kira's finding)
- **`cross_comment`** — how this clause conflicts with prior policy or the knowledge base (Harvey's finding)

These two outputs meet at the Admin agent, which synthesises them into a per-clause verdict.
A human reviewer then approves, edits, or rejects the final output before it is committed.

---

## 2. Pipeline overview

```
create_run → ingest_pdf → parse_ocr_normalize → clause_index → harvey_context_load
                                                                        │
                                              ┌─────────────────────────┘
                                              │
                               ┌──────────────┴──────────────┐
                               │  stage_order = 6 (parallel)  │
                               │                             │
                       harvey_review_block          kira_review_block
                       (sequential pipeline)        (worker-panel loop)
                               │                             │
                               └──────────────┬──────────────┘
                                              │
                                         admin_merge
                                         (LLM synthesis)
                                              │
                                   awaiting_human_review
                                              │
                                         finalized
```

Harvey and Kira run at the same `stage_order`. With one worker process they run sequentially
(neither blocks the other from being claimed). With two worker processes they run truly in
parallel. Admin merge waits for both to complete.

---

## 3. Harvey — sequential 3-stage pipeline

### Why sequential, not parallel independent passes

The original broken design ran all three Harvey roles independently and then voted. This
wasted the role differentiation: the `regression_challenger` role only makes sense if it
*sees what the contradiction_finder found*. Running it independently on the raw contract
produces a third independent pass, not a challenge.

### The three stages

**Stage 1 — `contradiction_finder`**
Runs on the raw contract clauses and RAG context. Exhaustive — flags every plausible
contradiction between the current contract and prior policy versions in the knowledge base.
Errs on the side of inclusion because stage 2 will filter.

**Stage 2 — `regression_challenger`**
Receives stage-1 findings as explicit input. Filters down to genuine, material regressions
only. Discards: legitimate documented policy updates, equivalent restatements in different
words, minor structural changes with no substantive effect. Returns a filtered finding list.

**Stage 3 — `downstream_risk`**
Receives stage-2 (validated) findings. Does not add or remove findings — enriches each one
with downstream consequence analysis: what enforcement gap or loophole does this
contradiction create? Can the counterparty weaponise the policy inconsistency? What is the
worst-case downstream liability? May increase severity but not decrease it.

### RAG access

Harvey has exclusive access to the pgvector RAG corpus (prior policy versions, playbook
rules, reference contracts). Every Harvey finding must cite at least one `rag_citation`
(chunk_id). Findings without citations are dropped at assembly time. Kira is explicitly
forbidden from accessing the RAG corpus.

### LLM calls per run

- Stage 1: 1 call
- Stage 2: 1 call (receives stage-1 output in context)
- Stage 3: 1 call (receives stage-2 output in context)
- Total Harvey: 3 calls

---

## 4. Kira — worker + panel loop

### Design

One `KiraWorker` does the analysis. Three `KiraPanelReviewers` vote approve/reject.

```
KiraWorker.analyze()
    │
    ▼
KiraPanelReviewer × 3  →  2+ approve  →  KiraValidatorAgent  →  admin_merge
                       →  2+ reject   →  aggregate feedback
                                              │
                                    KiraWorker.revise()
                                              │
                                    KiraPanelReviewer × 3  (repeat, max 3 iterations)
```

### Why worker + panel instead of 3 identical instances

The old design ran 3 identical instances and used 2-of-3 agreement as a consistency filter
(things appearing in 2 of 3 independent runs are likely real). This is a hallucination
filter, not a quality improvement mechanism.

The new design is an improvement loop: the worker produces output, the panel critiques it,
the worker revises. This produces better `recommended_change` text and better severity
calibration than consistency voting alone.

### Panel approval threshold

2-of-3 panel reviewers must approve to pass findings to admin. If 2+ reject, feedback from
all rejecting reviewers is aggregated into a single block and sent back to the worker for
revision. Maximum 3 iterations; after that, the last worker output passes regardless.

### Kira's scope

Contract-internal issues only: ambiguity, missing protections, exploitable gaps, imbalanced
terms. Every finding must include a `recommended_change` with actual rewrite text (not
generic advice). Kira is strictly forbidden from referencing the RAG corpus.

### LLM calls per run (worst case)

- Worker initial analysis: 1 call
- Panel review × 3: 3 calls
- Worker revision × 2 (if rejected twice): 2 calls
- Panel re-review × 2 × 3: 6 calls
- KiraValidatorAgent: 1 call
- Total Kira worst case: 13 calls

Typical case (1 revision cycle): 8 calls.

---

## 5. Admin — LLM synthesis

Admin receives Harvey's cross-contract findings and Kira's intra-contract findings and
produces one `ClauseVerdict` per affected clause:

```
ClauseVerdict {
    clause_uid:               str
    intra_comment:            str | None   ← synthesised from Kira findings
    cross_comment:            str | None   ← synthesised from Harvey findings
    severity:                 low | medium | high | critical
    contributing_finding_ids: list[str]
}
```

Either comment can be null if only one branch flagged that clause. Admin deduplicates
overlapping findings from both branches.

Admin is a single LLM call with no reviewer loop — the Harvey and Kira quality gates
upstream are sufficient.

---

## 6. Fine-tuning strategy

### Interface

`app/backend/agents/base.py` defines two base classes:

- **`FineTunableAgent`** — agent that should be fine-tuned on domain data.
  Declares `fine_tune_dataset`, `fine_tune_priority`, and `fine_tune_checkpoint`.
  When `fine_tune_checkpoint` is set, the provider factory routes inference to the
  fine-tuned endpoint with no prompt changes required.

- **`BaselineAgent`** — agent that must NOT be fine-tuned.
  These serve as adversarial quality gates against fine-tuned agents. Fine-tuning
  them defeats the purpose: a fine-tuned panel shares the worker's biases and will
  not catch hallucinations or drift introduced by fine-tuning.

### Assignment

| Agent | Class | Dataset | Priority |
|---|---|---|---|
| `KiraWorker` | `FineTunableAgent` | LEDGAR | 1 (highest) |
| `HarveyReviewer` | `FineTunableAgent` | CUAD | 2 |
| `KiraPanelReviewer` | **`BaselineAgent`** | — | never fine-tune |
| `AdminMergeAgent` | **`BaselineAgent`** | — | never fine-tune |
| `KiraValidatorAgent` | **`BaselineAgent`** | — | never fine-tune |

### Why Kira first

Kira makes recommended edits to specific clause language. Writing legally sound alternative
clause text is a highly specific skill that general models do poorly. LEDGAR (provision
classification, compliance rules) is a dense, task-specific dataset well-suited for this.
The improvement in `recommended_change` quality is the highest-leverage fine-tuning target
in the system.

### Why Harvey second

Harvey's job is policy-contradiction reasoning, not knowledge retrieval (the RAG provides
the knowledge). The hard part is distinguishing a legitimate policy update from a regression,
which requires legal domain judgment. CUAD (contract clause annotation and conflict
detection) is the right dataset. Upside is real but lower than Kira because the RAG
context already provides much of the domain knowledge Harvey needs.

### Why panel, admin, and validator must stay baseline

After Kira is fine-tuned, the `KiraPanelReviewers` are the primary protection against the
fine-tuned model hallucinating or drifting. A baseline panel will notice when fine-tuned
worker output looks unusual to a general model. A fine-tuned panel trained on the same data
will approve the same mistakes. Admin and the validator are structural agents — they work on
structured inputs, not domain reasoning, and do not benefit meaningfully from fine-tuning.

---

## 7. Output schema summary

```
Finding {
    finding_id, clause_uid, issue_type, severity
    exploitability, business_impact
    description, recommendation, recommendation_detail
    finding_scope:       intra_contract | cross_contract
    recommended_change:  str | None   ← populated by Kira only
    branch:              harvey | kira
    agent_role:          e.g. harvey_downstream_risk, kira_worker
    rag_citations:       [...] ← Harvey only, required
    contract_evidence:   [...] ← Kira, required
}

ClauseVerdict {
    clause_uid
    intra_comment:  str | None   ← Kira synthesis
    cross_comment:  str | None   ← Harvey synthesis
    severity:       low | medium | high | critical
    contributing_finding_ids: [...]
}

FinalVerdict {
    run_id, finalized_at, overall_risk_level
    harvey_findings:  [Finding]
    kira_findings:    [Finding]
    clause_verdicts:  [ClauseVerdict]   ← primary actionable output
    human_action:     approved | edited | rejected
}
```

---

## 8. Known limitations

### Same-model panel limitation
The `KiraPanelReviewers` run the same base model (gemma 4 26b) as the `KiraWorker`.
A model reviewing its own output tends to converge quickly after one revision because
both share the same biases. The panel is useful as a **formatting and completeness enforcer**
(is `recommended_change` concrete? are severities calibrated?) but will not reliably catch
deeper reasoning errors the worker makes. This limitation is acceptable pre-fine-tuning.
Post-fine-tuning it becomes an asset: the baseline panel can catch fine-tuned worker drift.

### LLM call count at scale
Worst-case per run: 3 (Harvey) + 13 (Kira) + 1 (Admin) = 17 LLM calls at 26B parameters.
Typical case: 3 + 8 + 1 = 12 calls. At cloud inference pricing this is non-trivial for
high-volume use. Mitigation: parallel Harvey/Kira execution halves wall-clock time. Future
mitigation: run panel reviewers at a smaller model (7B baseline) once the fine-tuned 26B
worker is deployed — the size contrast increases adversarial value of the panel.

### RAG corpus quality ceiling
Harvey's findings are only as good as what's in the RAG corpus. An empty or sparse corpus
causes Harvey to produce no findings (all citations fail the non-fabrication rule). The
system degrades gracefully (Harvey block returns empty, Kira still runs) but the
cross-contract analysis is lost. Corpus population is a prerequisite for Harvey value.

### Parser confidence gate
If any clause has extraction confidence below 0.3, `kira_review_block` is blocked before
reaching the LLM. A manual override is required. This is intentional but means low-quality
scanned PDFs silently stop the pipeline.

---

## 9. Deployment notes

**Model:** gemma 4 26b (all agents). Cloud inference.

**Worker processes:** 2 recommended to exploit the Harvey/Kira parallel execution at
`stage_order = 6`. A single worker runs them sequentially without blocking.

**Environment variables:**
```
LLM_PROVIDER=ollama              # or openrouter for cloud
OLLAMA_MODEL=gemma2:27b          # local dev
OPENROUTER_MODEL=google/gemma-2-27b-it  # cloud
POSTGRES_DSN=postgresql://...
JWT_SECRET=...
```

**Fine-tuning checkpoint deployment:**
Set `KiraWorker.fine_tune_checkpoint = "<path or hf-repo>"` in the class definition.
The provider factory (future work) reads this attribute and routes inference to the
fine-tuned endpoint. No other code changes are required.

---

## 10. Open questions / future work

- Harvey stages 1-3 each make an independent provider call. A future optimisation is to
  pass stage-1 and stage-2 output as conversation turns within a single multi-turn call,
  reducing latency and context re-encoding cost.

- `KiraPanelReviewers` could be run at a smaller model (e.g. 9B baseline) once the 26B
  worker is fine-tuned. The size contrast increases adversarial quality of the review.

- The Admin LLM call is currently a single-pass synthesis. A future version could run two
  passes (draft + self-critique) if output quality is insufficient.

- Export Report is not yet implemented (button is a no-op).

- Email sending for invites is not yet implemented (manual link copy only).

- Automated corpus ETL from the parquet datasets is not yet implemented (RISK-002).
  Corpus is seeded manually.
