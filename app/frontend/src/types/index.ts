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
  | "under_review"
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

export interface FindingAnchor {
  findingId: string;
  pageNumber: number;
  selectedText: string;
  bbox?: number[] | null;
  source: "contract_evidence" | "legacy_evidence";
  confidence?: number | null;
}

export interface ContractEvidence {
  clause_id: string;
  page: number;
  span?: [number, number] | null;
  text: string;
  confidence: number;
}

export interface RagCitation {
  chunk_id: string;
  document_id: string;
  version: string;
  page: number;
  source_path: string;
  chunk_hash: string;
  score: number;
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
  recommended_change?: string | null;
  evidence: EvidenceRef[];
  contract_evidence?: ContractEvidence[];
  rag_citations?: RagCitation[];
  branch: "harvey" | "kira";
  agent_role: string;
  round_number: number;
  consensus_state?: string | null;
  unresolved_by_consensus?: boolean;
}

export interface ClauseData {
  clause_uid: string;
  page_number: number;
  normalized_text: string;
  bbox: number[];
}

export interface PdfRect {
  page: number;
  x0: number;
  top: number;
  x1: number;
  bottom: number;
}

export interface PdfPageLayout {
  page: number;
  width: number;
  height: number;
}

export interface DocumentLayout {
  pages: PdfPageLayout[];
  finding_rects: Record<string, PdfRect[]>;
  annotation_rects: Record<string, PdfRect[]>;
  clause_rects: Record<string, PdfRect[]>;
}

export interface ContractEdit {
  text: string;
  plain_text?: string | null;
  rich_text?: Array<Record<string, unknown>> | null;
  page?: number | null;
  rects?: PdfRect[] | null;
  anchor_text?: string | null;
  edited_at: string;
}

// ============================================================================
// Document draft — Google Docs-style structured editor
// ============================================================================

export interface CommentAnchor {
  annotation_id: string;
  from_pos: number;
  to_pos: number;
}

export interface PendingSuggestion {
  finding_id: string;
  severity: string;
  description: string;
  replacement_text: string;
}

export type BlockStyle = "heading1" | "heading2" | "heading3" | "body" | "list_item";

export interface DraftBlock {
  block_id: string;
  clause_uid: string;
  page_number: number;
  style: BlockStyle;
  text: string;
  original_text: string;
  marks: Array<{ type: string; from_pos: number; to_pos: number }>;
  pending_suggestion: PendingSuggestion | null;
  comment_anchors: CommentAnchor[];
}

export interface DocumentDraft {
  blocks: DraftBlock[];
  revision: number;
}

export interface DocumentAnnotation {
  id: string;
  run_id: string;
  clause_uid: string;
  page_number?: number | null;
  selected_text?: string | null;
  span_start?: number | null;
  span_end?: number | null;
  annotation_type: "comment" | "suggestion";
  body: string;
  suggested_replacement?: string | null;
  status: "open" | "accepted" | "dismissed" | "deleted";
  source: "human" | "ai";
  finding_id?: string | null;
  author_id?: string | null;
  author_name?: string | null;
  created_at: string;
  updated_at: string;
}

// PDF-viewer anchor (rects-based, used by the PDF ContractReader variant)
export interface PdfCommentAnchor {
  workspaceId?: string | null;
  contractId?: string | number | null;
  runId: string;
  pageNumber: number;
  selectedText: string;
  rects: Array<{
    x: number;
    y: number;
    width: number;
    height: number;
  }>;
}

export interface DocumentComment {
  id: string;
  runId: string;
  workspaceId?: string | null;
  contractId?: string | number | null;
  pageNumber: number;
  selectedText: string;
  anchor: PdfCommentAnchor;
  userId: string;
  username: string;
  note: string;
  createdAt: string;
  updatedAt?: string | null;
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
  parser_confidence_state?: "ok" | "warning" | "blocked" | null;
}

export type RagDocType = "policy" | "reference_contract" | "playbook";

export interface RagDocumentResponse {
  document_id: string;
  doc_type: RagDocType;
  source_path: string;
  original_filename?: string | null;
  label?: string | null;
  version: string;
  tenant_id: string;
  workspace_id?: string | null;
  active: boolean;
  chunk_count: number;
  created_at: string;
  file_hash?: string | null;
}

export interface RagIngestionStatus {
  job_id: string;
  document_id?: string | null;
  state: "pending" | "running" | "done" | "failed";
  chunks_processed: number;
  total_chunks?: number | null;
  error_detail?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

// ============================================================================
// Contract versioning types
// ============================================================================

export interface ContractVersion {
  id: number;
  label: string;
  branch_name: string | null;
  run_id: string | null;
  run_state: string | null;
  risk_level: string | null;
  filename: string | null;
  created_at: string;
}

export interface ContractSummary {
  id: number;
  name: string;
  workspace_id: string | null;
  workspace_name: string | null;
  latest_label: string | null;
  latest_risk: string | null;
  latest_run_state: string | null;
  version_count: number;
  created_at: string;
  updated_at: string;
}

export interface ContractDetail {
  id: number;
  name: string;
  workspace_id: string | null;
  workspace_name: string | null;
  versions: ContractVersion[];
  created_at: string;
  updated_at: string;
}

export interface Workspace {
  workspace_id: string;
  name: string;
  description: string | null;
  role: string | null;
}

export interface HistoryEntry {
  run_id: string;
  contract_id: number;
  contract_name: string;
  workspace_id: string | null;
  workspace_name: string | null;
  version_label: string;
  filename: string | null;
  state: RunState;
  risk_level: string | null;
  human_action: "approved" | "rejected" | "edited" | null;
  created_at: string;
  updated_at: string;
}

export interface AddVersionResponse {
  run_id: string;
  label: string;
  contract_id: number;
  version_id: number;
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

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface AuthUser {
  user_id: string;
  email: string;
  display_name: string;
  job_title: string | null;
  department: string | null;
  avatar_color: string;
  org_id: string | null;
  org_role: string;
  org_name: string | null;
  token: string;
}

// ---------------------------------------------------------------------------
// Comments
// ---------------------------------------------------------------------------

export interface Comment {
  id: string;
  run_id?: string;
  workspace_id?: string | null;
  contract_id?: string | null;
  author_id: string;
  author_name: string;
  body: string;
  page_number?: number | null;
  selected_text?: string | null;
  anchor?: CommentAnchor | null;
  created_at: string;
  updated_at: string;
}
