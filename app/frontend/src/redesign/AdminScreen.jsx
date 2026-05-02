
// ── Admin mock data ───────────────────────────────────────────────────────────

const MOCK_ADMIN_USERS = [
  { id: "u1", name: "Sarah Johnson",  email: "sarah@verdictai.io",   jobTitle: "Senior Associate", dept: "Corporate M&A", role: "org_admin", color: "#C8973E", locked: false },
  { id: "u2", name: "Michael Kim",    email: "mkim@verdictai.io",    jobTitle: "Partner",          dept: "Litigation",    role: "member",    color: "#6366F1", locked: false },
  { id: "u3", name: "Jennifer Liu",   email: "jliu@verdictai.io",    jobTitle: "Associate",        dept: "Corporate M&A", role: "member",    color: "#EC4899", locked: false },
  { id: "u4", name: "Tom Parker",     email: "tparker@verdictai.io", jobTitle: "Paralegal",        dept: "Operations",    role: "member",    color: "#10B981", locked: true  },
];

const MOCK_ADMIN_WS = [
  { id: "ws1", name: "Legal",       desc: "Primary contract review", memberCount: 4 },
  { id: "ws2", name: "HR",          desc: "Employment agreements",   memberCount: 2 },
  { id: "ws3", name: "Procurement", desc: "Vendor contracts",        memberCount: 1 },
];

const MOCK_ADMIN_INVITES_INIT = [
  { id: "inv1", email: "alex.chen@verdictai.io", workspace: "Legal", role: "Reviewer", invitedBy: "Sarah Johnson" },
];

const adminRoleColors = { org_admin: "var(--accent)", member: "var(--text-2)" };

// ── Admin Screen ──────────────────────────────────────────────────────────────

function AdminScreen() {
  const [tab, setTab]         = React.useState("users");
  const [users, setUsers]     = React.useState([]);
  const [workspaces, setWorkspaces] = React.useState([]);
  const [selectedWs, setSel]  = React.useState(null);
  const [wsMembers, setWsMembers] = React.useState([]);
  const [wsMembersLoading, setWsMembersLoading] = React.useState(false);
  const [invites, setInvites] = React.useState([]);
  const [adminLoading, setAdminLoading] = React.useState(true);
  const [inviteEmail, setInviteEmail] = React.useState("");
  const [inviteRole, setInviteRole]   = React.useState("reviewer");
  const [inviteLink, setInviteLink]   = React.useState(null);
  const [copied, setCopied]           = React.useState(false);
  const [newWsName, setNewWsName]     = React.useState("");
  const [newWsDesc, setNewWsDesc]     = React.useState("");
  const [wsCreateOpen, setWsCreateOpen] = React.useState(false);
  const [wsCreating, setWsCreating]   = React.useState(false);
  const [wsError, setWsError]         = React.useState(null);
  const [ragDocs, setRagDocs]         = React.useState([]);
  const [ragLoading, setRagLoading]   = React.useState(false);
  const [ragUploading, setRagUploading] = React.useState(false);
  const [ragDocType, setRagDocType]   = React.useState("policy");
  const ragInputRef = React.useRef(null);

  function ini(n) { return n.split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase(); }

  const loadAdmin = React.useCallback(() => {
    Promise.all([
      window.verdictApi.adminGet("/admin/users"),
      window.verdictApi.adminGet("/admin/workspaces"),
      window.verdictApi.adminGet("/admin/invites"),
    ]).then(([u, w, i]) => {
      setUsers((u ?? []).map(row => ({
        id: row.user_id,
        name: row.display_name,
        email: row.email,
        jobTitle: row.job_title,
        dept: row.department,
        role: row.org_role,
        color: row.avatar_color,
        locked: row.locked,
      })));
      setWorkspaces((w ?? []).map(row => ({
        id: row.workspace_id,
        name: row.name,
        desc: row.description,
        memberCount: row.member_count,
      })));
      setInvites((i ?? []).map(row => ({
        id: row.invite_id,
        email: row.email,
        workspace: row.workspace_name ?? "Organisation",
        role: row.workspace_role,
        invitedBy: row.invited_by,
      })));
    }).finally(() => setAdminLoading(false));
  }, []);

  React.useEffect(() => { loadAdmin(); }, [loadAdmin]);

  const loadWorkspaceMembers = React.useCallback((workspaceId) => {
    if (!workspaceId) return Promise.resolve([]);
    setWsMembersLoading(true);
    return window.verdictApi.adminGet(`/admin/workspaces/${workspaceId}/members`)
      .then(rows => {
        const members = rows ?? [];
        setWsMembers(members.map(row => ({
          id: row.user_id,
          name: row.display_name,
          email: row.email,
          jobTitle: row.job_title,
          dept: row.department,
          color: row.avatar_color,
          role: row.role,
        })));
        return members;
      })
      .catch(err => {
        setWsError(err?.message || "Failed to load workspace members");
        setWsMembers([]);
        return [];
      })
      .finally(() => setWsMembersLoading(false));
  }, []);

  function openWorkspace(ws) {
    setWsError(null);
    setWsCreateOpen(false);
    setSel(ws);
    loadWorkspaceMembers(ws.id);
  }

  function openCreateWorkspace() {
    setSel(null);
    setWsError(null);
    setWsCreateOpen(true);
    window.requestAnimationFrame(() => document.getElementById("new-workspace-name")?.focus());
  }

  function closeCreateWorkspace() {
    setWsCreateOpen(false);
    setWsError(null);
    setNewWsName("");
    setNewWsDesc("");
  }

  async function createWorkspace(e) {
    e?.preventDefault?.();
    const name = newWsName.trim();
    if (!name || wsCreating) {
      setWsError("Workspace name is required");
      return;
    }
    setWsCreating(true);
    setWsError(null);
    try {
      const created = await window.verdictApi.adminSend("POST", "/admin/workspaces", {
        name,
        description: newWsDesc.trim() || null,
      });
      const createdWs = {
        id: created.workspace_id,
        name: created.name,
        desc: created.description,
        memberCount: created.member_count ?? 1,
      };
      setWorkspaces(prev => [...prev, createdWs]);
      setNewWsName("");
      setNewWsDesc("");
      setWsCreateOpen(false);
      setSel(createdWs);
      loadWorkspaceMembers(createdWs.id);
      loadAdmin();
    } catch (err) {
      setWsError(err?.message || "Failed to create workspace");
    } finally {
      setWsCreating(false);
    }
  }

  async function changeWorkspaceMemberRole(userId, role) {
    if (!selectedWs) return;
    await window.verdictApi.adminSend("PATCH", `/admin/workspaces/${selectedWs.id}/members/${userId}`, { role });
    loadWorkspaceMembers(selectedWs.id);
    loadAdmin();
  }

  async function removeWorkspaceMember(userId) {
    if (!selectedWs) return;
    await window.verdictApi.adminSend("DELETE", `/admin/workspaces/${selectedWs.id}/members/${userId}`);
    loadWorkspaceMembers(selectedWs.id);
    loadAdmin();
  }

  async function addWorkspaceMember(userId) {
    if (!selectedWs) return;
    await window.verdictApi.adminSend("POST", `/admin/workspaces/${selectedWs.id}/members`, { user_id: userId, role: "reviewer" });
    loadWorkspaceMembers(selectedWs.id);
    loadAdmin();
  }

  const loadRag = React.useCallback(() => {
    setRagLoading(true);
    window.verdictApi.listRagDocuments()
      .then(docs => setRagDocs(Array.isArray(docs) ? docs : (docs.documents ?? [])))
      .catch(() => setRagDocs([]))
      .finally(() => setRagLoading(false));
  }, []);

  React.useEffect(() => { if (tab === "rag") loadRag(); }, [tab, loadRag]);

  async function handleRagUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setRagUploading(true);
    try {
      await window.verdictApi.uploadRagDocument(file, ragDocType);
      loadRag();
    } catch { /* ignore */ }
    setRagUploading(false);
    if (ragInputRef.current) ragInputRef.current.value = "";
  }

  async function deleteRagDoc(docId) {
    await window.verdictApi.deleteRagDocument(docId).catch(() => {});
    loadRag();
  }

  async function sendInvite(e) {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    try {
      const isOrgAdminInvite = inviteRole === "org_admin";
      const created = await window.verdictApi.adminSend("POST", "/admin/invites", {
        email: inviteEmail,
        org_role: isOrgAdminInvite ? "org_admin" : "member",
        workspace_id: isOrgAdminInvite ? null : (workspaces[0]?.id ?? null),
        workspace_role: isOrgAdminInvite ? "reviewer" : inviteRole,
      });
      const linkData = await window.verdictApi.adminGet(`/admin/invites/${created.invite_id}/link`);
      setInviteLink(`${window.location.origin}${linkData.link}`);
      setInviteEmail("");
      loadAdmin();
    } catch (err) {
      alert(err?.message || "Failed to create invite. Make sure you have admin permissions.");
    }
  }

  function copy() {
    if (!inviteLink) return;
    navigator.clipboard?.writeText(inviteLink).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const isOrgAdmin = window.verdictApi.currentUser()?.org_role === "org_admin";

  const tabs = [
    { key: "users",      label: "Users",          count: users.length },
    { key: "workspaces", label: "Workspaces",      count: workspaces.length },
    { key: "invites",    label: "Invites",          count: invites.length },
    { key: "rag",        label: "Knowledge Base",   count: ragDocs.length },
  ];

  const visibleTabs = isOrgAdmin ? tabs : tabs.filter(t => t.key === "users" || t.key === "workspaces");

  // ── shared styles ──
  const colLabel = { fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-3)" };
  const input = { padding: "9px 14px", border: "1px solid var(--border)", borderRadius: 7, fontSize: 13, color: "var(--text)", background: "var(--bg)", outline: "none", transition: "border-color 0.15s", fontFamily: "var(--font-sans)" };
  const ghostBtn = { fontSize: 12, color: "var(--text-3)", border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" };

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 80, animation: "fadeIn 0.35s ease both" }}>

      {/* Header */}
      <div style={{ marginBottom: 40 }}>
        <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 8 }}>Organisation · {window.verdictApi.currentUser()?.org_name ?? "Organisation"}</p>
        <h1 style={{ fontFamily: "var(--h-font)", fontSize: 42, fontWeight: 700, letterSpacing: "-0.025em", color: "var(--text)", lineHeight: 1 }}>Admin</h1>
      </div>

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border)", marginBottom: 40 }}>
        {visibleTabs.map(t => (
          <button key={t.key} onClick={() => { setTab(t.key); setSel(null); setWsCreateOpen(false); }}
            style={{ display: "flex", alignItems: "center", gap: 7, padding: "9px 14px", fontSize: 13, fontWeight: 500, color: tab === t.key ? "var(--text)" : "var(--text-2)", background: "none", border: "none", borderBottom: tab === t.key ? "2px solid var(--text)" : "2px solid transparent", marginBottom: -1, cursor: "pointer", transition: "all 0.15s" }}>
            {t.label}
            <span style={{ fontSize: 10.5, color: "var(--text-3)", background: "var(--border-light)", padding: "1px 6px", borderRadius: 8 }}>{adminLoading && tab !== "rag" ? "…" : t.count}</span>
          </button>
        ))}
      </div>

      {/* ── Users ── */}
      {tab === "users" && (
        <div style={{ animation: "fadeIn 0.2s ease" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 160px 90px 80px 80px", gap: "0 16px", padding: "0 0 11px", borderBottom: "1px solid var(--border)" }}>
            {["User", "Role / Dept", "Org Role", "Status", ""].map(h => <span key={h} style={colLabel}>{h}</span>)}
          </div>
          {users.map((u, i) => (
            <div key={u.id} style={{ display: "grid", gridTemplateColumns: "1fr 160px 90px 80px 80px", gap: "0 16px", padding: "14px 0", borderBottom: "1px solid var(--border-light)", alignItems: "center", animation: `fadeIn 0.25s ${i * 0.05}s both` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                <span style={{ width: 30, height: 30, borderRadius: "50%", background: u.color, color: "white", fontSize: 10, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{ini(u.name)}</span>
                <div style={{ minWidth: 0 }}>
                  <p style={{ fontSize: 13.5, fontWeight: 500, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.name}</p>
                  <p style={{ fontSize: 11, color: "var(--text-3)" }}>{u.email}</p>
                </div>
              </div>
              <div>
                <p style={{ fontSize: 12.5, color: "var(--text-2)" }}>{u.jobTitle}</p>
                <p style={{ fontSize: 11, color: "var(--text-3)" }}>{u.dept}</p>
              </div>
              <span style={{ fontSize: 11, fontWeight: 600, color: adminRoleColors[u.role] ?? "var(--text-2)", textTransform: "capitalize" }}>{u.role.replace("_", " ")}</span>
              <span style={{ fontSize: 12.5, color: u.locked ? "var(--risk-high)" : "var(--risk-low)" }}>{u.locked ? "Locked" : "Active"}</span>
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                {u.locked && <button onClick={async () => { await window.verdictApi.adminSend("POST", `/admin/users/${u.id}/unlock`).catch(() => {}); loadAdmin(); }} style={{ ...ghostBtn, fontSize: 11 }} onMouseEnter={e => e.currentTarget.style.color = "var(--risk-low)"} onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>Unlock</button>}
                {u.role !== "org_admin" && <button onClick={async () => { await window.verdictApi.adminSend("DELETE", `/admin/users/${u.id}`).catch(() => {}); loadAdmin(); }} style={{ ...ghostBtn, fontSize: 11 }} onMouseEnter={e => e.currentTarget.style.color = "var(--risk-high)"} onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>Remove</button>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Workspaces list ── */}
      {tab === "workspaces" && !selectedWs && !wsCreateOpen && (
        <div style={{ animation: "fadeIn 0.2s ease" }}>
          {isOrgAdmin && (
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 28 }}>
              <button onClick={openCreateWorkspace} style={{ padding: "9px 18px", borderRadius: 7, background: "var(--text)", color: "var(--bg)", fontSize: 13, fontWeight: 600, border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 7 }}>
                <IconPlus size={11} />Create workspace
              </button>
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 100px 28px", gap: "0 16px", padding: "0 0 11px", borderBottom: "1px solid var(--border)" }}>
            {["Workspace", "Members", ""].map(h => <span key={h} style={colLabel}>{h}</span>)}
          </div>
          {workspaces.map((ws, i) => (
            <div key={ws.id} onClick={() => openWorkspace(ws)}
              style={{ display: "grid", gridTemplateColumns: "1fr 100px 28px", gap: "0 16px", padding: "15px 10px", borderBottom: "1px solid var(--border-light)", cursor: "pointer", transition: "background 0.1s", alignItems: "center", animation: `fadeIn 0.25s ${i * 0.06}s both` }}
              onMouseEnter={e => e.currentTarget.style.background = "var(--hover-bg)"}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
              <div>
                <p style={{ fontSize: 13.5, fontWeight: 500, color: "var(--text)" }}>{ws.name}</p>
                {ws.desc && <p style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{ws.desc}</p>}
              </div>
              <span style={{ fontSize: 13, color: "var(--text-2)" }}>{ws.memberCount} member{ws.memberCount !== 1 ? "s" : ""}</span>
              <div style={{ color: "var(--text-3)", display: "flex", justifyContent: "flex-end" }}><IconArrowRight size={13} /></div>
            </div>
          ))}
        </div>
      )}

      {/* ── Create workspace ── */}
      {tab === "workspaces" && !selectedWs && wsCreateOpen && (
        <div style={{ animation: "fadeIn 0.2s ease", maxWidth: 760 }}>
          <button onClick={closeCreateWorkspace} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-2)", marginBottom: 28, border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" }}
            onMouseEnter={e => e.currentTarget.style.color = "var(--text)"}
            onMouseLeave={e => e.currentTarget.style.color = "var(--text-2)"}>
            <IconArrowLeft />All Workspaces
          </button>
          <h2 style={{ fontFamily: "var(--h-font)", fontSize: 28, fontWeight: 700, color: "var(--text)", marginBottom: 28 }}>Create workspace</h2>
          <form onSubmit={createWorkspace}>
            <label style={{ display: "block", ...colLabel, marginBottom: 8 }} htmlFor="new-workspace-name">Workspace name</label>
            <input id="new-workspace-name" value={newWsName} onChange={e => { setNewWsName(e.target.value); setWsError(null); }} placeholder="e.g. M&A Q2 2026"
              style={{ ...input, width: "100%", marginBottom: 18 }}
              onFocus={e => e.target.style.borderColor = "var(--text-2)"}
              onBlur={e => e.target.style.borderColor = "var(--border)"} />
            <label style={{ display: "block", ...colLabel, marginBottom: 8 }} htmlFor="new-workspace-desc">Description</label>
            <input id="new-workspace-desc" value={newWsDesc} onChange={e => setNewWsDesc(e.target.value)} placeholder="Optional"
              style={{ ...input, width: "100%", marginBottom: wsError ? 8 : 26 }}
              onFocus={e => e.target.style.borderColor = "var(--text-2)"}
              onBlur={e => e.target.style.borderColor = "var(--border)"} />
            {wsError && <p style={{ fontSize: 12, color: "var(--risk-high)", marginBottom: 22 }}>{wsError}</p>}
            <div style={{ display: "flex", gap: 10 }}>
              <button type="submit" disabled={wsCreating} style={{ padding: "9px 18px", borderRadius: 7, background: wsCreating ? "var(--border-light)" : "var(--text)", color: wsCreating ? "var(--text-3)" : "var(--bg)", fontSize: 13, fontWeight: 600, border: "none", cursor: wsCreating ? "not-allowed" : "pointer", display: "flex", alignItems: "center", gap: 7, opacity: wsCreating ? 0.7 : 1 }}>
                <IconPlus size={11} />{wsCreating ? "Creating..." : "Create"}
              </button>
              <button type="button" onClick={closeCreateWorkspace} style={{ padding: "9px 14px", borderRadius: 7, border: "1px solid var(--border)", background: "transparent", color: "var(--text-2)", fontSize: 13, cursor: "pointer" }}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      {/* ── Workspace detail ── */}
      {tab === "workspaces" && selectedWs && (
        <div style={{ animation: "fadeIn 0.2s ease" }}>
          <button onClick={() => setSel(null)} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-2)", marginBottom: 28, border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" }}
            onMouseEnter={e => e.currentTarget.style.color = "var(--text)"}
            onMouseLeave={e => e.currentTarget.style.color = "var(--text-2)"}>
            <IconArrowLeft />All Workspaces
          </button>
          <h2 style={{ fontFamily: "var(--h-font)", fontSize: 28, fontWeight: 700, color: "var(--text)", marginBottom: 32 }}>{selectedWs.name}</h2>
          {wsError && <p style={{ fontSize: 12, color: "var(--risk-high)", marginBottom: 18 }}>{wsError}</p>}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 140px 80px", gap: "0 16px", padding: "0 0 11px", borderBottom: "1px solid var(--border)" }}>
            {["Member", "Role", ""].map(h => <span key={h} style={colLabel}>{h}</span>)}
          </div>
          {wsMembersLoading && <p style={{ fontSize: 13, color: "var(--text-3)", padding: "20px 0" }}>Loading members…</p>}
          {!wsMembersLoading && wsMembers.map((u, i) => (
            <div key={u.id} style={{ display: "grid", gridTemplateColumns: "1fr 140px 80px", gap: "0 16px", padding: "13px 0", borderBottom: "1px solid var(--border-light)", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 26, height: 26, borderRadius: "50%", background: u.color, color: "white", fontSize: 9, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{ini(u.name)}</span>
                <div>
                  <p style={{ fontSize: 13.5, fontWeight: 500, color: "var(--text)" }}>{u.name}</p>
                  <p style={{ fontSize: 11, color: "var(--text-3)" }}>{u.jobTitle}</p>
                </div>
              </div>
              <select value={u.role} onChange={e => changeWorkspaceMemberRole(u.id, e.target.value)} style={{ ...input, padding: "5px 10px", fontSize: 12, cursor: "pointer" }}>
                <option value="reviewer">Reviewer</option>
                <option value="viewer">Viewer</option>
                <option value="workspace_admin">Workspace Admin</option>
              </select>
              <div style={{ textAlign: "right" }}>
                <button onClick={() => removeWorkspaceMember(u.id)} style={{ ...ghostBtn, fontSize: 11 }} onMouseEnter={e => e.currentTarget.style.color = "var(--risk-high)"} onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>Remove</button>
              </div>
            </div>
          ))}
          <div style={{ marginTop: 24 }}>
            <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 12 }}>Add Member</p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {users.filter(u => !wsMembers.some(m => m.id === u.id)).map(u => (
                <button key={u.id} onClick={() => addWorkspaceMember(u.id)} style={{ display: "flex", alignItems: "center", gap: 7, padding: "5px 12px", borderRadius: 6, border: "1px solid var(--border)", fontSize: 12, color: "var(--text-2)", background: "none", cursor: "pointer", transition: "all 0.12s" }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--text-3)"; e.currentTarget.style.color = "var(--text)"; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--text-2)"; }}>
                  <span style={{ width: 18, height: 18, borderRadius: "50%", background: u.color, color: "white", fontSize: 8, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{ini(u.name)}</span>
                  {u.name.split(" ")[0]}
                  <IconPlus size={10} />
                </button>
              ))}
              {!wsMembersLoading && users.filter(u => !wsMembers.some(m => m.id === u.id)).length === 0 && (
                <p style={{ fontSize: 12, color: "var(--text-3)" }}>All organisation members are already in this workspace.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Invites ── */}
      {tab === "invites" && (
        <div style={{ animation: "fadeIn 0.2s ease" }}>
          <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 24, marginBottom: 40, background: "var(--surface)" }}>
            <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 20 }}>Invite Someone</p>
            <form onSubmit={sendInvite} style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: inviteLink ? 16 : 0 }}>
              <input type="email" required value={inviteEmail} onChange={e => setInviteEmail(e.target.value)} placeholder="colleague@firm.com" style={{ ...input, flex: 1, minWidth: 200 }}
                onFocus={e => e.target.style.borderColor = "var(--text-2)"}
                onBlur={e => e.target.style.borderColor = "var(--border)"} />
              <select value={inviteRole} onChange={e => setInviteRole(e.target.value)} style={{ ...input, cursor: "pointer", paddingRight: 14 }}>
                <option value="reviewer">Reviewer</option>
                <option value="viewer">Viewer</option>
                <option value="workspace_admin">Workspace Admin</option>
                <option value="org_admin">Org Admin</option>
              </select>
              <button type="submit" style={{ padding: "9px 18px", borderRadius: 7, background: "var(--text)", color: "var(--bg)", fontSize: 13, fontWeight: 600, border: "none", cursor: "pointer" }}>Generate Link</button>
            </form>
            {inviteLink && (
              <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", background: "rgba(61,139,94,0.06)", border: "1px solid rgba(61,139,94,0.2)", borderRadius: 7, animation: "fadeIn 0.2s ease" }}>
                <code style={{ flex: 1, fontSize: 11, color: "var(--text-2)", wordBreak: "break-all", fontFamily: "monospace" }}>{inviteLink}</code>
                <button onClick={copy} style={{ flexShrink: 0, fontSize: 12, fontWeight: 600, color: copied ? "var(--risk-low)" : "var(--accent)", border: "none", background: "none", cursor: "pointer" }}>{copied ? "Copied ✓" : "Copy"}</button>
              </div>
            )}
          </div>

          {invites.length > 0 ? (
            <div>
              <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 16 }}>Pending ({invites.length})</p>
              {invites.map((inv, i) => (
                <div key={inv.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 0", borderBottom: "1px solid var(--border-light)", animation: `fadeIn 0.25s ${i * 0.06}s both` }}>
                  <div>
                    <p style={{ fontSize: 13.5, fontWeight: 500, color: "var(--text)" }}>{inv.email}</p>
                    <p style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{inv.workspace} · {inv.role} · invited by {inv.invitedBy}</p>
                  </div>
                  <button onClick={async () => { await window.verdictApi.adminSend("DELETE", `/admin/invites/${inv.id}`).catch(() => {}); setInvites(p => p.filter(x => x.id !== inv.id)); }} style={{ ...ghostBtn }}
                    onMouseEnter={e => e.currentTarget.style.color = "var(--risk-high)"}
                    onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>Revoke</button>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ fontSize: 13, color: "var(--text-3)", textAlign: "center", padding: "40px 0" }}>No pending invites.</p>
          )}
        </div>
      )}
      {/* ── Knowledge Base (RAG) ── */}
      {tab === "rag" && (
        <div style={{ animation: "fadeIn 0.2s ease" }}>
          <div style={{ marginBottom: 32 }}>
            <p style={{ fontSize: 13, color: "var(--text-2)", marginBottom: 20, lineHeight: 1.6 }}>
              Upload reference documents (PDFs, text files) to the knowledge base. The AI uses these during contract analysis to benchmark against your firm's standards.
            </p>
            <input ref={ragInputRef} type="file" accept=".pdf,.txt,.docx" style={{ display: "none" }} onChange={handleRagUpload} />
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <select value={ragDocType} onChange={e => setRagDocType(e.target.value)} style={{ ...input, cursor: "pointer" }}>
                <option value="policy">Policy</option>
                <option value="template">Template</option>
                <option value="precedent">Precedent</option>
                <option value="guidance">Guidance</option>
              </select>
              <button onClick={() => ragInputRef.current?.click()} disabled={ragUploading}
                style={{ padding: "9px 18px", borderRadius: 7, background: "var(--text)", color: "var(--bg)", fontSize: 13, fontWeight: 600, border: "none", cursor: ragUploading ? "default" : "pointer", opacity: ragUploading ? 0.6 : 1, display: "flex", alignItems: "center", gap: 7 }}>
                <IconPlus size={11} />{ragUploading ? "Uploading…" : "Upload Document"}
              </button>
            </div>
          </div>

          {ragLoading ? (
            <p style={{ fontSize: 13, color: "var(--text-3)", padding: "24px 0" }}>Loading…</p>
          ) : ragDocs.length === 0 ? (
            <div style={{ textAlign: "center", padding: "60px 0", color: "var(--text-3)" }}>
              <p style={{ fontSize: 14 }}>No documents in the knowledge base yet.</p>
              <p style={{ fontSize: 12, marginTop: 8 }}>Upload PDFs or text files to get started.</p>
            </div>
          ) : (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 120px 100px 60px", gap: "0 16px", padding: "0 0 11px", borderBottom: "1px solid var(--border)" }}>
                {["Document", "Type", "Status", ""].map(h => <span key={h} style={colLabel}>{h}</span>)}
              </div>
              {ragDocs.map((doc, i) => {
                const name = doc.filename ?? doc.file_name ?? doc.name ?? "Document";
                const status = doc.status ?? doc.ingestion_status ?? "ready";
                const docId = doc.document_id ?? doc.id;
                const ext = name.split(".").pop()?.toUpperCase() ?? "—";
                const statusColor = status === "ready" || status === "completed" ? "var(--risk-low)" : status === "processing" ? "var(--accent)" : status === "failed" ? "var(--risk-high)" : "var(--text-3)";
                return (
                  <div key={docId} style={{ display: "grid", gridTemplateColumns: "1fr 120px 100px 60px", gap: "0 16px", padding: "14px 0", borderBottom: "1px solid var(--border-light)", alignItems: "center", animation: `fadeIn 0.25s ${i * 0.05}s both` }}>
                    <p style={{ fontSize: 13.5, fontWeight: 500, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</p>
                    <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text-3)", background: "var(--border-light)", padding: "3px 8px", borderRadius: 4, display: "inline-block" }}>{ext}</span>
                    <span style={{ fontSize: 12, color: statusColor, fontWeight: 500, textTransform: "capitalize" }}>{status.replace(/_/g, " ")}</span>
                    <div style={{ textAlign: "right" }}>
                      <button onClick={() => deleteRagDoc(docId)} style={{ ...ghostBtn, fontSize: 11 }}
                        onMouseEnter={e => e.currentTarget.style.color = "var(--risk-high)"}
                        onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>Remove</button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { AdminScreen });
