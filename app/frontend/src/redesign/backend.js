const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api";

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
  if (!res.ok) throw new Error(data.detail || fallback);
  return data;
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

async function logout() {
  await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" }).catch(() => {});
  localStorage.removeItem("veridict_token");
  localStorage.removeItem("veridict_user");
}

function mapContract(c) {
  return {
    id: c.id,
    name: c.name,
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

async function listContracts() {
  const res = await fetch(`${API_BASE}/contracts`, { headers: authHeaders() });
  return (await readJson(res, "Failed to load contracts")).map(mapContract);
}

async function getContract(id) {
  const res = await fetch(`${API_BASE}/contracts/${id}`, { headers: authHeaders() });
  return mapContractDetail(await readJson(res, "Failed to load contract"));
}

async function listWorkspaces() {
  const res = await fetch(`${API_BASE}/workspaces`, { headers: authHeaders() });
  return readJson(res, "Failed to load workspaces");
}

async function createContract(name, workspaceId) {
  const res = await fetch(`${API_BASE}/contracts`, {
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
  const res = await fetch(`${API_BASE}/contracts/${contractId}/versions`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  return readJson(res, "Failed to add version");
}

async function listHistory(limit = 100) {
  const res = await fetch(`${API_BASE}/history?limit=${limit}`, { headers: authHeaders() });
  return readJson(res, "Failed to load history");
}

async function getRun(runId) {
  const res = await fetch(`${API_BASE}/runs/${runId}`, { headers: authHeaders() });
  return readJson(res, "Failed to load run");
}

async function getRunFindings(runId) {
  const res = await fetch(`${API_BASE}/runs/${runId}/findings`, { headers: authHeaders() });
  return readJson(res, "Failed to load findings");
}

async function submitHumanReview(runId, action, reason = "") {
  const user = currentUser();
  const res = await fetch(`${API_BASE}/runs/${runId}/human-review`, {
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
  const res = await fetch(`${API_BASE}/auth/me`, {
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

async function uploadRagDocument(file, docType = "policy", workspaceId = null) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doc_type", docType);
  if (workspaceId) formData.append("workspace_id", workspaceId);
  const res = await fetch(`${API_BASE}/rag/documents`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  return readJson(res, "Upload failed");
}

async function listRagDocuments(workspaceId = null) {
  const url = workspaceId
    ? `${API_BASE}/rag/documents?workspace_id=${workspaceId}`
    : `${API_BASE}/rag/documents`;
  const res = await fetch(url, { headers: authHeaders() });
  return readJson(res, "Failed to load documents");
}

async function getRagIngestionStatus(jobId) {
  const res = await fetch(`${API_BASE}/rag/ingestions/${jobId}`, { headers: authHeaders() });
  return readJson(res, "Failed to get ingestion status");
}

async function deleteRagDocument(documentId) {
  const res = await fetch(`${API_BASE}/rag/documents/${documentId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 204) return null;
  return readJson(res, "Delete failed");
}

async function adminGet(path) {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  return readJson(res, "Admin request failed");
}

async function adminSend(method, path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: authHeaders(Boolean(body)),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  return readJson(res, "Admin request failed");
}

window.verdictApi = {
  API_BASE,
  login,
  createOrg,
  logout,
  currentUser,
  listContracts,
  getContract,
  listWorkspaces,
  createContract,
  addContractVersion,
  listHistory,
  getRun,
  getRunFindings,
  submitHumanReview,
  updateProfile,
  getRunFileUrl,
  uploadRagDocument,
  listRagDocuments,
  getRagIngestionStatus,
  deleteRagDocument,
  adminGet,
  adminSend,
};
