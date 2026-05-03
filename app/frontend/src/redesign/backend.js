// Default `/api` = same origin as the Vite dev server (see vite.config proxy) or production host; required for refresh cookies (SameSite=Lax, path=/api/auth).
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";
const ACCESS_TOKEN_REFRESH_MS = (12 * 60 - 5) * 60 * 1000; // refresh 5 min before 12-hour access expiry

export const VERDICT_SESSION_EXPIRED = "verdict-session-expired";

let refreshTimer = null;
let sessionExpiredPending = false;
/** Single in-flight refresh — backend rotates (revokes) the old refresh token, so parallel refreshes race and log the user out. */
let refreshInFlight = null;

function token() {
  return localStorage.getItem("veridict_token");
}

function authHeaders(json = false) {
  const headers = json ? { "Content-Type": "application/json" } : {};
  const t = token();
  if (t) headers.Authorization = `Bearer ${t}`;
  return headers;
}

async function readJson(res, fallback) {
  const data = await res.json().catch(() => ({ detail: fallback }));
  if (!res.ok) {
    if (res.status === 429) throw new Error("Too many requests — please wait a moment and try again.");
    if (res.status === 403) throw new Error("You don't have permission to perform this action.");
    if (res.status >= 500) throw new Error("Server error — please try again shortly.");
    const detail = data.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map(item => item?.msg ?? JSON.stringify(item)).join("; ")
        : detail
          ? JSON.stringify(detail)
          : fallback;
    throw new Error(message);
  }
  return data;
}

// Try to refresh the access token using the httpOnly refresh cookie.
// fatal: true when the refresh token is invalid/expired (caller should clear the session).
// fatal: false on network errors — do not clear the session.
async function tryRefreshToken() {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, { method: "POST", credentials: "include" });
      if (!res.ok) {
        let detail = "";
        try {
          const errBody = await res.json();
          detail = typeof errBody?.detail === "string" ? errBody.detail : "";
        } catch {
          /* ignore */
        }
        // Cookie not sent (common dev mis-match: localhost UI + 127.0.0.1 API) — not a revoked session.
        const missingRefreshCookie = res.status === 401 && detail === "No refresh token";
        const fatal = (res.status === 401 || res.status === 403) && !missingRefreshCookie;
        return { ok: false, fatal, missingRefreshCookie };
      }
      const data = await res.json();
      const user = mapAuthUser(data);
      localStorage.setItem("veridict_token", user.token);
      localStorage.setItem("veridict_user", JSON.stringify(user));
      return { ok: true, fatal: false, missingRefreshCookie: false };
    } catch {
      return { ok: false, fatal: false, missingRefreshCookie: false };
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

function clearSession() {
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
  localStorage.removeItem("veridict_token");
  localStorage.removeItem("veridict_user");
  sessionExpiredPending = true;
  window.dispatchEvent(new CustomEvent(VERDICT_SESSION_EXPIRED, { detail: { reason: "expired" } }));
}

/** Returns true once after clearSession() if the auth UI should show a session-expired message. */
function consumeSessionExpiredNotice() {
  const v = sessionExpiredPending;
  sessionExpiredPending = false;
  return v;
}

function scheduleSilentRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer);
  if (!currentUser()) return;
  refreshTimer = setTimeout(async () => {
    refreshTimer = null;
    const r = await tryRefreshToken();
    if (r.ok) scheduleSilentRefresh();
    else if (r.fatal) clearSession();
    else scheduleSilentRefresh();
  }, ACCESS_TOKEN_REFRESH_MS);
}

// Fetch wrapper that retries once after auto-refreshing the access token on 401.
// Also handles network failures and enforces a timeout (default 30s; pass timeoutMs in options to override).
async function apiFetch(url, options = {}) {
  const { timeoutMs = 30000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(url, { ...fetchOptions, credentials: "include", signal: controller.signal });
  } catch (err) {
    if (err.name === "AbortError") throw new Error("Request timed out — the server took too long to respond.");
    throw new Error("Network error — please check your connection and try again.");
  } finally {
    clearTimeout(timeoutId);
  }
  if (res.status === 401) {
    const refreshed = await tryRefreshToken();
    if (refreshed.ok) {
      const newHeaders = { ...(fetchOptions.headers || {}) };
      const t = token();
      if (t) newHeaders.Authorization = `Bearer ${t}`;
      try {
        res = await fetch(url, { ...fetchOptions, headers: newHeaders, credentials: "include" });
      } catch {
        throw new Error("Network error — please check your connection and try again.");
      }
      if (res.status === 401) clearSession();
    } else if (refreshed.fatal) {
      clearSession();
    }
  }
  return res;
}

function mapAuthUser(data) {
  return {
    user_id: data.user_id,
    email: data.email,
    display_name: data.display_name,
    job_title: data.job_title ?? null,
    department: data.department ?? null,
    avatar_color: data.avatar_color ?? "#C8973E",
    org_id: data.org_id ?? null,
    org_role: data.org_role ?? "member",
    org_name: data.org_name ?? null,
    token: data.access_token,
  };
}

function saveAuth(data) {
  const user = mapAuthUser(data);
  localStorage.setItem("veridict_token", user.token);
  localStorage.setItem("veridict_user", JSON.stringify(user));
  scheduleSilentRefresh();
  return user;
}

function currentUser() {
  try {
    const raw = localStorage.getItem("veridict_user");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

async function login(email, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: authHeaders(true),
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  return saveAuth(await readJson(res, "Login failed"));
}

async function createOrg(payload) {
  const res = await fetch(`${API_BASE}/auth/create-org`, {
    method: "POST",
    headers: authHeaders(true),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return saveAuth(await readJson(res, "Account creation failed"));
}

async function invitePreview(token) {
  const res = await fetch(`${API_BASE}/auth/invite-preview/${encodeURIComponent(token)}`, {
    headers: authHeaders(),
    credentials: "include",
  });
  return readJson(res, "Invite not found or expired");
}

async function registerFromInvite(payload) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: authHeaders(true),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return saveAuth(await readJson(res, "Invite registration failed"));
}

async function logout() {
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
  await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" }).catch(() => {});
  localStorage.removeItem("veridict_token");
  localStorage.removeItem("veridict_user");
}

function mapContract(c) {
  return {
    id: c.id,
    name: c.name,
    workspaceId: c.workspace_id ?? null,
    versionCount: c.version_count,
    latestLabel: c.latest_label ?? "-",
    latestRunState: c.latest_run_state,
    latestRisk: c.latest_risk,
    updatedAt: c.updated_at,
    workspace: c.workspace_name ?? "Workspace",
  };
}

function mapContractDetail(c) {
  return {
    id: c.id,
    name: c.name,
    workspace: c.workspace_name ?? "Workspace",
    versions: (c.versions ?? []).slice().reverse().map((v) => ({
      id: v.id,
      label: v.label,
      filename: v.filename ?? "Uploaded document",
      runState: v.run_state,
      risk: v.risk_level,
      runId: v.run_id,
      createdAt: v.created_at,
      findingCount: 0,
    })),
  };
}

async function listContracts(workspaceId = null) {
  const qs = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  const res = await apiFetch(`${API_BASE}/contracts${qs}`, { headers: authHeaders() });
  return (await readJson(res, "Failed to load contracts")).map(mapContract);
}

async function getContract(id) {
  const res = await apiFetch(`${API_BASE}/contracts/${id}`, { headers: authHeaders() });
  return mapContractDetail(await readJson(res, "Failed to load contract"));
}

async function listWorkspaces() {
  const res = await apiFetch(`${API_BASE}/workspaces`, { headers: authHeaders() });
  return readJson(res, "Failed to load workspaces");
}

async function createContract(name, workspaceId) {
  const res = await apiFetch(`${API_BASE}/contracts`, {
    method: "POST",
    headers: authHeaders(true),
    body: JSON.stringify({ name, workspace_id: workspaceId }),
  });
  return readJson(res, "Failed to create contract");
}

async function addContractVersion(contractId, file) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("policy_family_id", "default");
  formData.append("policy_version", "1");
  formData.append("jurisdiction", "US");
  formData.append("regime", "general");
  const res = await apiFetch(`${API_BASE}/contracts/${contractId}/versions`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
    timeoutMs: 300000,
  });
  return readJson(res, "Failed to add version");
}

async function listHistory(limit = 100) {
  const res = await apiFetch(`${API_BASE}/history?limit=${limit}`, { headers: authHeaders() });
  return readJson(res, "Failed to load history");
}

async function getRun(runId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}`, { headers: authHeaders() });
  return readJson(res, "Failed to load run");
}

async function getRunFindings(runId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/findings`, { headers: authHeaders() });
  return readJson(res, "Failed to load findings");
}

async function retryRun(runId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/retry`, {
    method: "POST",
    headers: authHeaders(),
  });
  return readJson(res, "Retry failed");
}

async function submitHumanReview(runId, action, reason = "") {
  const user = currentUser();
  const res = await apiFetch(`${API_BASE}/runs/${runId}/human-review`, {
    method: "POST",
    headers: authHeaders(true),
    body: JSON.stringify({
      run_action: action,
      reviewer_id: user?.user_id ?? "frontend",
      finding_actions: [],
      rejection_reason: reason || undefined,
    }),
  });
  return readJson(res, "Review submission failed");
}

async function updateProfile(payload) {
  const res = await apiFetch(`${API_BASE}/auth/me`, {
    method: "PATCH",
    headers: authHeaders(true),
    body: JSON.stringify(payload),
  });
  return saveAuth(await readJson(res, "Profile update failed"));
}

function getRunFileUrl(runId) {
  const t = token();
  return `${API_BASE}/runs/${runId}/file${t ? `?token=${encodeURIComponent(t)}` : ""}`;
}

function getRunExportUrl(runId) {
  const t = token();
  return `${API_BASE}/runs/${runId}/export-edited${t ? `?token=${encodeURIComponent(t)}` : ""}`;
}

async function uploadRagDocument(file, docType = "policy", workspaceId = null) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doc_type", docType);
  if (workspaceId) formData.append("workspace_id", workspaceId);
  const res = await apiFetch(`${API_BASE}/rag/documents`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
    timeoutMs: 300000,
  });
  return readJson(res, "Upload failed");
}

async function listRagDocuments(workspaceId = null) {
  const url = workspaceId
    ? `${API_BASE}/rag/documents?workspace_id=${workspaceId}`
    : `${API_BASE}/rag/documents`;
  const res = await apiFetch(url, { headers: authHeaders() });
  return readJson(res, "Failed to load documents");
}

async function getRagIngestionStatus(jobId) {
  const res = await apiFetch(`${API_BASE}/rag/ingestions/${jobId}`, { headers: authHeaders() });
  return readJson(res, "Failed to get ingestion status");
}

async function deleteRagDocument(documentId) {
  const res = await apiFetch(`${API_BASE}/rag/documents/${documentId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 204) return null;
  return readJson(res, "Delete failed");
}

async function listRunComments(runId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/comments`, { headers: authHeaders() });
  return readJson(res, "Failed to load comments");
}

async function postRunComment(runId, body) {
  const payload = typeof body === "string" ? { body } : body;
  const res = await apiFetch(`${API_BASE}/runs/${runId}/comments`, {
    method: "POST",
    headers: authHeaders(true),
    body: JSON.stringify(payload),
  });
  return readJson(res, "Failed to post comment");
}

async function deleteRunComment(runId, commentId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/comments/${commentId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 204) return null;
  return readJson(res, "Failed to delete comment");
}

async function listRunClauses(runId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/clauses`, { headers: authHeaders() });
  return readJson(res, "Failed to load clauses");
}

async function getContractEdits(runId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/contract-edits`, { headers: authHeaders() });
  return readJson(res, "Failed to load edits");
}

async function getDocumentLayout(runId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/document-layout`, { headers: authHeaders() });
  return readJson(res, "Failed to load document layout");
}

async function saveClauseEdit(runId, clauseUid, text, metadata = {}) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/contract-edits/${encodeURIComponent(clauseUid)}`, {
    method: "PUT",
    headers: authHeaders(true),
    body: JSON.stringify({ text, ...metadata }),
  });
  return readJson(res, "Failed to save edit");
}

async function acceptFinding(runId, findingId, customText) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/findings/${findingId}/accept`, {
    method: "POST",
    headers: authHeaders(Boolean(customText)),
    body: customText ? JSON.stringify({ custom_text: customText }) : undefined,
  });
  return readJson(res, "Failed to accept finding");
}

async function dismissFinding(runId, findingId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/findings/${findingId}/dismiss`, {
    method: "POST",
    headers: authHeaders(),
  });
  return readJson(res, "Failed to dismiss finding");
}

async function listAnnotations(runId, clauseUid) {
  const suffix = clauseUid ? `?clause_uid=${encodeURIComponent(clauseUid)}` : "";
  const res = await apiFetch(`${API_BASE}/runs/${runId}/annotations${suffix}`, { headers: authHeaders() });
  return readJson(res, "Failed to load annotations");
}

async function createAnnotation(runId, payload) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/annotations`, {
    method: "POST",
    headers: authHeaders(true),
    body: JSON.stringify(payload),
  });
  return readJson(res, "Failed to create annotation");
}

async function deleteAnnotation(runId, annotationId) {
  const res = await apiFetch(`${API_BASE}/runs/${runId}/annotations/${annotationId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 204) return null;
  return readJson(res, "Failed to delete annotation");
}

async function adminGet(path) {
  const res = await apiFetch(`${API_BASE}${path}`, { headers: authHeaders() });
  return readJson(res, "Admin request failed");
}

async function adminSend(method, path, body) {
  const res = await apiFetch(`${API_BASE}${path}`, {
    method,
    headers: authHeaders(Boolean(body)),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  return readJson(res, "Admin request failed");
}

// Validate session on load: refresh if we have cached user (network errors keep local session).
(async function bootSession() {
  if (!currentUser()) return;
  const r = await tryRefreshToken();
  if (r.ok) scheduleSilentRefresh();
  else if (r.fatal) clearSession();
  else scheduleSilentRefresh();
})();

window.verdictApi = {
  API_BASE,
  login,
  createOrg,
  invitePreview,
  registerFromInvite,
  logout,
  currentUser,
  VERDICT_SESSION_EXPIRED,
  consumeSessionExpiredNotice,
  listContracts,
  getContract,
  listWorkspaces,
  createContract,
  addContractVersion,
  listHistory,
  getRun,
  getRunFindings,
  retryRun,
  submitHumanReview,
  updateProfile,
  getRunFileUrl,
  getRunExportUrl,
  uploadRagDocument,
  listRagDocuments,
  getRagIngestionStatus,
  deleteRagDocument,
  listRunComments,
  postRunComment,
  deleteRunComment,
  listRunClauses,
  getContractEdits,
  getDocumentLayout,
  saveClauseEdit,
  acceptFinding,
  dismissFinding,
  listAnnotations,
  createAnnotation,
  deleteAnnotation,
  adminGet,
  adminSend,
};
