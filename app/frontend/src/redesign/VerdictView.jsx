
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

const BENCHMARKS = [
  { metric: "Liability Cap",      document: "Unlimited",        flag: true,  industry: "100% of fees", firm: "100% of fees" },
  { metric: "Termination Notice", document: "90 days",          flag: true,  industry: "45 days",      firm: "30 days"      },
  { metric: "Non-compete Scope",  document: "5 yrs, global",    flag: true,  industry: "1 yr, region", firm: "2 yrs, region"},
  { metric: "Governing Law",      document: "Ambiguous",        flag: true,  industry: "Specified",    firm: "New York"     },
  { metric: "Warranty Period",    document: "12 months",        flag: false, industry: "6 months",     firm: "12 months"    },
];

function SectionLabel({ children, style = {} }) {
  return (
    <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.14em", color: "var(--text-3)", marginBottom: 20, ...style }}>{children}</p>
  );
}

function VerdictScreen({ navigate, selectedContractId, selectedRunId, onApprove, onReject }) {
  const [verdict, setVerdict]         = React.useState(null);
  const [loadErr, setLoadErr]         = React.useState(false);
  const [fileName, setFileName]       = React.useState("Contract analysis report.pdf");
  const [expandedIdx, setExpandedIdx] = React.useState(null);
  const [rejectMode, setRejectMode]   = React.useState(false);
  const [rejectReason, setRejectReason] = React.useState("");
  const [approved, setApproved]       = React.useState(false);

  React.useEffect(() => {
    if (!selectedRunId) { setVerdict(null); return; }
    let active = true;
    setVerdict(null); setLoadErr(false);
    window.verdictApi.getRun(selectedRunId).then(async run => {
      if (!active) return;
      setFileName(run.filename || "Contract analysis report.pdf");
      const findings = run.verdict?.findings ?? await window.verdictApi.getRunFindings(selectedRunId).catch(() => []);
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
        alignmentScore: Math.max(35, 100 - findings.length * 8),
        recommendations: run.verdict?.recommendations ?? [],
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

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 100, animation: "fadeIn 0.4s ease both" }}>

      {/* Back */}
      <button onClick={() => navigate(backTarget, selectedContractId)} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-2)", marginBottom: 36, border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" }}
        onMouseEnter={e => e.currentTarget.style.color = "var(--text)"}
        onMouseLeave={e => e.currentTarget.style.color = "var(--text-2)"}>
        <IconArrowLeft />{backLabel}
      </button>

      {/* ── Report header ─────────────────────────────────────────────────────── */}
      <div style={{ borderBottom: "1px solid var(--border)", paddingBottom: 40, marginBottom: 64 }}>
        <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.14em", color: "var(--text-3)", marginBottom: 14 }}>
          Contract Analysis Report · {new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
        </p>
        <h1 style={{ fontFamily: "var(--h-font)", fontSize: 38, fontWeight: 700, letterSpacing: "-0.025em", color: "var(--text)", marginBottom: 24, maxWidth: 660, lineHeight: 1.2 }}>{fileName}</h1>

        <div style={{ display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
          {/* Risk badge */}
          <div style={{ display: "inline-flex", alignItems: "center", gap: 9, padding: "7px 14px", borderRadius: 5, background: risk.bg }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: risk.color, flexShrink: 0 }} />
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.09em", textTransform: "uppercase", color: risk.color }}>{risk.label}</span>
          </div>
          {/* Finding counts */}
          <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
            {counts.critical > 0 && <span style={{ fontSize: 13, color: "var(--risk-high)", fontWeight: 500 }}>{counts.critical} critical</span>}
            {counts.medium   > 0 && <span style={{ fontSize: 13, color: "var(--risk-medium)" }}>{counts.medium} warning{counts.medium !== 1 ? "s" : ""}</span>}
            {counts.low      > 0 && <span style={{ fontSize: 13, color: "var(--text-3)" }}>{counts.low} low</span>}
          </div>
          {/* Alignment */}
          <div style={{ marginLeft: "auto" }}>
            <span style={{ fontSize: 13, color: "var(--text-3)" }}>Policy alignment: </span>
            <span style={{ fontSize: 13, fontWeight: 600, color: verdict.alignmentScore >= 70 ? "var(--risk-low)" : verdict.alignmentScore >= 50 ? "var(--risk-medium)" : "var(--risk-high)" }}>{verdict.alignmentScore}%</span>
          </div>
        </div>
      </div>

      {/* ── Two-column layout ──────────────────────────────────────────────────── */}
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

          {/* Compliance Benchmarking */}
          <div style={{ marginBottom: 60 }}>
            <SectionLabel>Compliance Benchmarking</SectionLabel>
            <div style={{ borderTop: "1px solid var(--border)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 140px 130px 130px", gap: "0 16px", padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                {["Metric", "This Document", "Industry Avg", "Firm Standard"].map(h => (
                  <span key={h} style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-3)" }}>{h}</span>
                ))}
              </div>
              {BENCHMARKS.map((row, i) => (
                <div key={row.metric} style={{ display: "grid", gridTemplateColumns: "1fr 140px 130px 130px", gap: "0 16px", padding: "14px 0", borderBottom: "1px solid var(--border-light)", animation: `fadeIn 0.3s ${i * 0.06}s both` }}>
                  <span style={{ fontSize: 13, color: "var(--text)" }}>{row.metric}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    {row.flag && <span style={{ width: 5, height: 5, borderRadius: 1, background: "var(--risk-high)", flexShrink: 0 }} />}
                    <span style={{ fontSize: 13, fontWeight: row.flag ? 600 : 400, color: row.flag ? "var(--risk-high)" : "var(--text)" }}>{row.document}</span>
                  </div>
                  <span style={{ fontSize: 13, color: "var(--text-2)" }}>{row.industry}</span>
                  <span style={{ fontSize: 13, color: "var(--text-2)" }}>{row.firm}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Policy Alignment */}
          <div>
            <SectionLabel>Policy Alignment Score</SectionLabel>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 14 }}>
              <p style={{ fontSize: 13, color: "var(--text-2)" }}>Measured against firm standard of 85%</p>
              <span style={{ fontFamily: "var(--font-serif)", fontSize: 52, fontWeight: 700, lineHeight: 1, color: verdict.alignmentScore >= 70 ? "var(--risk-low)" : verdict.alignmentScore >= 50 ? "var(--risk-medium)" : "var(--risk-high)" }}>{verdict.alignmentScore}<span style={{ fontSize: 28, opacity: 0.7 }}>%</span></span>
            </div>
            <div style={{ height: 2, background: "var(--border)", borderRadius: 1, overflow: "hidden", position: "relative", marginBottom: 8 }}>
              <div style={{ position: "absolute", top: 0, left: 0, height: "100%", background: verdict.alignmentScore >= 70 ? "var(--risk-low)" : verdict.alignmentScore >= 50 ? "var(--risk-medium)" : "var(--risk-high)", borderRadius: 1, width: `${verdict.alignmentScore}%`, transition: "width 1.4s ease", animationName: "slideWidth" }} />
              {/* Firm standard marker */}
              <div style={{ position: "absolute", top: -3, left: "85%", width: 1, height: 8, background: "var(--text-3)", transform: "translateX(-50%)" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <span style={{ fontSize: 10, color: "var(--text-3)" }}>↑ Firm standard: 85%</span>
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

          {/* Immediate Actions */}
          <div>
            <SectionLabel>Immediate Actions</SectionLabel>
            <div>
              {["Negotiate revised terms", "Seek legal counsel", "Request clarification on scope"].map((action, i) => (
                <div key={i} style={{ display: "flex", gap: 14, padding: "11px 0", borderBottom: "1px solid var(--border-light)", alignItems: "flex-start" }}>
                  <span style={{ fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 700, color: "var(--border)", lineHeight: 1.4, flexShrink: 0 }}>{String(i + 1).padStart(2, "0")}</span>
                  <p style={{ fontSize: 13, color: "var(--text)", lineHeight: 1.55, paddingTop: 1 }}>{action}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Next Steps */}
          <div>
            <SectionLabel>Next Steps</SectionLabel>
            <div>
              {[
                { label: "Generate Redline",       desc: "AI-drafted revision with tracked changes", accent: true,  action: "soon"   },
                { label: "Schedule Partner Review", desc: "Book a review session with your team",     accent: false, action: "soon"   },
                { label: "Export Report",           desc: "Download full analysis as PDF",            accent: false, action: "export" },
              ].map(({ label, desc, accent, action }) => {
                const isSoon = action === "soon";
                return (
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
                    disabled={isSoon}
                    style={{ display: "flex", alignItems: "center", gap: 12, width: "100%", padding: "12px 0", borderBottom: "1px solid var(--border-light)", textAlign: "left", background: "none", border: "none", cursor: isSoon ? "default" : "pointer", opacity: isSoon ? 0.45 : 1, transition: "padding-left 0.15s" }}
                    onMouseEnter={e => { if (!isSoon) e.currentTarget.style.paddingLeft = "5px"; }}
                    onMouseLeave={e => e.currentTarget.style.paddingLeft = "0"}>
                    <div style={{ flex: 1 }}>
                      <p style={{ fontSize: 13, fontWeight: 500, color: accent ? "var(--accent)" : "var(--text)", marginBottom: 2 }}>{label}</p>
                      <p style={{ fontSize: 11, color: "var(--text-3)" }}>{isSoon ? "Coming soon" : desc}</p>
                    </div>
                    {!isSoon && <span style={{ color: "var(--text-3)", flexShrink: 0 }}><IconArrowRight size={13} /></span>}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Legal team notes */}
          <div>
            <SectionLabel>Legal Team Notes</SectionLabel>
            <div style={{ border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
              {[{ author: "SJ", text: "Liability clause is a blocker — needs renegotiation before we can sign.", ago: "2h ago" }, { author: "MK", text: "Agreed. I've flagged this to partner review.", ago: "1h ago" }].map((c, i) => (
                <div key={i} style={{ padding: "12px 14px", borderBottom: i < 1 ? "1px solid var(--border-light)" : "none" }}>
                  <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
                    <span style={{ width: 22, height: 22, borderRadius: "50%", background: "var(--accent)", color: "white", fontSize: 9, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, marginTop: 1 }}>{c.author}</span>
                    <div style={{ flex: 1 }}>
                      <p style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.55 }}>{c.text}</p>
                      <p style={{ fontSize: 10, color: "var(--text-3)", marginTop: 4 }}>{c.ago}</p>
                    </div>
                  </div>
                </div>
              ))}
              <div style={{ padding: "10px 14px", borderTop: "1px solid var(--border-light)", display: "flex", gap: 8 }}>
                <input placeholder="Add a note…" style={{ flex: 1, fontSize: 12.5, color: "var(--text)", background: "none", border: "none", outline: "none" }} />
                <button style={{ fontSize: 12, fontWeight: 600, color: "var(--accent)", background: "none", border: "none", cursor: "pointer" }}>Post</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { VerdictScreen, verdictSeverityConfig, verdictRiskConfig });
