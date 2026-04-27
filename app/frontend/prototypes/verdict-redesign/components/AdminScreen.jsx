
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
  const [users, setUsers]     = React.useState(MOCK_ADMIN_USERS);
  const [selectedWs, setSel]  = React.useState(null);
  const [invites, setInvites] = React.useState(MOCK_ADMIN_INVITES_INIT);
  const [inviteEmail, setInviteEmail] = React.useState("");
  const [inviteRole, setInviteRole]   = React.useState("reviewer");
  const [inviteLink, setInviteLink]   = React.useState(null);
  const [copied, setCopied]           = React.useState(false);
  const [newWsName, setNewWsName]     = React.useState("");

  function ini(n) { return n.split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase(); }

  function sendInvite(e) {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    const link = `https://app.verdict.ai/invite?token=mock_${Date.now().toString(36)}`;
    setInviteLink(link);
    setInvites(prev => [...prev, { id: `inv_${Date.now()}`, email: inviteEmail, workspace: "Legal", role: inviteRole.replace("_", " "), invitedBy: "Sarah Johnson" }]);
    setInviteEmail("");
  }

  function copy() {
    if (!inviteLink) return;
    navigator.clipboard?.writeText(inviteLink).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const tabs = [
    { key: "users",      label: "Users",      count: users.length },
    { key: "workspaces", label: "Workspaces", count: MOCK_ADMIN_WS.length },
    { key: "invites",    label: "Invites",    count: invites.length },
  ];

  // ── shared styles ──
  const colLabel = { fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-3)" };
  const input = { padding: "9px 14px", border: "1px solid var(--border)", borderRadius: 7, fontSize: 13, color: "var(--text)", background: "var(--bg)", outline: "none", transition: "border-color 0.15s", fontFamily: "var(--font-sans)" };
  const ghostBtn = { fontSize: 12, color: "var(--text-3)", border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" };

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 80, animation: "fadeIn 0.35s ease both" }}>

      {/* Header */}
      <div style={{ marginBottom: 40 }}>
        <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 8 }}>Organisation · Verdict Legal LLP</p>
        <h1 style={{ fontFamily: "var(--h-font)", fontSize: 42, fontWeight: 700, letterSpacing: "-0.025em", color: "var(--text)", lineHeight: 1 }}>Admin</h1>
      </div>

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border)", marginBottom: 40 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => { setTab(t.key); setSel(null); }}
            style={{ display: "flex", alignItems: "center", gap: 7, padding: "9px 14px", fontSize: 13, fontWeight: 500, color: tab === t.key ? "var(--text)" : "var(--text-2)", background: "none", border: "none", borderBottom: tab === t.key ? "2px solid var(--text)" : "2px solid transparent", marginBottom: -1, cursor: "pointer", transition: "all 0.15s" }}>
            {t.label}
            <span style={{ fontSize: 10.5, color: "var(--text-3)", background: "var(--border-light)", padding: "1px 6px", borderRadius: 8 }}>{t.count}</span>
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
                {u.locked && <button onClick={() => setUsers(p => p.map(x => x.id === u.id ? { ...x, locked: false } : x))} style={{ ...ghostBtn, fontSize: 11 }} onMouseEnter={e => e.currentTarget.style.color = "var(--risk-low)"} onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>Unlock</button>}
                {u.id !== "u1" && <button onClick={() => setUsers(p => p.filter(x => x.id !== u.id))} style={{ ...ghostBtn, fontSize: 11 }} onMouseEnter={e => e.currentTarget.style.color = "var(--risk-high)"} onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>Remove</button>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Workspaces list ── */}
      {tab === "workspaces" && !selectedWs && (
        <div style={{ animation: "fadeIn 0.2s ease" }}>
          <div style={{ display: "flex", gap: 10, marginBottom: 32 }}>
            <input value={newWsName} onChange={e => setNewWsName(e.target.value)} placeholder="New workspace name…"
              style={{ ...input, flex: 1 }}
              onFocus={e => e.target.style.borderColor = "var(--text-2)"}
              onBlur={e => e.target.style.borderColor = "var(--border)"} />
            <button style={{ padding: "9px 18px", borderRadius: 7, background: "var(--text)", color: "var(--bg)", fontSize: 13, fontWeight: 600, border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 7 }}>
              <IconPlus size={11} />Create
            </button>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 100px 28px", gap: "0 16px", padding: "0 0 11px", borderBottom: "1px solid var(--border)" }}>
            {["Workspace", "Members", ""].map(h => <span key={h} style={colLabel}>{h}</span>)}
          </div>
          {MOCK_ADMIN_WS.map((ws, i) => (
            <div key={ws.id} onClick={() => setSel(ws)}
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

      {/* ── Workspace detail ── */}
      {tab === "workspaces" && selectedWs && (
        <div style={{ animation: "fadeIn 0.2s ease" }}>
          <button onClick={() => setSel(null)} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-2)", marginBottom: 28, border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" }}
            onMouseEnter={e => e.currentTarget.style.color = "var(--text)"}
            onMouseLeave={e => e.currentTarget.style.color = "var(--text-2)"}>
            <IconArrowLeft />All Workspaces
          </button>
          <h2 style={{ fontFamily: "var(--h-font)", fontSize: 28, fontWeight: 700, color: "var(--text)", marginBottom: 32 }}>{selectedWs.name}</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 140px 80px", gap: "0 16px", padding: "0 0 11px", borderBottom: "1px solid var(--border)" }}>
            {["Member", "Role", ""].map(h => <span key={h} style={colLabel}>{h}</span>)}
          </div>
          {users.slice(0, selectedWs.memberCount).map((u, i) => (
            <div key={u.id} style={{ display: "grid", gridTemplateColumns: "1fr 140px 80px", gap: "0 16px", padding: "13px 0", borderBottom: "1px solid var(--border-light)", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 26, height: 26, borderRadius: "50%", background: u.color, color: "white", fontSize: 9, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{ini(u.name)}</span>
                <div>
                  <p style={{ fontSize: 13.5, fontWeight: 500, color: "var(--text)" }}>{u.name}</p>
                  <p style={{ fontSize: 11, color: "var(--text-3)" }}>{u.jobTitle}</p>
                </div>
              </div>
              <select style={{ ...input, padding: "5px 10px", fontSize: 12, cursor: "pointer" }}>
                {["Reviewer", "Viewer", "Workspace Admin"].map(r => <option key={r}>{r}</option>)}
              </select>
              <div style={{ textAlign: "right" }}>
                <button style={{ ...ghostBtn, fontSize: 11 }} onMouseEnter={e => e.currentTarget.style.color = "var(--risk-high)"} onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>Remove</button>
              </div>
            </div>
          ))}
          <div style={{ marginTop: 24 }}>
            <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 12 }}>Add Member</p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {users.slice(selectedWs.memberCount).map(u => (
                <button key={u.id} style={{ display: "flex", alignItems: "center", gap: 7, padding: "5px 12px", borderRadius: 6, border: "1px solid var(--border)", fontSize: 12, color: "var(--text-2)", background: "none", cursor: "pointer", transition: "all 0.12s" }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--text-3)"; e.currentTarget.style.color = "var(--text)"; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--text-2)"; }}>
                  <span style={{ width: 18, height: 18, borderRadius: "50%", background: u.color, color: "white", fontSize: 8, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{ini(u.name)}</span>
                  {u.name.split(" ")[0]}
                  <IconPlus size={10} />
                </button>
              ))}
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
                  <button onClick={() => setInvites(p => p.filter(x => x.id !== inv.id))} style={{ ...ghostBtn }}
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
    </div>
  );
}

Object.assign(window, { AdminScreen });
