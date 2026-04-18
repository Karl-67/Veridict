import type {
  AddVersionResponse,
  ContractDetail,
  ContractSummary,
  FinalVerdict,
  HumanReviewPayload,
  HumanReviewResult,
  ReviewResult,
  RunCreateResponse,
  RunDetail,
  SeverityLevel,
} from "@/types";

const API_BASE = "http://localhost:8000/api";

// ----------------------------------------------------------------------------
// Default run metadata. The backend's POST /api/runs requires these form
// fields. Until the UI surfaces them, we hardcode placeholder defaults — these
// must reference an existing policy lineage in the policy repository, or the
// backend will return MissingLineageError.
// ----------------------------------------------------------------------------
const DEFAULT_RUN_PARAMS = {
  tenant_id: "demo-tenant",
  policy_family_id: "default",
  policy_version: "1",
  jurisdiction: "US",
  regime: "general",
};

export interface CreateRunOptions {
  tenant_id?: string;
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
  formData.append("tenant_id", options.tenant_id ?? DEFAULT_RUN_PARAMS.tenant_id);
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
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Run creation failed" }));
    throw new Error(error.detail || "Run creation failed");
  }

  return response.json();
}

export async function getRun(runId: string): Promise<RunDetail> {
  const response = await fetch(`${API_BASE}/runs/${runId}`);
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
]);

/**
 * Poll GET /api/runs/{run_id} until the run reaches a terminal state.
 * onUpdate is called with every intermediate result so the UI can show live stage progress.
 */
export async function pollRunUntilDone(
  runId: string,
  intervalMs = 1500,
  timeoutMs = 5 * 60_000,
  onUpdate?: (run: RunDetail) => void
): Promise<RunDetail> {
  const start = Date.now();
  while (true) {
    const run = await getRun(runId);
    onUpdate?.(run);
    if (TERMINAL_STATES.has(run.state)) {
      return run;
    }
    if (Date.now() - start > timeoutMs) {
      throw new Error("Run polling timed out after 5 minutes");
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Review submission failed" }));
    throw new Error(error.detail || "Review submission failed");
  }
  return response.json();
}

export function getRunFileUrl(runId: string): string {
  return `${API_BASE}/runs/${runId}/file`;
}

// ----------------------------------------------------------------------------
// Contract versioning API
// ----------------------------------------------------------------------------

export async function listContracts(tenantId = "demo-tenant"): Promise<ContractSummary[]> {
  const response = await fetch(`${API_BASE}/contracts?tenant_id=${encodeURIComponent(tenantId)}`);
  if (!response.ok) throw new Error("Failed to fetch contracts");
  return response.json();
}

export async function createContract(name: string, tenantId = "demo-tenant"): Promise<ContractSummary> {
  const response = await fetch(`${API_BASE}/contracts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, tenant_id: tenantId }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to create contract" }));
    throw new Error(error.detail || "Failed to create contract");
  }
  return response.json();
}

export async function getContract(contractId: number): Promise<ContractDetail> {
  const response = await fetch(`${API_BASE}/contracts/${contractId}`);
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
  formData.append("tenant_id", DEFAULT_RUN_PARAMS.tenant_id);
  formData.append("policy_family_id", DEFAULT_RUN_PARAMS.policy_family_id);
  formData.append("policy_version", DEFAULT_RUN_PARAMS.policy_version);
  formData.append("jurisdiction", DEFAULT_RUN_PARAMS.jurisdiction);
  formData.append("regime", DEFAULT_RUN_PARAMS.regime);
  if (options.branchFrom !== undefined) formData.append("branch_from", String(options.branchFrom));
  if (options.branchName) formData.append("branch_name", options.branchName);

  const response = await fetch(`${API_BASE}/contracts/${contractId}/versions`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to add version" }));
    throw new Error(error.detail || "Failed to add version");
  }
  return response.json();
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
      issue: f.recommendation_detail || f.description,
      severity: severityMap[f.severity] ?? "medium",
    })),
  };
}
