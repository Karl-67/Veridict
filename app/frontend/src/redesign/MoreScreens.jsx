
// ── Shared data for these screens ─────────────────────────────────────────────

const MOCK_HISTORY = (() => {
  const now = Date.now();
  const ha = h => new Date(now - h * 3600000).toISOString();
  const da = d => new Date(now - d * 86400000).toISOString();
  return [
    { runId: "r4", contractId: 2, name: "Non-Disclosure Agreement — TechVentures LLC", label: "v1", state: "awaiting_human_review", risk: "medium", action: null,       ws: "Legal",       at: ha(2)  },
    { runId: "r6", contractId: 4, name: "Vendor SLA — CloudOps Provider",              label: "v1", state: "processing",            risk: null,     action: null,       ws: "Procurement", at: ha(5)  },
    { runId: "r3", contractId: 1, name: "Master Services Agreement — Acme Corp",        label: "v3", state: "finalized",             risk: "high",   action: null,       ws: "Legal",       at: da(1)  },
    { runId: "r5", contractId: 3, name: "Employment Agreement — Senior Engineer",       label: "v2", state: "finalized",             risk: "low",    action: null,       ws: "HR",          at: da(2)  },
    { runId: "r2", contractId: 1, name: "Master Services Agreement — Acme Corp",        label: "v2", state: "finalized",             risk: "medium", action: "approved", ws: "Legal",       at: da(3)  },
    { runId: "r7", contractId: 5, name: "Software License Agreement — DataSystems",     label: "v4", state: "finalized",             risk: "medium", action: null,       ws: "Legal",       at: da(3)  },
    { runId: "r8", contractId: 6, name: "Joint Venture Agreement — Meridian Partners",  label: "v2", state: "finalized",             risk: "low",    action: null,       ws: "Legal",       at: da(4)  },
    { runId: "r1", contractId: 1, name: "Master Services Agreement — Acme Corp",        label: "v1", state: "finalized",             risk: "high",   action: "rejected", ws: "Legal",       at: da(6)  },
    { runId: "r9", contractId: 3, name: "Employment Agreement — Senior Engineer",       label: "v1", state: "finalized",             risk: "low",    action: null,       ws: "HR",          at: da(9)  },
  ];
})();

const MOCK_USER_PROFILE = {
  displayName: "Sarah Johnson", email: "sarah@verdictai.io",
  jobTitle: "Senior Associate",  department: "Corporate M&A",
  orgName: "Verdict Legal LLP",  orgRole: "org_admin", avatarColor: "#C8973E",
};

const AVATAR_COLORS = ["#C8973E","#6366F1","#EC4899","#10B981","#3B82F6","#EF4444","#F59E0B","#14B8A6"];

const MOCK_PROFILE_WORKSPACES = [
  { id: "ws1", name: "Legal",       role: "org_admin", memberCount: 4, desc: "Primary contract review" },
  { id: "ws2", name: "HR",          role: "reviewer",  memberCount: 2, desc: "Employment agreements" },
  { id: "ws3", name: "Procurement", role: "viewer",    memberCount: 1, desc: "Vendor contracts" },
];

// ── History helpers ───────────────────────────────────────────────────────────

function historyGroup(iso) {
  const d       = new Date(iso);
  const now     = new Date();
  const today   = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yest    = new Date(today); yest.setDate(today.getDate() - 1);
  const weekAgo = new Date(today); weekAgo.setDate(today.getDate() - 7);
  const day     = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  if (day >= today)   return "Today";
  if (day >= yest)    return "Yesterday";
  if (day >= weekAgo) return "This Week";
  return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

function historyDot(entry) {
  if (entry.action === "approved")                      return { bg: "var(--risk-low)",    pulse: false };
  if (entry.action === "rejected")                      return { bg: "var(--risk-high)",   pulse: false };
  if (entry.state === "awaiting_human_review")          return { bg: "var(--accent)",      pulse: false };
  if (entry.state === "processing")                     return { bg: "var(--accent)",      pulse: true  };
  if (entry.state === "failed" || entry.state === "blocked") return { bg: "var(--risk-high)", pulse: false };
  if (entry.state === "finalized")                      return { bg: "var(--risk-low)",    pulse: false };
  return { bg: "var(--text-3)", pulse: false };
}

function historyStatusText(entry) {
  if (entry.action === "approved") return { text: "Approved",   color: "var(--risk-low)"  };
  if (entry.action === "rejected") return { text: "Rejected",   color: "var(--risk-high)" };
  return stateLabel(entry.state);
}

// ── History Screen ────────────────────────────────────────────────────────────

function HistoryScreen({ navigate }) {
  const [filter, setFilter] = React.useState("all");
  const [entries, setEntries] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  React.useEffect(() => {
    let active = true;
    window.verdictApi.listHistory()
      .then(rows => {
        if (!active) return;
        setEntries(rows.map(e => ({
          runId: e.run_id,
          contractId: e.contract_id,
          name: e.contract_name,
          label: e.version_label,
          state: e.state,
          risk: e.risk_level,
          action: e.human_action,
          ws: e.workspace_name ?? "Workspace",
          at: e.updated_at,
        })));
      })
      .catch(() => { if (active) setEntries([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const filterDefs = [
    { key: "all",                   label: "All" },
    { key: "awaiting_human_review", label: "Awaiting Review" },
    { key: "finalized",             label: "Finalized" },
    { key: "processing",            label: "Processing" },
    { key: "failed",                label: "Failed" },
  ];

  const filtered = filter === "all" ? entries : entries.filter(e => e.state === filter);
  const approved = entries.filter(e => e.action === "approved").length;
  const rejected = entries.filter(e => e.action === "rejected").length;

  // Group entries by date
  const groups = [];
  const seen   = new Map();
  for (const e of filtered) {
    const g = historyGroup(e.at);
    if (!seen.has(g)) { seen.set(g, groups.length); groups.push({ label: g, entries: [] }); }
    groups[seen.get(g)].entries.push(e);
  }

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 80, animation: "fadeIn 0.35s ease both" }}>

      {/* Page header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 40 }}>
        <div>
          <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 8 }}>Activity Log</p>
          <h1 style={{ fontFamily: "var(--h-font)", fontSize: 42, fontWeight: 700, letterSpacing: "-0.025em", color: "var(--text)", lineHeight: 1 }}>History</h1>
        </div>
        <div style={{ display: "flex", gap: 40, alignItems: "flex-end" }}>
          {[
            { label: "Total Runs", value: entries.length, color: null },
            { label: "Approved",   value: approved,            color: approved > 0 ? "var(--risk-low)"  : null },
            { label: "Rejected",   value: rejected,            color: rejected > 0 ? "var(--risk-high)" : null },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ textAlign: "right" }}>
              <p style={{ fontFamily: "var(--font-serif)", fontSize: 30, fontWeight: 700, lineHeight: 1, color: color ?? "var(--text)" }}>{value}</p>
              <p style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4 }}>{label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Filter tabs */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border)" }}>
        {filterDefs.map(f => {
          const count = f.key === "all" ? entries.length : entries.filter(e => e.state === f.key).length;
          if (f.key !== "all" && count === 0) return null;
          return (
            <button key={f.key} onClick={() => setFilter(f.key)} style={{ display: "flex", alignItems: "center", gap: 6, padding: "9px 14px", fontSize: 13, fontWeight: 500, color: filter === f.key ? "var(--text)" : "var(--text-2)", background: "none", border: "none", borderBottom: filter === f.key ? "2px solid var(--text)" : "2px solid transparent", marginBottom: -1, cursor: "pointer", transition: "all 0.15s" }}>
              {f.label}
              <span style={{ fontSize: 10.5, color: "var(--text-3)" }}>{loading ? "…" : count}</span>
            </button>
          );
        })}
      </div>

      {/* Timeline */}
      {groups.length === 0 ? (
        <div style={{ textAlign: "center", padding: "80px 0", color: "var(--text-3)" }}>
          <p style={{ fontSize: 14 }}>No entries match this filter.</p>
        </div>
      ) : groups.map(group => (
        <div key={group.label}>
          {/* Date divider */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "28px 0 14px" }}>
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.14em", color: "var(--text-3)", flexShrink: 0 }}>{group.label}</span>
            <div style={{ flex: 1, height: 1, background: "var(--border-light)" }} />
          </div>

          {group.entries.map((entry, i) => {
            const dot    = historyDot(entry);
            const status = historyStatusText(entry);
            return (
              <div key={entry.runId}
                onClick={() => navigate("contract_detail", entry.contractId)}
                style={{ display: "grid", gridTemplateColumns: "18px 1fr 148px 96px 80px 28px", gap: "0 16px", padding: "13px 10px", borderBottom: "1px solid var(--border-light)", cursor: "pointer", transition: "background 0.1s", alignItems: "center", animation: `fadeIn 0.25s ${i * 0.04}s both` }}
                onMouseEnter={e => e.currentTarget.style.background = "var(--hover-bg)"}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                <div style={{ display: "flex", justifyContent: "center" }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot.bg, display: "block", flexShrink: 0 }} className={dot.pulse ? "pulse" : ""} />
                </div>
                <div style={{ minWidth: 0 }}>
                  <p style={{ fontSize: 13.5, fontWeight: 500, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{entry.name}</p>
                  <p style={{ fontSize: 11, color: "var(--text-3)", marginTop: 1 }}>
                    {entry.ws} · <span style={{ fontFamily: "monospace", fontWeight: 600 }}>{entry.label}</span>
                  </p>
                </div>
                <span style={{ fontSize: 13, color: status.color }}>{status.text}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  {entry.risk
                    ? <><span style={{ width: 7, height: 7, borderRadius: 1.5, background: riskColor(entry.risk), flexShrink: 0 }} /><span style={{ fontSize: 12.5, color: riskColor(entry.risk) }}>{riskLabel(entry.risk)}</span></>
                    : <span style={{ color: "var(--text-3)" }}>—</span>}
                </div>
                <span style={{ fontSize: 12, color: "var(--text-3)" }}>{timeAgo(entry.at)}</span>
                <div style={{ color: "var(--text-3)", display: "flex", justifyContent: "flex-end" }}><IconArrowRight size={13} /></div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// ── Profile Screen ────────────────────────────────────────────────────────────

function ProfileScreen() {
  const current = window.verdictApi.currentUser();
  const [user, setUser]           = React.useState({
    displayName: current?.display_name ?? MOCK_USER_PROFILE.displayName,
    email: current?.email ?? MOCK_USER_PROFILE.email,
    jobTitle: current?.job_title ?? "",
    department: current?.department ?? "",
    orgName: current?.org_name ?? MOCK_USER_PROFILE.orgName,
    orgRole: current?.org_role ?? "member",
    avatarColor: current?.avatar_color ?? MOCK_USER_PROFILE.avatarColor,
  });
  const [avatarColor, setColor]   = React.useState(user.avatarColor);
  const [workspaces, setWorkspaces] = React.useState([]);
  const [section, setSection]     = React.useState("info");
  const [savedState, setSaved]    = React.useState(null);
  const [pwFields, setPwFields]   = React.useState({ current: "", next: "", confirm: "" });

  function initials(n) { return n.split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase(); }

  function save() {
    setSaved("saving");
    window.verdictApi.updateProfile({
      display_name: user.displayName,
      job_title: user.jobTitle,
      department: user.department,
      avatar_color: avatarColor,
    }).then(() => {
      setSaved("saved");
      setTimeout(() => setSaved(null), 2200);
    }).catch(() => setSaved(null));
  }

  function savePassword() {
    if (!pwFields.current || !pwFields.next) return;
    if (pwFields.next !== pwFields.confirm) { setSaved("mismatch"); setTimeout(() => setSaved(null), 2200); return; }
    setSaved("saving");
    window.verdictApi.updateProfile({
      current_password: pwFields.current,
      new_password: pwFields.next,
    }).then(() => {
      setSaved("saved");
      setPwFields({ current: "", next: "", confirm: "" });
      setTimeout(() => setSaved(null), 2200);
    }).catch(() => setSaved(null));
  }

  React.useEffect(() => {
    window.verdictApi.listWorkspaces().then(setWorkspaces).catch(() => setWorkspaces([]));
  }, []);

  const navItems = [
    { key: "info",       label: "Personal Info" },
    { key: "password",   label: "Security" },
    { key: "workspaces", label: "Workspaces" },
  ];

  const inputStyle = (readOnly = false) => ({
    width: "100%", padding: "10px 14px", border: "1px solid var(--border)", borderRadius: 7,
    fontSize: 13.5, color: readOnly ? "var(--text-2)" : "var(--text)",
    background: readOnly ? "transparent" : "var(--surface)",
    outline: "none", transition: "border-color 0.15s",
    cursor: readOnly ? "default" : "text",
  });

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 80, animation: "fadeIn 0.35s ease both", display: "grid", gridTemplateColumns: "200px 1fr", gap: 72, maxWidth: 860 }}>

      {/* Left sidebar */}
      <div>
        <div style={{ marginBottom: 36 }}>
          <div style={{ width: 60, height: 60, borderRadius: "50%", background: avatarColor, display: "flex", alignItems: "center", justifyContent: "center", color: "white", fontSize: 20, fontWeight: 700, marginBottom: 14, transition: "background 0.3s" }}>
            {initials(user.displayName)}
          </div>
          <p style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", lineHeight: 1.3 }}>{user.displayName}</p>
          <p style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>{user.email}</p>
          <span style={{ display: "inline-block", marginTop: 10, fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.09em", color: "var(--accent)", background: "rgba(200,151,62,0.12)", padding: "3px 8px", borderRadius: 4 }}>
            {user.orgRole === "org_admin" ? "Admin" : "Member"}
          </span>
        </div>

        <nav style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          {navItems.map(s => (
            <button key={s.key} onClick={() => setSection(s.key)} style={{ textAlign: "left", padding: "8px 10px", borderRadius: 6, fontSize: 13, fontWeight: section === s.key ? 600 : 400, color: section === s.key ? "var(--text)" : "var(--text-2)", background: section === s.key ? "var(--hover-bg)" : "none", border: "none", cursor: "pointer", transition: "all 0.12s" }}>
              {s.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Right content */}
      <div>

        {/* ── Personal Info ── */}
        {section === "info" && (
          <div style={{ animation: "fadeIn 0.2s ease" }}>
            <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 28 }}>Personal Info</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 20, marginBottom: 36 }}>
              {[
                { label: "Full Name",   key: "displayName", placeholder: "Your full name",        readOnly: false },
                { label: "Email",       key: "email",       placeholder: "your@email.com",        readOnly: true  },
                { label: "Job Title",   key: "jobTitle",    placeholder: "e.g. Senior Associate", readOnly: false },
                { label: "Department",  key: "department",  placeholder: "e.g. Corporate M&A",   readOnly: false },
              ].map(({ label, key, placeholder, readOnly }) => (
                <div key={key}>
                  <label style={{ display: "block", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 8 }}>{label}</label>
                  <input value={user[key] ?? ""} onChange={e => !readOnly && setUser(p => ({ ...p, [key]: e.target.value }))} placeholder={placeholder} readOnly={readOnly}
                    style={inputStyle(readOnly)}
                    onFocus={e => { if (!readOnly) e.target.style.borderColor = "var(--text-2)"; }}
                    onBlur={e => e.target.style.borderColor = "var(--border)"} />
                </div>
              ))}
            </div>

            <div style={{ marginBottom: 36 }}>
              <label style={{ display: "block", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 12 }}>Avatar Color</label>
              <div style={{ display: "flex", gap: 8 }}>
                {AVATAR_COLORS.map(c => (
                  <button key={c} onClick={() => setColor(c)} style={{ width: 26, height: 26, borderRadius: "50%", background: c, border: "none", cursor: "pointer", outline: avatarColor === c ? `3px solid ${c}` : "none", outlineOffset: 2.5, transform: avatarColor === c ? "scale(1.18)" : "scale(1)", transition: "all 0.15s" }} />
                ))}
              </div>
            </div>

            <SaveButton state={savedState} onSave={save} />
          </div>
        )}

        {/* ── Security ── */}
        {section === "password" && (
          <div style={{ animation: "fadeIn 0.2s ease" }}>
            <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 28 }}>Security</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 400, marginBottom: 32 }}>
              {[
                { label: "Current password",     key: "current" },
                { label: "New password",          key: "next"    },
                { label: "Confirm new password",  key: "confirm" },
              ].map(({ label, key }) => (
                <div key={key}>
                  <label style={{ display: "block", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 8 }}>{label}</label>
                  <input type="password" value={pwFields[key]} onChange={e => setPwFields(p => ({ ...p, [key]: e.target.value }))} placeholder="••••••••" style={inputStyle()}
                    onFocus={e => e.target.style.borderColor = "var(--text-2)"}
                    onBlur={e => e.target.style.borderColor = "var(--border)"} />
                </div>
              ))}
            </div>
            {savedState === "mismatch" && <p style={{ fontSize: 12, color: "var(--risk-high)", marginBottom: 12 }}>Passwords don't match.</p>}
            <SaveButton state={savedState === "mismatch" ? null : savedState} onSave={savePassword} label="Update Password" />
          </div>
        )}

        {/* ── Workspaces ── */}
        {section === "workspaces" && (
          <div style={{ animation: "fadeIn 0.2s ease" }}>
            <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 28 }}>Workspaces</p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 100px 80px", gap: "0 16px", padding: "0 0 11px", borderBottom: "1px solid var(--border)" }}>
              {["Workspace", "Role", "Members"].map(h => <span key={h} style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-3)" }}>{h}</span>)}
            </div>
            {workspaces.map((raw, i) => {
              const ws = {
                id: raw.workspace_id ?? raw.id,
                name: raw.name,
                role: raw.role ?? "member",
                memberCount: raw.member_count ?? raw.memberCount ?? "-",
                desc: raw.description ?? raw.desc,
              };
              return <div key={ws.id} style={{ display: "grid", gridTemplateColumns: "1fr 100px 80px", gap: "0 16px", padding: "15px 0", borderBottom: "1px solid var(--border-light)", alignItems: "center", animation: `fadeIn 0.3s ${i * 0.07}s both` }}>
                <div>
                  <p style={{ fontSize: 13.5, fontWeight: 500, color: "var(--text)" }}>{ws.name}</p>
                  {ws.desc && <p style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{ws.desc}</p>}
                </div>
                <span style={{ fontSize: 12, fontWeight: 600, color: ws.role === "org_admin" ? "var(--accent)" : ws.role === "reviewer" ? "var(--risk-low)" : "var(--text-2)", textTransform: "capitalize" }}>{ws.role.replace("_", " ")}</span>
                <span style={{ fontSize: 13, color: "var(--text-2)" }}>{ws.memberCount}</span>
              </div>;
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Shared save button ────────────────────────────────────────────────────────

function SaveButton({ state, onSave, label = "Save Changes" }) {
  return (
    <button onClick={onSave} style={{ padding: "10px 24px", borderRadius: 8, background: state === "saved" ? "var(--risk-low)" : "var(--text)", color: "var(--bg)", fontSize: 13.5, fontWeight: 600, border: "none", cursor: "pointer", transition: "all 0.25s" }}>
      {state === "saving" ? "Saving…" : state === "saved" ? "Saved ✓" : label}
    </button>
  );
}

Object.assign(window, { HistoryScreen, ProfileScreen, SaveButton, MOCK_HISTORY, MOCK_USER_PROFILE, AVATAR_COLORS, MOCK_PROFILE_WORKSPACES });
