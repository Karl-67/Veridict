
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
    finalized:              { text: "Finalized",       color: "var(--risk-low)" },
    awaiting_human_review:  { text: "Awaiting Review", color: "var(--accent)" },
    under_review:           { text: "Under Review",    color: "var(--risk-medium)" },
    processing:             { text: "Processing",      color: "var(--accent)" },
    failed:                 { text: "Failed",          color: "var(--risk-high)" },
    blocked:                { text: "Blocked",         color: "var(--risk-high)" },
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
  return <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="8" r="2"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.4 1.4M11.55 11.55l1.4 1.4M3.05 12.95l1.4-1.4M11.55 4.45l1.4-1.4"/></svg>;
}
function IconChevronDown({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 5l5 5 5-5"/></svg>;
}
function IconCheck({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 7l4 4 6-6"/></svg>;
}

// ── Header ────────────────────────────────────────────────────────────────────

function Header({ screen, onNavigate, onAdmin, onProfile, isDark, onToggleTheme, onLogout }) {
  const [notifOpen, setNotifOpen] = React.useState(false);
  const [notifs, setNotifs]       = React.useState([]);
  const notifRef = React.useRef(null);
  const user = window.verdictApi.currentUser();

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
          <button style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 11px", borderRadius: 7, border: "1px solid var(--border)", color: "var(--text-3)", fontSize: 12, background: "none", cursor: "pointer", transition: "all 0.12s" }}
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
          <button {...iconBtn(onAdmin, null, screen === "admin", "Admin")}><IconSettings /></button>
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
  const [screen, setScreen] = React.useState("dashboard");
  const [selectedContractId, setSelectedContractId] = React.useState(null);
  const [selectedRunId, setSelectedRunId] = React.useState(null);
  const [pendingError, setPendingError] = React.useState(null);
  const [fileName, setFileName] = React.useState("");
  const [processingStage, setProcessingStage] = React.useState(0);
  const [tweakPanelVisible, setTweakPanelVisible] = React.useState(false);

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

  // Simulate processing
  React.useEffect(() => {
    if (screen !== "processing") { setProcessingStage(0); return; }
    let s = 0;
    const t = setInterval(() => {
      s++;
      setProcessingStage(s);
      if (s >= MOCK_PIPELINE_STAGES.length) {
        clearInterval(t);
        setTimeout(() => navigate("verdict"), 600);
      }
    }, 1200);
    return () => clearInterval(t);
  }, [screen]);

  function navigate(s, id = null, runId = null) {
    setSelectedContractId(id);
    setSelectedRunId(runId);
    setScreen(s);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const screenProps = { screen, navigate, selectedContractId, selectedRunId, fileName, processingStage, pendingError };

  if (!loggedIn) return <AuthScreen onLogin={() => setLoggedIn(true)} />;

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "var(--bg)", transition: "background 0.3s, color 0.3s" }}>
      <Header screen={screen} onNavigate={(s, id) => navigate(s, id)} onAdmin={() => navigate("admin")} onProfile={() => navigate("profile")} isDark={isDark} onToggleTheme={() => setTweak("theme", isDark ? "light" : "dark")} onLogout={async () => { await window.verdictApi.logout(); setLoggedIn(false); }} />

      <main style={{ flex: 1, maxWidth: 1400, margin: "0 auto", width: "100%", padding: "0 52px" }}>
        {screen === "dashboard"        && <DashboardScreen {...screenProps} />}
        {screen === "contract_detail"  && <ContractDetailScreen {...screenProps} onViewRun={(runId) => navigate("verdict", selectedContractId, runId)} onAddVersion={async (file) => {
          if (!selectedContractId || !file) return;
          setFileName(file.name);
          setPendingError(null);
          navigate("processing");
          try {
            const result = await window.verdictApi.addContractVersion(selectedContractId, file);
            setTimeout(() => navigate("contract_detail", result.contract_id), 600);
          } catch (err) {
            setPendingError(err.message || "Upload failed");
            navigate("processing");
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
            await window.verdictApi.addContractVersion(contract.id, file);
            setTimeout(() => navigate("contract_detail", contract.id), 600);
          } catch (err) {
            setPendingError(err.message || "Upload failed");
            navigate("processing");
          }
        }} />}
        {screen === "processing"       && <ProcessingScreen {...screenProps} />}
        {screen === "verdict"          && <VerdictScreen {...screenProps} onApprove={() => navigate("contract_detail", selectedContractId ?? 2)} onReject={() => navigate("contract_detail", selectedContractId ?? 2)} />}
        {screen === "history" && <HistoryScreen {...screenProps} />}
        {screen === "profile" && <ProfileScreen {...screenProps} />}
        {screen === "admin"   && <AdminScreen  {...screenProps} />}
      </main>

      <footer style={{ borderTop: "1px solid var(--border)", padding: "18px 52px", display: "flex", justifyContent: "space-between", alignItems: "center", transition: "border-color 0.3s" }}>
        <span style={{ fontSize: 12, color: "var(--text-3)" }}>© 2026 Veridict — Legal Intelligence Platform</span>
        <span style={{ fontSize: 12, color: "var(--text-3)" }}>v2.4.1</span>
      </footer>

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
  timeAgo, greeting, riskColor, riskLabel, stateLabel,
  IconArrowLeft, IconArrowRight, IconPlus, IconCheck, IconChevronDown
});
