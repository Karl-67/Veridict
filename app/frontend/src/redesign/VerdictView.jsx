
// ── Verdict Screen ────────────────────────────────────────────────────────────

const verdictSeverityConfig = {
  critical: { label: "Critical", color: "var(--risk-high)",   bg: "rgba(196,67,43,0.09)"  },
  high:     { label: "High",     color: "var(--risk-high)",   bg: "rgba(196,67,43,0.05)"  },
  medium:   { label: "Warning",  color: "var(--risk-medium)", bg: "rgba(200,151,62,0.09)" },
  low:      { label: "Low",      color: "var(--text-3)",      bg: "transparent"           },
};

const verdictRiskConfig = {
  high:   { label: "High Risk Exposure",   color: "var(--risk-high)",   bg: "rgba(196,67,43,0.06)"  },
  medium: { label: "Medium Risk Exposure", color: "var(--risk-medium)", bg: "rgba(200,151,62,0.06)" },
  low:    { label: "Low Risk Exposure",    color: "var(--risk-low)",    bg: "rgba(61,139,94,0.06)"  },
};

function SectionLabel({ children, style = {} }) {
  return (
    <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.14em", color: "var(--text-3)", marginBottom: 20, ...style }}>{children}</p>
  );
}

// Normalize raw backend findings so ContractReader gets Admin evidence anchors first.
function toReaderFindings(rawFindings) {
  const isFocusedEvidence = text => {
    const normalized = (text ?? "").replace(/\s+/g, " ").trim();
    return normalized.length > 0 && normalized.length <= 900;
  };

  return rawFindings.map(f => {
    const contractEvidence = (f.contract_evidence ?? [])
      .map(ce => ({
        page: ce.page ?? 1,
        normalized_text: ce.text ?? ce.excerpt ?? ce.normalized_text ?? "",
        document_hash: "",
        parser_version: "",
        clause_uid: ce.clause_id ?? ce.clause_uid ?? f.clause_uid ?? "",
        bbox: ce.bbox ?? [],
        extraction_confidence: ce.confidence ?? ce.extraction_confidence ?? 1,
      }))
      .filter(e => isFocusedEvidence(e.normalized_text));

    const legacyEvidence = (f.evidence ?? [])
      .map(e => ({
        ...e,
        page: e.page ?? 1,
        normalized_text: e.normalized_text ?? e.text ?? "",
        clause_uid: e.clause_uid ?? f.clause_uid ?? "",
      }))
      .filter(e => isFocusedEvidence(e.normalized_text));

    return {
      ...f,
      evidence: contractEvidence.length > 0 ? contractEvidence : legacyEvidence,
    };
  });
}

// ── Comments panel ────────────────────────────────────────────────────────────

function CommentsPanel({ runId }) {
  const [comments, setComments] = React.useState([]);
  const [draft, setDraft]       = React.useState("");
  const [posting, setPosting]   = React.useState(false);
  const currentUser = window.verdictApi.currentUser();

  React.useEffect(() => {
    if (!runId) return;
    let active = true;
    window.verdictApi.listRunComments(runId)
      .then(data => {
        // Only show general (non-anchored) comments in the analysis panel.
        // Anchored (text-selection) comments live in the document viewer left rail.
        if (active) setComments(data.filter(c => !c.anchor));
      })
      .catch(() => {});
    return () => { active = false; };
  }, [runId]);

  async function post() {
    const body = draft.trim();
    if (!body || posting) return;
    setPosting(true);
    try {
      const c = await window.verdictApi.postRunComment(runId, body);
      setComments(prev => [...prev, c]);
      setDraft("");
    } catch {}
    setPosting(false);
  }

  async function remove(commentId) {
    try {
      await window.verdictApi.deleteRunComment(runId, commentId);
      setComments(prev => prev.filter(c => c.id !== commentId));
    } catch {}
  }

  function initials(name) {
    return (name || "?").split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase();
  }

  function commentAgo(iso) {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  return (
    <div>
      <SectionLabel>Legal Team Notes</SectionLabel>
      <div style={{ border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
        {comments.length === 0 && (
          <div style={{ padding: "16px 14px", color: "var(--text-3)", fontSize: 12.5 }}>No notes yet. Be the first to add one.</div>
        )}
        {comments.map((c, i) => (
          <div key={c.id} style={{ padding: "12px 14px", borderBottom: i < comments.length - 1 ? "1px solid var(--border-light)" : "none" }}>
            <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
              <span style={{ width: 22, height: 22, borderRadius: "50%", background: c.avatar_color || "var(--accent)", color: "white", fontSize: 9, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, marginTop: 1 }}>{initials(c.author_name)}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 2 }}>
                  <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--text)" }}>{c.author_name}</span>
                  {c.job_title && <span style={{ fontSize: 10, color: "var(--text-3)" }}>{c.job_title}</span>}
                  <span style={{ fontSize: 10, color: "var(--text-3)", marginLeft: "auto" }}>{commentAgo(c.created_at)}</span>
                </div>
                <p style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.55 }}>{c.body}</p>
              </div>
              {currentUser?.user_id === c.author_id && (
                <button onClick={() => remove(c.id)} title="Delete" style={{ flexShrink: 0, fontSize: 10, color: "var(--text-3)", background: "none", border: "none", cursor: "pointer", padding: "2px 4px", borderRadius: 4, transition: "color 0.12s" }}
                  onMouseEnter={e => e.currentTarget.style.color = "var(--risk-high)"}
                  onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>✕</button>
              )}
            </div>
          </div>
        ))}
        <div style={{ padding: "10px 14px", borderTop: "1px solid var(--border-light)", display: "flex", gap: 8, alignItems: "center" }}>
          <input
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); post(); } }}
            placeholder="Add a note…"
            style={{ flex: 1, fontSize: 12.5, color: "var(--text)", background: "none", border: "none", outline: "none" }}
          />
          <button onClick={post} disabled={!draft.trim() || posting} style={{ fontSize: 12, fontWeight: 600, color: draft.trim() ? "var(--accent)" : "var(--text-3)", background: "none", border: "none", cursor: draft.trim() ? "pointer" : "default", transition: "color 0.12s" }}>
            {posting ? "…" : "Post"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main verdict screen ───────────────────────────────────────────────────────

function VerdictScreen({ navigate, selectedContractId, selectedRunId, onApprove, onReject }) {
  const [verdict, setVerdict]         = React.useState(null);
  const [rawFindings, setRawFindings] = React.useState([]);
  const [loadErr, setLoadErr]         = React.useState(false);
  const [fileName, setFileName]       = React.useState("Contract analysis report.pdf");
  const [expandedIdx, setExpandedIdx] = React.useState(null);
  const [rejectMode, setRejectMode]   = React.useState(false);
  const [rejectReason, setRejectReason] = React.useState("");
  const [approved, setApproved]       = React.useState(false);
  const [activeTab, setActiveTab]     = React.useState("analysis");
  const currentUser = window.verdictApi.currentUser();

  React.useEffect(() => {
    if (!selectedRunId) { setVerdict(null); return; }
    let active = true;
    setVerdict(null); setLoadErr(false); setRawFindings([]);
    window.verdictApi.getRun(selectedRunId).then(async run => {
      if (!active) return;
      setFileName(run.filename || "Contract analysis report.pdf");
      const findings = run.verdict?.findings ?? await window.verdictApi.getRunFindings(selectedRunId).catch(() => []);
      if (active) setRawFindings(findings);
      const mapped = {
        riskLevel: run.verdict?.overall_risk_level === "critical" ? "high" : (run.verdict?.overall_risk_level ?? "medium"),
        summary: run.verdict?.summary ?? "This contract is awaiting human review. Review the findings below before final sign-off.",
        findings: findings.map((f, index) => ({
          id: f.finding_id ?? String(index),
          severity: f.severity,
          title: f.issue_type || f.description || "Contract finding",
          quote: f.contract_evidence?.[0]?.text || f.evidence?.[0]?.normalized_text || "No direct quote available.",
          recommendation: f.recommendation_detail || f.recommendation || f.description,
        })),
        recommendations: run.verdict?.recommendations ?? [],
        blockedReason: run.blocked_reason ?? null,
      };
      if (active) setVerdict(mapped);
    }).catch(() => { if (active) setLoadErr(true); });
    return () => { active = false; };
  }, [selectedRunId]);

  if (loadErr) {
    return (
      <div style={{ paddingTop: "var(--density-pad)", color: "var(--text-3)", display: "flex", flexDirection: "column", gap: 12 }}>
        <p style={{ fontSize: 14 }}>Could not load analysis results.</p>
        <button onClick={() => navigate("contract_detail", selectedContractId)} style={{ fontSize: 13, color: "var(--text-2)", background: "none", border: "none", cursor: "pointer", textAlign: "left" }}>← Back to Contract</button>
      </div>
    );
  }
  if (!verdict) {
    return <div style={{ paddingTop: "var(--density-pad)", color: "var(--text-3)" }}>Loading analysis…</div>;
  }

  const risk = verdictRiskConfig[verdict.riskLevel] ?? verdictRiskConfig.medium;
  const counts = { critical: 0, high: 0, medium: 0, low: 0 };
  verdict.findings.forEach(f => { if (f.severity in counts) counts[f.severity]++; });

  const backTarget = selectedContractId ? "contract_detail" : "dashboard";
  const backLabel  = selectedContractId ? "Back to Contract" : "Back to Dashboard";

  const readerFindings = toReaderFindings(rawFindings);
  const ContractReaderComponent = window.ContractReader;

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 100, animation: "fadeIn 0.4s ease both" }}>

      {/* Back */}
      <button onClick={() => navigate(backTarget, selectedContractId)} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-2)", marginBottom: 36, border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" }}
        onMouseEnter={e => e.currentTarget.style.color = "var(--text)"}
        onMouseLeave={e => e.currentTarget.style.color = "var(--text-2)"}>
        <IconArrowLeft />{backLabel}
      </button>

      {/* ── Report header ─────────────────────────────────────────────────────── */}
      <div style={{ borderBottom: "1px solid var(--border)", paddingBottom: 40, marginBottom: 36 }}>
        <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.14em", color: "var(--text-3)", marginBottom: 14 }}>
          Contract Analysis Report · {new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
        </p>
        <h1 style={{ fontFamily: "var(--h-font)", fontSize: 38, fontWeight: 700, letterSpacing: "-0.025em", color: "var(--text)", marginBottom: 24, maxWidth: 660, lineHeight: 1.2 }}>{fileName}</h1>

        {verdict.blockedReason && (
          <div style={{ display: "flex", gap: 10, padding: "12px 16px", background: "rgba(196,67,43,0.06)", border: "1px solid rgba(196,67,43,0.2)", borderRadius: 8, marginBottom: 20 }}>
            <span style={{ color: "var(--risk-high)", fontSize: 13, flexShrink: 0 }}>⚠</span>
            <p style={{ fontSize: 13, color: "var(--risk-high)", lineHeight: 1.55 }}>{verdict.blockedReason}</p>
          </div>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 9, padding: "7px 14px", borderRadius: 5, background: risk.bg }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: risk.color, flexShrink: 0 }} />
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.09em", textTransform: "uppercase", color: risk.color }}>{risk.label}</span>
          </div>
          <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
            {counts.critical > 0 && <span style={{ fontSize: 13, color: "var(--risk-high)", fontWeight: 500 }}>{counts.critical} critical</span>}
            {counts.high     > 0 && <span style={{ fontSize: 13, color: "var(--risk-high)" }}>{counts.high} high</span>}
            {counts.medium   > 0 && <span style={{ fontSize: 13, color: "var(--risk-medium)" }}>{counts.medium} warning{counts.medium !== 1 ? "s" : ""}</span>}
            {counts.low      > 0 && <span style={{ fontSize: 13, color: "var(--text-3)" }}>{counts.low} low</span>}
          </div>
        </div>
      </div>

      {/* ── Tab bar ── */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border)", marginBottom: 48 }}>
        {[
          { key: "analysis", label: "Analysis" },
          { key: "document", label: `Document${readerFindings.length > 0 ? ` · ${readerFindings.length} findings` : ""}` },
        ].map(({ key, label }) => (
          <button key={key} onClick={() => setActiveTab(key)} style={{ padding: "9px 18px", fontSize: 13, fontWeight: 500, color: activeTab === key ? "var(--text)" : "var(--text-2)", background: "none", border: "none", borderBottom: activeTab === key ? "2px solid var(--text)" : "2px solid transparent", marginBottom: -1, cursor: "pointer", transition: "all 0.15s" }}>
            {label}
          </button>
        ))}
      </div>

      {/* ── Document tab ── */}
      {activeTab === "document" && (
        <div style={{ animation: "fadeIn 0.3s ease" }}>
          {ContractReaderComponent && selectedRunId ? (
            <ContractReaderComponent
              runId={selectedRunId}
              findings={readerFindings}
              contractId={selectedContractId}
              filename={fileName}
              currentUserName={currentUser?.display_name || currentUser?.full_name || "Unknown"}
            />
          ) : (
            <div style={{ padding: "48px 0", color: "var(--text-3)", fontSize: 14 }}>Document viewer not available.</div>
          )}
        </div>
      )}

      {/* ── Analysis tab ── */}
      {activeTab === "analysis" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 80, alignItems: "start" }}>

          {/* ── LEFT ── */}
          <div>

            {/* Executive Summary */}
            <div style={{ marginBottom: 60 }}>
              <SectionLabel>Executive Summary</SectionLabel>
              <p style={{ fontSize: 15, color: "var(--text)", lineHeight: 1.75, maxWidth: 580 }}>{verdict.summary}</p>
            </div>

            {/* Flagged Clauses */}
            <div style={{ marginBottom: 60 }}>
              <SectionLabel>Flagged Clauses &amp; Risks</SectionLabel>
              <div>
                {verdict.findings.length === 0 && (
                  <p style={{ fontSize: 14, color: "var(--text-3)" }}>No findings for this contract.</p>
                )}
                {verdict.findings.map((f, i) => {
                  const cfg  = verdictSeverityConfig[f.severity] ?? verdictSeverityConfig.low;
                  const open = expandedIdx === i;
                  return (
                    <div key={f.id} style={{ borderBottom: "1px solid var(--border-light)" }}>
                      <button onClick={() => setExpandedIdx(open ? null : i)} style={{ display: "flex", alignItems: "flex-start", gap: 14, width: "100%", padding: "17px 0", textAlign: "left", background: "none", border: "none", cursor: "pointer" }}>
                        <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: "0.09em", textTransform: "uppercase", color: cfg.color, background: cfg.bg, padding: "3px 8px", borderRadius: 4, flexShrink: 0, marginTop: 1 }}>{cfg.label}</span>
                        <span style={{ flex: 1, fontSize: 14, fontWeight: 500, color: "var(--text)", lineHeight: 1.5 }}>{f.title}</span>
                        <span style={{ flexShrink: 0, color: "var(--text-3)", transform: open ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s", marginTop: 2 }}><IconChevronDown /></span>
                      </button>
                      {open && (
                        <div style={{ paddingBottom: 22, paddingLeft: 80, animation: "fadeIn 0.2s ease" }}>
                          <blockquote style={{ borderLeft: `2px solid ${cfg.color}`, paddingLeft: 16, marginBottom: 16, fontSize: 13, fontStyle: "italic", color: "var(--text-2)", lineHeight: 1.75 }}>"{f.quote}"</blockquote>
                          {f.recommendation && (
                            <div style={{ display: "flex", gap: 10, padding: "12px 16px", background: "var(--hover-bg)", borderRadius: 6 }}>
                              <span style={{ color: "var(--accent)", fontSize: 13, flexShrink: 0 }}>→</span>
                              <p style={{ fontSize: 13, color: "var(--text)", lineHeight: 1.65 }}>{f.recommendation}</p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

          </div>

          {/* ── RIGHT (sticky) ── */}
          <div style={{ position: "sticky", top: 72, display: "flex", flexDirection: "column", gap: 40 }}>

            {/* Sign-off panel */}
            {!approved && (
              <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 24, background: "var(--surface)" }}>
                <SectionLabel style={{ marginBottom: 12 }}>Sign-off Required</SectionLabel>
                <p style={{ fontSize: 13, color: "var(--text-2)", marginBottom: 22, lineHeight: 1.65 }}>Your decision finalizes this review and notifies all relevant stakeholders.</p>
                {!rejectMode ? (
                  <div style={{ display: "flex", gap: 8 }}>
                    <button onClick={() => setRejectMode(true)} style={{ flex: 1, padding: "9px 14px", borderRadius: 7, border: "1px solid var(--border)", fontSize: 13, fontWeight: 500, color: "var(--text)", background: "none", cursor: "pointer", transition: "all 0.15s" }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--risk-high)"; e.currentTarget.style.color = "var(--risk-high)"; }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--text)"; }}>Reject</button>
                    <button onClick={async () => { if (selectedRunId) await window.verdictApi.submitHumanReview(selectedRunId, "approved"); setApproved(true); onApprove && setTimeout(onApprove, 800); }} style={{ flex: 1, padding: "9px 14px", borderRadius: 7, background: "var(--accent)", color: "white", fontSize: 13, fontWeight: 600, border: "none", cursor: "pointer", transition: "opacity 0.15s" }}
                      onMouseEnter={e => e.currentTarget.style.opacity = "0.85"}
                      onMouseLeave={e => e.currentTarget.style.opacity = "1"}>Approve</button>
                  </div>
                ) : (
                  <div style={{ animation: "fadeIn 0.2s ease" }}>
                    <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--risk-high)", marginBottom: 8 }}>Reason for rejection</p>
                    <textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)} rows={3} placeholder="Describe why this contract cannot be approved…"
                      style={{ width: "100%", padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 6, fontSize: 13, lineHeight: 1.6, resize: "vertical", background: "var(--bg)", color: "var(--text)", outline: "none", marginBottom: 10, fontFamily: "var(--font-sans)" }} />
                    <div style={{ display: "flex", gap: 8 }}>
                      <button onClick={() => setRejectMode(false)} style={{ flex: 1, padding: "8px", borderRadius: 7, border: "1px solid var(--border)", fontSize: 13, color: "var(--text-2)", background: "none", cursor: "pointer" }}>Cancel</button>
                      <button onClick={async () => { if (selectedRunId) await window.verdictApi.submitHumanReview(selectedRunId, "rejected", rejectReason); onReject && onReject(rejectReason); }} style={{ flex: 1, padding: "8px", borderRadius: 7, background: "var(--risk-high)", color: "white", fontSize: 13, fontWeight: 600, border: "none", cursor: "pointer" }}>Confirm</button>
                    </div>
                  </div>
                )}
              </div>
            )}
            {approved && (
              <div style={{ border: "1px solid var(--risk-low)", borderRadius: 10, padding: 24, background: "rgba(61,139,94,0.06)", animation: "fadeIn 0.3s ease" }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <span style={{ color: "var(--risk-low)" }}><IconCheck size={16} /></span>
                  <p style={{ fontSize: 14, fontWeight: 600, color: "var(--risk-low)" }}>Contract Approved</p>
                </div>
                <p style={{ fontSize: 13, color: "var(--text-2)", marginTop: 8 }}>Your approval has been recorded. All stakeholders have been notified.</p>
              </div>
            )}

            {/* Next Steps */}
            <div>
              <SectionLabel>Next Steps</SectionLabel>
              <div>
                {[
                  { label: "Export Contract",  desc: "Download the source contract PDF", accent: false, action: "export" },
                ].map(({ label, desc, accent, action }) => (
                  <button key={label}
                    onClick={() => {
                      if (action === "export" && selectedRunId) {
                        const url = window.verdictApi.getRunFileUrl(selectedRunId);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = fileName;
                        a.click();
                      }
                    }}
                    style={{ display: "flex", alignItems: "center", gap: 12, width: "100%", padding: "12px 0", borderBottom: "1px solid var(--border-light)", textAlign: "left", background: "none", border: "none", cursor: "pointer", transition: "padding-left 0.15s" }}
                    onMouseEnter={e => e.currentTarget.style.paddingLeft = "5px"}
                    onMouseLeave={e => e.currentTarget.style.paddingLeft = "0"}>
                    <div style={{ flex: 1 }}>
                      <p style={{ fontSize: 13, fontWeight: 500, color: accent ? "var(--accent)" : "var(--text)", marginBottom: 2 }}>{label}</p>
                      <p style={{ fontSize: 11, color: "var(--text-3)" }}>{desc}</p>
                    </div>
                    <span style={{ color: "var(--text-3)", flexShrink: 0 }}><IconArrowRight size={13} /></span>
                  </button>
                ))}
              </div>
            </div>

            {/* Real comments */}
            {selectedRunId && <CommentsPanel runId={selectedRunId} />}

          </div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { VerdictScreen, verdictSeverityConfig, verdictRiskConfig });
