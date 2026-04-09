// ============================================================================
// Legacy display types — still used by VerdictCard. We adapt the new
// FinalVerdict shape into these so the UI doesn't have to change.
// ============================================================================

export interface ClauseFlag {
  clause: string;
  issue: string;
  severity: "low" | "medium" | "high";
}

export interface ReviewResult {
  clause_flags: ClauseFlag[];
  risk_level: "low" | "medium" | "high";
  summary: string;
  recommendations: string[];
}

// ============================================================================
// New backend run/verdict contract (mirrors app/backend/models/schemas.py)
// ============================================================================

export type RunState =
  | "created"
  | "processing"
  | "awaiting_human_review"
  | "finalized"
  | "rejected"
  | "blocked"
  | "failed";

export type StageState =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "blocked"
  | "retrying";

export type SeverityLevel = "low" | "medium" | "high" | "critical";

export interface EvidenceRef {
  document_hash: string;
  parser_version: string;
  clause_uid: string;
  page: number;
  bbox: number[];
  normalized_text: string;
  extraction_confidence: number;
}

export interface Finding {
  finding_id: string;
  clause_uid: string;
  issue_type: string;
  severity: SeverityLevel;
  exploitability: string;
  business_impact: string;
  description: string;
  recommendation: string;
  recommendation_detail: string;
  evidence: EvidenceRef[];
  branch: "harvey" | "kira";
  agent_role: string;
  round_number: number;
}

export interface FinalVerdict {
  run_id: string;
  finalized_at: string;
  overall_risk_level: SeverityLevel;
  findings: Finding[];
  summary: string;
  recommendations: string[];
  human_action: "approved" | "edited" | "rejected";
  unresolved_finding_count: number;
}

export interface StageStatus {
  stage_name: string;
  state: StageState;
  retry_count: number;
  max_retries: number;
  started_at?: string | null;
  completed_at?: string | null;
  error_detail?: string | null;
}

export interface RunCreateResponse {
  run_id: string;
  state: RunState;
  created_at: string;
}

export interface RunDetail {
  run_id: string;
  state: RunState;
  stages: StageStatus[];
  filename: string;
  tenant_id?: string | null;
  policy_family_id?: string | null;
  policy_version_number?: number | null;
  jurisdiction?: string | null;
  regime?: string | null;
  effective_date?: string | null;
  created_at: string;
  updated_at: string;
  verdict?: FinalVerdict | null;
  blocked_reason?: string | null;
}

export type HumanRunAction = "approved" | "edited" | "rejected";

export interface HumanReviewPayload {
  schema_version?: number;
  run_action: HumanRunAction;
  reviewer_id: string;
  finding_actions?: unknown[];
  rejection_reason?: string;
}

export interface HumanReviewResult {
  run_id: string;
  run_action: HumanRunAction;
  state: RunState;
  verdict?: FinalVerdict | null;
}
