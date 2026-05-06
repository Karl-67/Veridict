import type {
  AddVersionResponse,
  ClauseData,
  ContractDetail,
  ContractEdit,
  ContractSummary,
  DocumentDraft,
  DocumentLayout,
  DocumentAnnotation,
  Finding,
  FinalVerdict,
  HistoryEntry,
  HumanReviewPayload,
  HumanReviewResult,
  RagDocType,
  RagDocumentResponse,
  RagIngestionStatus,
  ReviewResult,
  RunCreateResponse,
  RunDetail,
  SeverityLevel,
  Workspace,
} from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

// ----------------------------------------------------------------------------
// Default run metadata. The backend's POST /api/runs requires these form
// fields. Until the UI surfaces them, we hardcode placeholder defaults — these
// must reference an existing policy lineage in the policy repository, or the
// backend will return MissingLineageError.
// ----------------------------------------------------------------------------
const DEFAULT_RUN_PARAMS = {
  policy_family_id: "default",
  policy_version: "1",
  jurisdiction: "US",
  regime: "general",
};

export interface CreateRunOptions {
  policy_family_id?: string;
  policy_version?: number | string;
  jurisdiction?: string;
  regime?: string;
  effective_date?: string;
}

export async function createRun(
  file: File,
  options: CreateRunOptions = {}
): Promise<RunCreateResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append(
    "policy_family_id",
    options.policy_family_id ?? DEFAULT_RUN_PARAMS.policy_family_id
  );
  formData.append(
    "policy_version",
    String(options.policy_version ?? DEFAULT_RUN_PARAMS.policy_version)
  );
  formData.append(
    "jurisdiction",
    options.jurisdiction ?? DEFAULT_RUN_PARAMS.jurisdiction
  );
  formData.append("regime", options.regime ?? DEFAULT_RUN_PARAMS.regime);
  if (options.effective_date) {
    formData.append("effective_date", options.effective_date);
  }

  const response = await fetch(`${API_BASE}/runs`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Run creation failed" }));
    throw new Error(error.detail || "Run creation failed");
  }

  return response.json();
}

export async function getRun(runId: string): Promise<RunDetail> {
  const response = await fetch(`${API_BASE}/runs/${runId}`, { headers: authHeaders() });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch run" }));
    throw new Error(error.detail || "Failed to fetch run");
  }
  return response.json();
}

const TERMINAL_STATES = new Set([
  "finalized",
  "rejected",
  "blocked",
  "failed",
  "awaiting_human_review",
  "under_review",
  "cancelled",
]);

/**
 * Poll GET /api/runs/{run_id} until the run reaches a terminal state.
 * onUpdate is called with every intermediate result so the UI can show live stage progress.
 */
export interface PollSignal {
  cancelled: boolean;
}

export async function pollRunUntilDone(
  runId: string,
  intervalMs = 1500,
  timeoutMs = 30 * 60_000,
  onUpdate?: (run: RunDetail) => void,
  signal?: PollSignal
): Promise<RunDetail> {
  const start = Date.now();
  while (true) {
    if (signal?.cancelled) throw new DOMException("Cancelled", "AbortError");
    const run = await getRun(runId);
    if (signal?.cancelled) throw new DOMException("Cancelled", "AbortError");
    onUpdate?.(run);
    if (TERMINAL_STATES.has(run.state)) {
      return run;
    }
    if (Date.now() - start > timeoutMs) {
      return { ...run, state: "processing" };
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export async function healthCheck(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/health`);
  return response.json();
}

export async function submitHumanReview(
  runId: string,
  payload: HumanReviewPayload
): Promise<HumanReviewResult> {
  const response = await fetch(`${API_BASE}/runs/${runId}/human-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Review submission failed" }));
    throw new Error(error.detail || "Review submission failed");
  }
  return response.json();
}

export function getRunFileUrl(runId: string): string {
  return withAuthQuery(`${API_BASE}/runs/${runId}/file`);
}

export async function retryRun(runId: string): Promise<{ run_id: string; state: string }> {
  const response = await fetch(`${API_BASE}/runs/${runId}/retry`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Retry failed" }));
    throw new Error(error.detail || "Retry failed");
  }
  return response.json();
}

export async function startRunReview(runId: string): Promise<{ run_id: string; state: string }> {
  const response = await fetch(`${API_BASE}/runs/${runId}/start-review`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to start review" }));
    throw new Error(error.detail || "Failed to start review");
  }
  return response.json();
}

export async function getRunFindings(runId: string): Promise<Finding[]> {
  const response = await fetch(`${API_BASE}/runs/${runId}/findings`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to fetch findings");
  return response.json();
}

export async function listRunClauses(runId: string): Promise<ClauseData[]> {
  const response = await fetch(`${API_BASE}/runs/${runId}/clauses`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to load clauses");
  return response.json();
}

export async function getContractEdits(runId: string): Promise<Record<string, ContractEdit>> {
  const response = await fetch(`${API_BASE}/runs/${runId}/contract-edits`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to load edits");
  return response.json();
}

export async function getDocumentLayout(runId: string): Promise<DocumentLayout> {
  const response = await fetch(`${API_BASE}/runs/${runId}/document-layout`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to load document layout");
  return response.json();
}

export async function saveClauseEdit(
  runId: string,
  clauseUid: string,
  text: string,
  metadata: Partial<ContractEdit> = {}
): Promise<{ clause_uid: string; text: string }> {
  const response = await fetch(`${API_BASE}/runs/${runId}/contract-edits/${encodeURIComponent(clauseUid)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ text, ...metadata }),
  });
  if (!response.ok) throw new Error("Failed to save edit");
  return response.json();
}

export async function acceptFinding(
  runId: string,
  findingId: string,
  customText?: string
): Promise<{ finding_id: string; accepted: boolean; applied_text: string | null }> {
  const response = await fetch(`${API_BASE}/runs/${runId}/findings/${findingId}/accept`, {
    method: "POST",
    headers: customText ? { "Content-Type": "application/json", ...authHeaders() } : authHeaders(),
    body: customText ? JSON.stringify({ custom_text: customText }) : undefined,
  });
  if (!response.ok) throw new Error("Failed to accept finding");
  return response.json();
}

export async function dismissFinding(runId: string, findingId: string): Promise<{ finding_id: string; dismissed: boolean }> {
  const response = await fetch(`${API_BASE}/runs/${runId}/findings/${findingId}/dismiss`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!response.ok) throw new Error("Failed to dismiss finding");
  return response.json();
}

export async function listAnnotations(runId: string, clauseUid?: string): Promise<DocumentAnnotation[]> {
  const url = clauseUid
    ? `${API_BASE}/runs/${runId}/annotations?clause_uid=${encodeURIComponent(clauseUid)}`
    : `${API_BASE}/runs/${runId}/annotations`;
  const response = await fetch(url, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to load annotations");
  return response.json();
}

export async function createAnnotation(
  runId: string,
  payload: {
    clause_uid: string;
    annotation_type?: "comment" | "suggestion";
    body: string;
    suggested_replacement?: string | null;
    selected_text?: string | null;
    span_start?: number | null;
    span_end?: number | null;
    page_number?: number | null;
  }
): Promise<DocumentAnnotation> {
  const response = await fetch(`${API_BASE}/runs/${runId}/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("Failed to create annotation");
  return response.json();
}

export async function deleteAnnotation(runId: string, annotationId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/runs/${runId}/annotations/${annotationId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok && response.status !== 204) throw new Error("Failed to delete annotation");
}

export async function getDocumentDraft(runId: string): Promise<DocumentDraft> {
  const response = await fetch(`${API_BASE}/runs/${runId}/document-draft`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to load document draft");
  return response.json();
}

export async function saveBlockEdit(
  runId: string,
  clauseUid: string,
  plainText: string,
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/runs/${runId}/contract-edits/${encodeURIComponent(clauseUid)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ text: plainText, plain_text: plainText }),
    },
  );
  if (!response.ok) throw new Error("Failed to save block edit");
}

export function getDocxExportUrl(runId: string, original = false): string {
  const url = `${API_BASE}/runs/${runId}/export-docx${original ? "?original=true" : ""}`;
  return withAuthQuery(url);
}

export function getEditedPdfUrl(runId: string): string {
  return withAuthQuery(`${API_BASE}/runs/${runId}/export-edited`);
}

export async function uploadRagDocument(payload: {
  file: File;
  doc_type: RagDocType;
  policy_family_id?: string;
  jurisdiction?: string;
  version_label?: string;
}): Promise<{ job_id: string; document_id: string; state: string }> {
  const formData = new FormData();
  formData.append("file", payload.file);
  formData.append("doc_type", payload.doc_type);
  if (payload.policy_family_id) formData.append("policy_family_id", payload.policy_family_id);
  if (payload.jurisdiction) formData.append("jurisdiction", payload.jurisdiction);
  if (payload.version_label) formData.append("version_label", payload.version_label);
  const response = await fetch(`${API_BASE}/rag/documents`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "RAG upload failed" }));
    throw new Error(error.detail || "RAG upload failed");
  }
  return response.json();
}

export async function listRagDocuments(): Promise<RagDocumentResponse[]> {
  const response = await fetch(`${API_BASE}/rag/documents`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to fetch RAG documents");
  return response.json();
}

export async function getRagDocument(documentId: string): Promise<RagDocumentResponse> {
  const response = await fetch(`${API_BASE}/rag/documents/${documentId}`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to fetch RAG document");
  return response.json();
}

export async function getRagIngestionStatus(jobId: string): Promise<RagIngestionStatus> {
  const response = await fetch(`${API_BASE}/rag/ingestions/${jobId}`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to fetch ingestion status");
  return response.json();
}

export async function deleteRagDocument(documentId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/rag/documents/${documentId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok && response.status !== 204) throw new Error("Failed to delete RAG document");
}

// ----------------------------------------------------------------------------
// Auth
// ----------------------------------------------------------------------------

export interface AuthResponse {
  token: string;
  user_id: string;
  email: string;
  display_name: string;
}

interface BackendAuthResponse extends Omit<AuthResponse, "token"> {
  access_token: string;
}

function mapAuthResponse(data: BackendAuthResponse): AuthResponse {
  return {
    token: data.access_token,
    user_id: data.user_id,
    email: data.email,
    display_name: data.display_name,
  };
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("veridict_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function withAuthQuery(url: string): string {
  const token = localStorage.getItem("veridict_token");
  if (!token) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}token=${encodeURIComponent(token)}`;
}

export async function registerUser(email: string, display_name: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, display_name, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Registration failed" }));
    throw new Error(err.detail || "Registration failed");
  }
  return mapAuthResponse(await res.json());
}

export async function loginUser(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(err.detail || "Login failed");
  }
  return mapAuthResponse(await res.json());
}

// ----------------------------------------------------------------------------
// Comments
// ----------------------------------------------------------------------------

import type { Comment, DocumentComment } from "@/types";

export async function listContractComments(runId: string): Promise<Comment[]> {
  const res = await fetch(`${API_BASE}/runs/${runId}/comments`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Failed to fetch comments");
  return res.json();
}

export async function createContractComment(
  runId: string,
  body: string | (Partial<DocumentComment> & { body?: string })
): Promise<Comment> {
  const payload = typeof body === "string" ? { body } : {
    body: body.note ?? body.body ?? "",
    workspace_id: body.workspaceId,
    contract_id: body.contractId == null ? undefined : String(body.contractId),
    page_number: body.pageNumber,
    selected_text: body.selectedText,
    anchor: body.anchor,
  };
  const res = await fetch(`${API_BASE}/runs/${runId}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to post comment");
  return res.json();
}

export async function updateContractComment(runId: string, commentId: string, body: string): Promise<Comment> {
  const res = await fetch(`${API_BASE}/runs/${runId}/comments/${commentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ body }),
  });
  if (!res.ok) throw new Error("Failed to update comment");
  return res.json();
}

export async function deleteContractComment(runId: string, commentId: string): Promise<void> {
  await fetch(`${API_BASE}/runs/${runId}/comments/${commentId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

export async function listFindingComments(runId: string, findingId: string): Promise<Comment[]> {
  const res = await fetch(`${API_BASE}/runs/${runId}/findings/${findingId}/comments`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch finding comments");
  return res.json();
}

// ----------------------------------------------------------------------------
// Contract Editor
// ----------------------------------------------------------------------------

export interface EditorState {
  content: string;
  last_edited_by: string | null;
  last_edited_at: string | null;
  version: number;
}

export async function getEditorContent(runId: string): Promise<EditorState> {
  const res = await fetch(`${API_BASE}/runs/${runId}/editor`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Failed to fetch editor content");
  return res.json();
}

export async function saveEditorContent(runId: string, content: string, authorName?: string): Promise<EditorState> {
  const res = await fetch(`${API_BASE}/runs/${runId}/editor`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ content, author_name: authorName }),
  });
  if (!res.ok) throw new Error("Failed to save editor content");
  return res.json();
}

export async function createFindingComment(runId: string, findingId: string, body: string): Promise<Comment> {
  const res = await fetch(`${API_BASE}/runs/${runId}/findings/${findingId}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ body }),
  });
  if (!res.ok) throw new Error("Failed to post comment");
  return res.json();
}

export async function deleteFindingComment(runId: string, findingId: string, commentId: string): Promise<void> {
  await fetch(`${API_BASE}/runs/${runId}/findings/${findingId}/comments/${commentId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

// ----------------------------------------------------------------------------
// Contract versioning API
// ----------------------------------------------------------------------------

export async function listWorkspaces(): Promise<Workspace[]> {
  const response = await fetch(`${API_BASE}/workspaces`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to fetch workspaces");
  return response.json();
}

export async function listContracts(workspaceId?: string): Promise<ContractSummary[]> {
  const url = workspaceId
    ? `${API_BASE}/contracts?workspace_id=${encodeURIComponent(workspaceId)}`
    : `${API_BASE}/contracts`;
  const response = await fetch(url, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to fetch contracts");
  return response.json();
}

export async function createContract(name: string, workspaceId: string): Promise<ContractSummary> {
  const response = await fetch(`${API_BASE}/contracts`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ name, workspace_id: workspaceId }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to create contract" }));
    throw new Error(error.detail || "Failed to create contract");
  }
  return response.json();
}

export async function getContract(contractId: number): Promise<ContractDetail> {
  const response = await fetch(`${API_BASE}/contracts/${contractId}`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to fetch contract");
  return response.json();
}

export async function addContractVersion(
  contractId: number,
  file: File,
  options: { branchFrom?: number; branchName?: string } = {}
): Promise<AddVersionResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("policy_family_id", DEFAULT_RUN_PARAMS.policy_family_id);
  formData.append("policy_version", DEFAULT_RUN_PARAMS.policy_version);
  formData.append("jurisdiction", DEFAULT_RUN_PARAMS.jurisdiction);
  formData.append("regime", DEFAULT_RUN_PARAMS.regime);
  if (options.branchFrom !== undefined) formData.append("branch_from", String(options.branchFrom));
  if (options.branchName) formData.append("branch_name", options.branchName);

  const response = await fetch(`${API_BASE}/contracts/${contractId}/versions`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to add version" }));
    throw new Error(error.detail || "Failed to add version");
  }
  return response.json();
}

export interface UpdateProfilePayload {
  display_name?: string;
  job_title?: string;
  department?: string;
  avatar_color?: string;
  current_password?: string;
  new_password?: string;
}

export async function updateProfile(payload: UpdateProfilePayload): Promise<import("@/types").AuthUser> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Update failed" }));
    throw new Error(err.detail || "Update failed");
  }
  const data = await res.json();
  return {
    user_id: data.user_id,
    email: data.email,
    display_name: data.display_name,
    job_title: data.job_title,
    department: data.department,
    avatar_color: data.avatar_color,
    org_id: data.org_id,
    org_role: data.org_role,
    org_name: data.org_name,
    token: data.access_token,
  };
}

export async function listHistory(limit = 100): Promise<HistoryEntry[]> {
  const res = await fetch(`${API_BASE}/history?limit=${limit}`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Failed to fetch history");
  return res.json();
}

// ----------------------------------------------------------------------------
// Adapter: convert new FinalVerdict shape into the legacy ReviewResult shape
// the existing VerdictCard expects.
// ----------------------------------------------------------------------------

const severityMap: Record<SeverityLevel, "low" | "medium" | "high"> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "high",
};

function findingToClauseLabel(description: string, clauseUid: string): string {
  // Pull a short human label out of the finding's description, falling back
  // to the clause uid.
  const firstSentence = description.split(/[.\n]/)[0]?.trim();
  if (firstSentence && firstSentence.length > 0 && firstSentence.length <= 80) {
    return firstSentence;
  }
  if (firstSentence && firstSentence.length > 80) {
    return firstSentence.slice(0, 77) + "...";
  }
  return clauseUid;
}

export function verdictToReviewResult(verdict: FinalVerdict): ReviewResult {
  return {
    risk_level: severityMap[verdict.overall_risk_level] ?? "medium",
    summary: verdict.summary,
    recommendations: verdict.recommendations,
    clause_flags: verdict.findings.map((f) => ({
      clause: findingToClauseLabel(f.description, f.clause_uid),
      issue: f.description,
      severity: severityMap[f.severity] ?? "medium",
    })),
  };
}
