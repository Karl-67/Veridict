
// ── Shared data & utilities ───────────────────────────────────────────────────

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light",
  "density": "comfortable",
  "accent": "gold",
  "serifHeaders": true
}/*EDITMODE-END*/;

const MOCK_CONTRACTS = [
  { id: 1, name: "Master Services Agreement — Acme Corp", versionCount: 3, latestLabel: "v3", latestRunState: "finalized", latestRisk: "high", updatedAt: "2026-04-25T14:32:00Z", workspace: "Legal" },
  { id: 2, name: "Non-Disclosure Agreement — TechVentures LLC", versionCount: 1, latestLabel: "v1", latestRunState: "awaiting_human_review", latestRisk: "medium", updatedAt: "2026-04-26T09:15:00Z", workspace: "Legal" },
  { id: 3, name: "Employment Agreement — Senior Engineer", versionCount: 2, latestLabel: "v2", latestRunState: "finalized", latestRisk: "low", updatedAt: "2026-04-24T11:45:00Z", workspace: "HR" },
  { id: 4, name: "Vendor SLA — CloudOps Provider", versionCount: 1, latestLabel: "v1", latestRunState: "processing", latestRisk: null, updatedAt: "2026-04-26T10:30:00Z", workspace: "Procurement" },
  { id: 5, name: "Software License Agreement — DataSystems", versionCount: 4, latestLabel: "v4", latestRunState: "finalized", latestRisk: "medium", updatedAt: "2026-04-23T16:20:00Z", workspace: "Legal" },
  { id: 6, name: "Joint Venture Agreement — Meridian Partners", versionCount: 2, latestLabel: "v2b", latestRunState: "finalized", latestRisk: "low", updatedAt: "2026-04-22T08:10:00Z", workspace: "Legal" },
];

const MOCK_CONTRACT_DETAIL = {
  1: { id: 1, name: "Master Services Agreement — Acme Corp", workspace: "Legal", versions: [
    { id: 3, label: "v3", filename: "MSA_v3_final.pdf", runState: "finalized", risk: "high",   runId: "run_3", createdAt: "2026-04-25T09:00:00Z", findingCount: 6 },
    { id: 2, label: "v2", filename: "MSA_v2_revised.pdf", runState: "finalized", risk: "medium", runId: "run_2", createdAt: "2026-04-23T14:00:00Z", findingCount: 4 },
    { id: 1, label: "v1", filename: "MSA_v1_initial.pdf",  runState: "finalized", risk: "high",   runId: "run_1", createdAt: "2026-04-20T10:00:00Z", findingCount: 8 },
  ]},
  2: { id: 2, name: "Non-Disclosure Agreement — TechVentures LLC", workspace: "Legal", versions: [
    { id: 4, label: "v1", filename: "NDA_TechVentures_v1.pdf", runState: "awaiting_human_review", risk: "medium", runId: "run_4", createdAt: "2026-04-26T09:15:00Z", findingCount: 4 },
  ]},
  3: { id: 3, name: "Employment Agreement — Senior Engineer", workspace: "HR", versions: [
    { id: 6, label: "v2", filename: "EA_SeniorEng_v2.pdf", runState: "finalized", risk: "low", runId: "run_6", createdAt: "2026-04-24T11:45:00Z", findingCount: 1 },
    { id: 5, label: "v1", filename: "EA_SeniorEng_v1.pdf", runState: "finalized", risk: "low", runId: "run_5", createdAt: "2026-04-22T09:00:00Z", findingCount: 2 },
  ]},
};

const MOCK_VERDICT = {
  riskLevel: "medium",
  summary: "This NDA contains several provisions that deviate from your firm's standard templates. The unlimited liability exposure clause and overly broad non-compete scope require immediate attention before execution.",
  findings: [
    { id: "f1", severity: "critical", title: "Unlimited liability exposure in data breach scenarios", quote: "In the event of unauthorized disclosure of Confidential Information, the Receiving Party shall be liable for all damages, including consequential, special, and punitive damages without limitation.", recommendation: "Negotiate a liability cap tied to fees paid in the prior 12 months. Remove punitive damages language entirely. This is a non-negotiable deviation from firm standard." },
    { id: "f2", severity: "medium", title: "Overly broad definition of Confidential Information", quote: "Confidential Information shall include any and all information disclosed by either party, whether oral or written, regardless of the form or medium.", recommendation: "Restrict to information marked as confidential at time of disclosure or reduced to writing within 30 days. Include standard carve-outs for public domain and independent development." },
    { id: "f3", severity: "medium", title: "Non-compete scope extends beyond reasonable jurisdiction", quote: "The Receiving Party agrees not to engage in any competing business activities anywhere in the world for a period of 5 years from the date of disclosure.", recommendation: "Limit geographic scope to regions where the Disclosing Party actively operates. Reduce duration to 12–24 months to ensure enforceability." },
    { id: "f4", severity: "low", title: "Governing law clause is ambiguous", quote: "This Agreement shall be governed by applicable law and the parties consent to jurisdiction.", recommendation: "Specify jurisdiction (e.g., State of New York) and agree on an explicit venue. Ambiguity here creates enforcement risk." },
  ],
  alignmentScore: 65,
  recommendations: ["negotiate_terms", "seek_legal_advice", "request_clarification"],
};

const MOCK_PIPELINE_STAGES = [
  { name: "document_ingestion", label: "Document Ingestion" },
  { name: "clause_extraction",  label: "Clause Extraction" },
  { name: "risk_classification", label: "Risk Classification" },
  { name: "policy_matching",    label: "Policy Matching" },
  { name: "report_generation",  label: "Report Generation" },
];

// ── Shared utilities ──────────────────────────────────────────────────────────

function timeAgo(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function riskColor(risk) {
  if (risk === "high" || risk === "critical") return "var(--risk-high)";
  if (risk === "medium") return "var(--risk-medium)";
  if (risk === "low") return "var(--risk-low)";
  return "var(--text-3)";
}

function riskLabel(risk) {
  if (!risk) return "—";
  return { low: "Low", medium: "Medium", high: "High", critical: "High" }[risk] ?? risk;
}

function stateLabel(state) {
  if (!state) return { text: "No runs", color: "var(--text-3)" };
  const map = {
    created:                { text: "Queued",          color: "var(--text-2)" },
    finalized:              { text: "Finalized",       color: "var(--risk-low)" },
    awaiting_human_review:  { text: "Awaiting Review", color: "var(--accent)" },
    under_review:           { text: "Under Review",    color: "var(--risk-medium)" },
    processing:             { text: "Processing",      color: "var(--accent)" },
    failed:                 { text: "Failed",          color: "var(--risk-high)" },
    blocked:                { text: "Blocked",         color: "var(--risk-high)" },
    rejected:               { text: "Rejected",        color: "var(--risk-high)" },
  };
  return map[state] ?? { text: state, color: "var(--text-2)" };
}

// ── Micro SVGs ────────────────────────────────────────────────────────────────

function IconArrowLeft({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 7H2M7 12l-5-5 5-5"/></svg>;
}
function IconArrowRight({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 7h10M7 2l5 5-5 5"/></svg>;
}
function IconPlus({ size = 12 }) {
  return <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 1v10M1 6h10"/></svg>;
}
function IconSearch({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="7" cy="7" r="5"/><path d="M11 11l3 3"/></svg>;
}
function IconBell({ size = 15 }) {
  return <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M8 1C5.239 1 3 3.239 3 6v4l-1.5 2h13L13 10V6c0-2.761-2.239-5-5-5z"/><path d="M6.5 14a1.5 1.5 0 003 0"/></svg>;
}
function IconSun({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="8" r="3.5"/><path d="M8 1v1M8 14v1M1 8h1M14 8h1M3.05 3.05l.7.7M12.25 12.25l.7.7M3.05 12.95l.7-.7M12.25 3.75l.7-.7"/></svg>;
}
function IconMoon({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M13.5 9.5A6 6 0 016.5 2.5 6 6 0 1013.5 9.5z"/></svg>;
}
function IconSettings({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>;
}
function IconChevronDown({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 5l5 5 5-5"/></svg>;
}
function IconCheck({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 7l4 4 6-6"/></svg>;
}

// ── Header ────────────────────────────────────────────────────────────────────

function Header({ screen, onNavigate, onAdmin, onProfile, onSearch, isDark, onToggleTheme, onLogout }) {
  const [notifOpen, setNotifOpen] = React.useState(false);
  const [notifs, setNotifs]       = React.useState([]);
  const notifRef = React.useRef(null);
  const user = window.verdictApi.currentUser();
  const isOrgAdmin = user?.org_role === "org_admin";

  React.useEffect(() => {
    window.verdictApi.listHistory(50).then(rows => {
      const pending = rows
        .filter(r => r.state === "awaiting_human_review")
        .slice(0, 8)
        .map(r => ({
          t: `${r.contract_name} requires sign-off`,
          b: `${r.workspace_name ?? "Workspace"} · ${r.version_label ?? ""}`,
          c: "var(--accent)",
          ago: r.updated_at,
          contractId: r.contract_id,
          runId: r.run_id,
        }));
      const recent = rows
        .filter(r => r.state === "finalized" && r.human_action)
        .slice(0, 4)
        .map(r => ({
          t: `${r.contract_name} analysis complete`,
          b: `${r.human_action === "approved" ? "Approved" : "Rejected"} · ${r.risk_level ? r.risk_level + " risk" : ""}`,
          c: r.human_action === "approved" ? "var(--risk-low)" : "var(--risk-high)",
          ago: r.updated_at,
          contractId: r.contract_id,
          runId: r.run_id,
        }));
      setNotifs([...pending, ...recent].slice(0, 8));
    }).catch(() => {});
  }, []);
  const initials = (user?.display_name || "User").split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase();

  React.useEffect(() => {
    function handler(e) {
      if (notifRef.current && !notifRef.current.contains(e.target)) setNotifOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const iconBtn = (onClick, children, active = false, title = "") => ({
    style: {
      width: 34, height: 34, display: "flex", alignItems: "center", justifyContent: "center",
      borderRadius: 7, color: active ? "var(--accent)" : "var(--text-2)",
      background: "transparent", cursor: "pointer", transition: "all 0.12s", border: "none",
    },
    onMouseEnter: e => { e.currentTarget.style.background = "var(--hover-bg)"; if (!active) e.currentTarget.style.color = "var(--text)"; },
    onMouseLeave: e => { e.currentTarget.style.background = "transparent"; if (!active) e.currentTarget.style.color = "var(--text-2)"; },
    onClick, title
  });

  return (
    <header style={{ position: "sticky", top: 0, zIndex: 50, background: "var(--bg)", borderBottom: "1px solid var(--border)", transition: "background 0.3s" }}>
      <div style={{ maxWidth: 1400, margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 52px", height: 52 }}>
        {/* Logo + Nav */}
        <div style={{ display: "flex", alignItems: "center", gap: 36 }}>
          <button onClick={() => onNavigate("dashboard")} style={{ fontFamily: "var(--font-serif)", fontSize: 17, fontWeight: 700, color: "var(--text)", letterSpacing: "-0.01em", border: "none", background: "none", cursor: "pointer" }}>
            Veridict
          </button>
          <nav style={{ display: "flex", gap: 2 }}>
            {[{ l: "Dashboard", s: "dashboard" }, { l: "History", s: "history" }].map(({ l, s }) => (
              <button key={s} onClick={() => onNavigate(s)} style={{ fontSize: 13, fontWeight: 500, color: screen === s ? "var(--text)" : "var(--text-2)", padding: "4px 11px", borderRadius: 6, background: screen === s ? "var(--hover-bg)" : "transparent", border: "none", cursor: "pointer", transition: "all 0.12s" }}
                onMouseEnter={e => { if (screen !== s) e.currentTarget.style.color = "var(--text)"; }}
                onMouseLeave={e => { if (screen !== s) e.currentTarget.style.color = "var(--text-2)"; }}
              >{l}</button>
            ))}
          </nav>
        </div>

        {/* Right */}
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <button onClick={onSearch} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 11px", borderRadius: 7, border: "1px solid var(--border)", color: "var(--text-3)", fontSize: 12, background: "none", cursor: "pointer", transition: "all 0.12s" }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--text-3)"; e.currentTarget.style.color = "var(--text-2)"; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--text-3)"; }}
          >
            <IconSearch size={12} />
            <span>Search</span>
            <kbd style={{ fontFamily: "monospace", fontSize: 9, opacity: 0.6, border: "1px solid var(--border)", padding: "1px 5px", borderRadius: 3 }}>⌘K</kbd>
          </button>

          <div style={{ position: "relative" }} ref={notifRef}>
            <button {...iconBtn(() => setNotifOpen(v => !v), null, notifOpen, "Notifications")} style={{ ...iconBtn(() => {}).style, position: "relative" }}>
              <IconBell />
              {notifs.filter(n => n.c === "var(--accent)").length > 0 && (
                <span style={{ position: "absolute", top: 6, right: 6, width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", border: "2px solid var(--bg)" }} />
              )}
            </button>
            {notifOpen && (
              <div style={{ position: "absolute", right: 0, top: "calc(100% + 8px)", width: 320, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, boxShadow: "0 8px 32px rgba(0,0,0,0.12)", overflow: "hidden", zIndex: 60 }}>
                <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                  <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-3)" }}>Notifications</p>
                </div>
                {notifs.length === 0 ? (
                  <div style={{ padding: "24px 16px", textAlign: "center", color: "var(--text-3)", fontSize: 13 }}>No notifications</div>
                ) : notifs.map((n, i) => (
                  <div key={i} onClick={() => { onNavigate("contract_detail", n.contractId); setNotifOpen(false); }} style={{ padding: "12px 16px", borderBottom: "1px solid var(--border-light)", cursor: "pointer", display: "flex", gap: 10, alignItems: "flex-start", transition: "background 0.1s" }}
                    onMouseEnter={e => e.currentTarget.style.background = "var(--hover-bg)"}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                  >
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: n.c, flexShrink: 0, marginTop: 5 }} />
                    <div style={{ minWidth: 0 }}>
                      <p style={{ fontSize: 12, fontWeight: 500, color: "var(--text)", lineHeight: 1.4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{n.t}</p>
                      <p style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{n.b} · {timeAgo(n.ago)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <button {...iconBtn(onToggleTheme, null, false, isDark ? "Light mode" : "Dark mode")}>{isDark ? <IconSun /> : <IconMoon />}</button>
          <div style={{ width: 1, height: 18, background: "var(--border)", margin: "0 4px" }} />
          {isOrgAdmin && (
            <button {...iconBtn(onAdmin, null, screen === "admin", "Admin")}><IconSettings /></button>
          )}
          <button onClick={onProfile} title="Profile" style={{ width: 28, height: 28, borderRadius: "50%", background: user?.avatar_color || "var(--accent)", color: "white", fontSize: 10, fontWeight: 700, border: screen === "profile" ? "2px solid var(--accent)" : "2px solid transparent", outline: screen === "profile" ? "2px solid var(--bg)" : "none", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", transition: "all 0.12s", flexShrink: 0 }}>{initials}</button>
          <button onClick={onLogout} title="Sign out" style={{ width: 34, height: 34, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 7, color: "var(--text-3)", background: "transparent", cursor: "pointer", transition: "all 0.12s", border: "none" }}
            onMouseEnter={e => { e.currentTarget.style.background = "var(--hover-bg)"; e.currentTarget.style.color = "var(--risk-high)"; }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-3)"; }}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M5 2H2a1 1 0 00-1 1v8a1 1 0 001 1h3M9 10l3-3-3-3M5.5 7h7"/></svg>
          </button>
        </div>
      </div>
    </header>
  );
}

function SearchOverlay({ open, onClose, onOpenContract, onOpenWorkspace }) {
  const [query, setQuery] = React.useState("");
  const [contracts, setContracts] = React.useState([]);
  const [workspaces, setWorkspaces] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [activeIdx, setActiveIdx] = React.useState(0);
  const inputRef = React.useRef(null);

  React.useEffect(() => {
    if (!open) {
      setQuery("");
      setActiveIdx(0);
      return;
    }
    window.requestAnimationFrame(() => inputRef.current?.focus());
    setLoading(true);
    Promise.all([
      window.verdictApi.listContracts().catch(() => []),
      window.verdictApi.listWorkspaces().catch(() => []),
    ]).then(([contractRows, workspaceRows]) => {
      setContracts(contractRows);
      setWorkspaces(workspaceRows);
    }).finally(() => setLoading(false));
  }, [open]);

  const results = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    const contractResults = contracts
      .filter(c => !q || c.name.toLowerCase().includes(q) || (c.workspace || "").toLowerCase().includes(q))
      .slice(0, q ? 8 : 6)
      .map(c => ({ type: "contract", id: `contract-${c.id}`, label: c.name, detail: `${c.workspace || "Workspace"} · ${stateLabel(c.latestRunState).text}`, risk: c.latestRisk, item: c }));
    const workspaceResults = workspaces
      .filter(w => !q || (w.name || "").toLowerCase().includes(q) || (w.description || "").toLowerCase().includes(q) || (w.role || "").toLowerCase().includes(q))
      .slice(0, q ? 5 : 4)
      .map(w => ({ type: "workspace", id: `workspace-${w.workspace_id}`, label: w.name, detail: [w.role?.replace("_", " "), w.description].filter(Boolean).join(" · ") || "Workspace", item: w }));
    return [...contractResults, ...workspaceResults].slice(0, 12);
  }, [query, contracts, workspaces]);

  React.useEffect(() => setActiveIdx(0), [query, results.length]);

  if (!open) return null;

  function choose(result) {
    if (!result) return;
    if (result.type === "contract") onOpenContract(result.item);
    else onOpenWorkspace(result.item);
    onClose();
  }

  function onKeyDown(e) {
    if (e.key === "Escape") onClose();
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx(i => Math.min(i + 1, Math.max(results.length - 1, 0)));
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx(i => Math.max(i - 1, 0));
    }
    if (e.key === "Enter") {
      e.preventDefault();
      choose(results[activeIdx]);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.26)", backdropFilter: "blur(3px)", display: "flex", justifyContent: "center", alignItems: "flex-start", paddingTop: "12vh" }} onMouseDown={onClose}>
      <div onMouseDown={e => e.stopPropagation()} style={{ width: "min(620px, calc(100vw - 32px))", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, boxShadow: "0 18px 60px rgba(0,0,0,0.18)", overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
          <IconSearch size={15} />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search contracts or workspaces..."
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", color: "var(--text)", fontSize: 14 }}
          />
          <button onClick={onClose} style={{ border: "none", background: "transparent", color: "var(--text-3)", cursor: "pointer", fontSize: 18, lineHeight: 1 }}>×</button>
        </div>

        <div style={{ maxHeight: 420, overflowY: "auto", padding: "7px 0" }}>
          {loading ? (
            <div style={{ padding: "34px 16px", textAlign: "center", color: "var(--text-3)", fontSize: 13 }}>Loading search…</div>
          ) : results.length === 0 ? (
            <div style={{ padding: "34px 16px", textAlign: "center", color: "var(--text-3)", fontSize: 13 }}>No results for “{query}”</div>
          ) : (
            results.map((result, i) => (
              <button
                key={result.id}
                onClick={() => choose(result)}
                onMouseEnter={() => setActiveIdx(i)}
                style={{
                  width: "100%",
                  border: "none",
                  background: i === activeIdx ? "var(--hover-bg)" : "transparent",
                  color: "var(--text)",
                  cursor: "pointer",
                  display: "grid",
                  gridTemplateColumns: "30px 1fr auto",
                  gap: 12,
                  alignItems: "center",
                  padding: "10px 16px",
                  textAlign: "left",
                }}
              >
                <span style={{ width: 30, height: 30, borderRadius: 7, border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center", color: result.type === "workspace" ? "var(--accent)" : "var(--text-2)", background: "var(--bg)" }}>
                  {result.type === "workspace" ? "W" : <IconSearch size={12} />}
                </span>
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: "block", fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{result.label}</span>
                  <span style={{ display: "block", marginTop: 2, fontSize: 11.5, color: "var(--text-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{result.detail}</span>
                </span>
                <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: result.type === "workspace" ? "var(--accent)" : riskColor(result.risk) }}>
                  {result.type}
                </span>
              </button>
            ))
          )}
        </div>

        <div style={{ display: "flex", gap: 14, padding: "10px 16px", borderTop: "1px solid var(--border)", color: "var(--text-3)", fontSize: 10 }}>
          <span>↑↓ navigate</span>
          <span>Enter open</span>
          <span>Esc close</span>
        </div>
      </div>
    </div>
  );
}

// ── URL ↔ screen helpers ──────────────────────────────────────────────────────

function screenToUrl(s, id, runId) {
  if (s === "contract_detail" && id) return `/contracts/${id}`;
  if (s === "verdict" && id && runId) return `/contracts/${id}/runs/${runId}`;
  if (s === "new_contract") return "/new";
  if (s === "processing") return "/processing";
  if (s === "history") return "/history";
  if (s === "profile") return "/profile";
  if (s === "admin") return "/admin";
  return "/";
}

function urlToScreen(pathname) {
  const verdictMatch = pathname.match(/^\/contracts\/([^/]+)\/runs\/([^/]+)$/);
  if (verdictMatch) return { screen: "verdict", id: verdictMatch[1], runId: verdictMatch[2] };
  const contractMatch = pathname.match(/^\/contracts\/([^/]+)$/);
  if (contractMatch) return { screen: "contract_detail", id: contractMatch[1], runId: null };
  if (pathname === "/history") return { screen: "history", id: null, runId: null };
  if (pathname === "/profile") return { screen: "profile", id: null, runId: null };
  if (pathname === "/admin") return { screen: "admin", id: null, runId: null };
  if (pathname === "/new") return { screen: "new_contract", id: null, runId: null };
  if (pathname === "/processing") return { screen: "processing", id: null, runId: null };
  return { screen: "dashboard", id: null, runId: null };
}

// ── App ───────────────────────────────────────────────────────────────────────

function App() {
  const [tweaks, setTweakState] = React.useState(TWEAK_DEFAULTS);
  const { theme, density, accent, serifHeaders } = tweaks;
  const isDark = theme === "dark";

  const setTweak = React.useCallback((key, val) => {
    setTweakState(prev => {
      const next = typeof key === "object" ? { ...prev, ...key } : { ...prev, [key]: val };
      window.parent.postMessage({ type: "__edit_mode_set_keys", edits: next }, "*");
      return next;
    });
  }, []);

  // Apply theme
  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
    // accent color
    const accentMap = { gold: "#C8973E", indigo: "#6366F1", sage: "#4EA872" };
    const accentHoverMap = { gold: "#B5862F", indigo: "#4F46E5", sage: "#3D8B5E" };
    document.documentElement.style.setProperty("--accent", accentMap[accent] || accentMap.gold);
    document.documentElement.style.setProperty("--accent-hover", accentHoverMap[accent] || accentHoverMap.gold);
    // density
    document.documentElement.style.setProperty("--density-pad", density === "compact" ? "44px" : "60px");
    document.documentElement.style.setProperty("--density-gap", density === "compact" ? "32px" : "48px");
    // serif headers
    document.documentElement.style.setProperty("--h-font", serifHeaders ? "var(--font-serif)" : "var(--font-sans)");
  }, [isDark, accent, density, serifHeaders]);

  const [loggedIn, setLoggedIn] = React.useState(() => Boolean(window.verdictApi.currentUser()));
  const [sessionExpired, setSessionExpired] = React.useState(false);
  const [screen, setScreen] = React.useState(() => urlToScreen(window.location.pathname).screen);
  const [selectedContractId, setSelectedContractId] = React.useState(() => urlToScreen(window.location.pathname).id);
  const [selectedRunId, setSelectedRunId] = React.useState(() => urlToScreen(window.location.pathname).runId);
  const [pendingError, setPendingError] = React.useState(null);
  const [fileName, setFileName] = React.useState("");
  const [processingRunId, setProcessingRunId] = React.useState(null);
  const [tweakPanelVisible, setTweakPanelVisible] = React.useState(false);
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [workspaceFilter, setWorkspaceFilter] = React.useState(null);
  const currentUser = window.verdictApi.currentUser();
  const isOrgAdmin = currentUser?.org_role === "org_admin";

  // Tweaks panel protocol
  React.useEffect(() => {
    function handler(e) {
      if (e.data?.type === "__activate_edit_mode") setTweakPanelVisible(true);
      if (e.data?.type === "__deactivate_edit_mode") setTweakPanelVisible(false);
    }
    window.addEventListener("message", handler);
    window.parent.postMessage({ type: "__edit_mode_available" }, "*");
    return () => window.removeEventListener("message", handler);
  }, []);

  React.useEffect(() => {
    const evt = window.verdictApi.VERDICT_SESSION_EXPIRED;
    function applySessionExpired() {
      setLoggedIn(false);
      setSessionExpired(true);
      setScreen("dashboard");
      setSelectedContractId(null);
      setSelectedRunId(null);
    }
    function onEvent() {
      window.verdictApi.consumeSessionExpiredNotice();
      applySessionExpired();
    }
    window.addEventListener(evt, onEvent);
    if (window.verdictApi.consumeSessionExpiredNotice()) applySessionExpired();
    return () => window.removeEventListener(evt, onEvent);
  }, []);

  React.useEffect(() => {
    if (screen !== "processing") setProcessingRunId(null);
  }, [screen]);

  function navigate(s, id = null, runId = null) {
    if (s === "admin" && !isOrgAdmin) {
      s = "dashboard";
      id = null;
      runId = null;
    }
    if (s !== "dashboard") setWorkspaceFilter(null);
    setSelectedContractId(id);
    setSelectedRunId(runId);
    setScreen(s);
    window.scrollTo({ top: 0, behavior: "smooth" });
    history.pushState({ screen: s, id, runId }, "", screenToUrl(s, id, runId));
  }

  // Stamp the initial history entry and handle browser back/forward
  React.useEffect(() => {
    const init = urlToScreen(window.location.pathname);
    history.replaceState({ screen: init.screen, id: init.id, runId: init.runId }, "", window.location.pathname + window.location.search);

    function onPopState(e) {
      const state = e.state || urlToScreen(window.location.pathname);
      setScreen(state.screen || "dashboard");
      setSelectedContractId(state.id || null);
      setSelectedRunId(state.runId || null);
      setWorkspaceFilter(null);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  React.useEffect(() => {
    if (loggedIn && screen === "admin" && !isOrgAdmin) {
      navigate("dashboard");
    }
  }, [loggedIn, screen, isOrgAdmin]);

  React.useEffect(() => {
    function handler(e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const screenProps = {
    screen,
    navigate,
    selectedContractId,
    selectedRunId,
    fileName,
    processingRunId,
    pendingError,
    workspaceFilter,
    onWorkspaceFilterChange: setWorkspaceFilter,
    onClearWorkspaceFilter: () => setWorkspaceFilter(null),
  };

  if (!loggedIn) {
    return (
      <AuthScreen
        sessionExpired={sessionExpired}
        onLogin={() => { setSessionExpired(false); setLoggedIn(true); }}
      />
    );
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "var(--bg)", transition: "background 0.3s, color 0.3s" }}>
      <Header screen={screen} onNavigate={(s, id) => navigate(s, id)} onAdmin={() => navigate("admin")} onProfile={() => navigate("profile")} onSearch={() => setSearchOpen(true)} isDark={isDark} onToggleTheme={() => setTweak("theme", isDark ? "light" : "dark")} onLogout={async () => { await window.verdictApi.logout(); setSessionExpired(false); setLoggedIn(false); }} />

      <main style={{ flex: 1, maxWidth: 1400, margin: "0 auto", width: "100%", padding: "0 52px" }}>
        {screen === "dashboard"        && <DashboardScreen {...screenProps} />}
        {screen === "contract_detail"  && <ContractDetailScreen {...screenProps} onViewRun={(runId) => navigate("verdict", selectedContractId, runId)} onAddVersion={async (file) => {
          if (!selectedContractId || !file) return;
          setFileName(file.name);
          setPendingError(null);
          navigate("processing");
          try {
            const result = await window.verdictApi.addContractVersion(selectedContractId, file);
            setProcessingRunId(result.run_id ?? null);
            setSelectedContractId(result.contract_id ?? selectedContractId);
          } catch (err) {
            setPendingError(err.message || "Upload failed");
          }
        }} />}
        {screen === "new_contract"     && <NewContractScreen {...screenProps} onSubmit={async (name, file) => {
          setFileName(file?.name ?? name + ".pdf");
          setPendingError(null);
          navigate("processing");
          try {
            const workspaces = await window.verdictApi.listWorkspaces();
            const workspaceId = workspaces[0]?.workspace_id;
            if (!workspaceId) throw new Error("No workspace is available for this account.");
            const contract = await window.verdictApi.createContract(name, workspaceId);
            const result = await window.verdictApi.addContractVersion(contract.id, file);
            setSelectedContractId(contract.id);
            setProcessingRunId(result.run_id ?? null);
          } catch (err) {
            setPendingError(err.message || "Upload failed");
          }
        }} />}
        {screen === "processing"       && <ProcessingScreen {...screenProps} />}
        {screen === "verdict"          && <VerdictScreen {...screenProps} onApprove={() => navigate("contract_detail", selectedContractId ?? 2)} onReject={() => navigate("contract_detail", selectedContractId ?? 2)} />}
        {screen === "history" && <HistoryScreen {...screenProps} />}
        {screen === "profile" && <ProfileScreen {...screenProps} />}
        {screen === "admin" && isOrgAdmin && <AdminScreen  {...screenProps} />}
      </main>

      <footer style={{ borderTop: "1px solid var(--border)", padding: "18px 52px", display: "flex", justifyContent: "space-between", alignItems: "center", transition: "border-color 0.3s" }}>
        <span style={{ fontSize: 12, color: "var(--text-3)" }}>© 2026 Veridict — Legal Intelligence Platform</span>
        <span style={{ fontSize: 12, color: "var(--text-3)" }}>v2.4.1</span>
      </footer>

      <SearchOverlay
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        onOpenContract={(contract) => navigate("contract_detail", contract.id)}
        onOpenWorkspace={(workspace) => {
          setWorkspaceFilter({ id: workspace.workspace_id, name: workspace.name });
          navigate("dashboard");
        }}
      />

      {tweakPanelVisible && (
        <TweaksPanel onClose={() => { setTweakPanelVisible(false); window.parent.postMessage({ type: "__edit_mode_dismissed" }, "*"); }}>
          <TweakSection label="Appearance">
            <TweakRadio label="Theme" value={theme} options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} onChange={v => setTweak("theme", v)} />
            <TweakRadio label="Density" value={density} options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} onChange={v => setTweak("density", v)} />
          </TweakSection>
          <TweakSection label="Brand">
            <TweakRadio label="Accent color" value={accent} options={[{ value: "gold", label: "Gold" }, { value: "indigo", label: "Indigo" }, { value: "sage", label: "Sage" }]} onChange={v => setTweak("accent", v)} />
            <TweakToggle label="Serif headers" value={serifHeaders} onChange={v => setTweak("serifHeaders", v)} />
          </TweakSection>
        </TweaksPanel>
      )}
    </div>
  );
}

function PlaceholderScreen({ title, desc }) {
  return (
    <div style={{ padding: "80px 0", animation: "fadeIn 0.35s ease both" }}>
      <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 12 }}>Coming soon</p>
      <h1 style={{ fontFamily: "var(--h-font)", fontSize: 40, fontWeight: 700, color: "var(--text)", marginBottom: 12 }}>{title}</h1>
      <p style={{ fontSize: 15, color: "var(--text-2)" }}>{desc}</p>
    </div>
  );
}

Object.assign(window, {
  App, Header, PlaceholderScreen,
  MOCK_CONTRACTS, MOCK_CONTRACT_DETAIL, MOCK_VERDICT, MOCK_PIPELINE_STAGES, TWEAK_DEFAULTS,
  STAGE_LABELS: undefined,
  timeAgo, greeting, riskColor, riskLabel, stateLabel,
  IconArrowLeft, IconArrowRight, IconPlus, IconCheck, IconChevronDown
});
