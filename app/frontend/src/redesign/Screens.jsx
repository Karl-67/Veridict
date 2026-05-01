
// ── Dashboard Screen ──────────────────────────────────────────────────────────

function DashboardScreen({ navigate }) {
  const [filter, setFilter] = React.useState("all");
  const [contracts, setContracts] = React.useState([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    window.verdictApi.listContracts()
      .then(data => { if (active) setContracts(data); })
      .catch(() => { if (active) setContracts([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const IN_PROGRESS_STATES = ["created", "processing", "under_review"];

  const total     = contracts.length;
  const awaiting  = contracts.filter(c => c.latestRunState === "awaiting_human_review").length;
  const inProg    = contracts.filter(c => IN_PROGRESS_STATES.includes(c.latestRunState)).length;
  const finalized = contracts.filter(c => c.latestRunState === "finalized").length;

  const filtered = filter === "all"      ? contracts
    : filter === "review"   ? contracts.filter(c => c.latestRunState === "awaiting_human_review")
    : filter === "progress" ? contracts.filter(c => IN_PROGRESS_STATES.includes(c.latestRunState))
    : contracts.filter(c => c.latestRunState === "finalized");

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 80, animation: "fadeIn 0.35s ease both" }}>
      {/* Page header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 40 }}>
        <div>
          <p style={{ fontSize: 13, color: "var(--text-3)", marginBottom: 6 }}>{greeting()}, {(window.verdictApi.currentUser()?.display_name || "").split(" ")[0] || "there"}</p>
          <h1 style={{ fontFamily: "var(--h-font)", fontSize: 42, fontWeight: 700, letterSpacing: "-0.025em", color: "var(--text)", lineHeight: 1 }}>Contracts</h1>
        </div>
        <button onClick={() => navigate("new_contract")} style={{ display: "flex", alignItems: "center", gap: 7, padding: "9px 18px", borderRadius: 8, background: "var(--text)", color: "var(--bg)", fontSize: 13, fontWeight: 600, border: "none", cursor: "pointer", transition: "opacity 0.15s", flexShrink: 0 }}
          onMouseEnter={e => e.currentTarget.style.opacity = "0.82"}
          onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
          <IconPlus /><span>New Contract</span>
        </button>
      </div>

      {/* Stats bar */}
      <div style={{ display: "flex", gap: 0, marginBottom: 0, borderBottom: "1px solid var(--border)" }}>
        {[
          { label: "Total",           value: total,     f: "all",      color: null },
          { label: "Awaiting Review", value: awaiting,  f: "review",   color: awaiting  > 0 ? "var(--accent)"   : null },
          { label: "In Progress",     value: inProg,    f: "progress", color: inProg    > 0 ? "var(--text-2)"   : null },
          { label: "Finalized",       value: finalized, f: "done",     color: finalized > 0 ? "var(--risk-low)" : null },
        ].map(({ label, value, f, color }, i) => (
          <button key={f} onClick={() => setFilter(f)} style={{ display: "flex", alignItems: "baseline", gap: 7, paddingBottom: 18, paddingRight: 32, paddingTop: 4, background: "none", border: "none", cursor: "pointer", opacity: filter !== "all" && filter !== f ? 0.35 : 1, transition: "opacity 0.2s", borderBottom: filter === f ? "2px solid var(--text)" : "2px solid transparent", marginBottom: -1 }}>
            <span style={{ fontFamily: "var(--font-serif)", fontSize: 30, fontWeight: 700, lineHeight: 1, color: color ?? "var(--text)" }}>{value}</span>
            <span style={{ fontSize: 12, color: "var(--text-2)", paddingBottom: 2 }}>{label}</span>
          </button>
        ))}
      </div>

      {loading && (
        <div style={{ padding: "60px 0", color: "var(--text-3)", fontSize: 14 }}>Loading contracts…</div>
      )}

      {/* Table header */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 76px 164px 96px 96px 32px", gap: "0 16px", padding: "13px 10px", borderBottom: "1px solid var(--border)" }}>
        {["Contract", "Version", "Status", "Risk", "Updated", ""].map(h => (
          <span key={h} style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-3)" }}>{h}</span>
        ))}
      </div>

      {/* Rows */}
      {!loading && filtered.map((c, i) => {
        const status   = stateLabel(c.latestRunState);
        const isAction = c.latestRunState === "awaiting_human_review";
        const isProc   = IN_PROGRESS_STATES.includes(c.latestRunState);
        return (
          <div key={c.id} onClick={() => navigate("contract_detail", c.id)}
            style={{ display: "grid", gridTemplateColumns: "1fr 76px 164px 96px 96px 32px", gap: "0 16px", padding: "15px 10px", borderBottom: "1px solid var(--border-light)", cursor: "pointer", transition: "background 0.1s", animation: `fadeIn 0.3s ${i * 0.04}s both` }}
            onMouseEnter={e => e.currentTarget.style.background = "var(--hover-bg)"}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
            {/* Name */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: isAction ? "var(--accent)" : isProc ? "var(--accent)" : "transparent", border: isAction || isProc ? "none" : "1.5px solid var(--border)" }} className={isProc ? "pulse" : ""} />
              <div style={{ minWidth: 0 }}>
                <p style={{ fontSize: 13.5, fontWeight: 500, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</p>
                <p style={{ fontSize: 11, color: "var(--text-3)", marginTop: 1 }}>{c.versionCount} version{c.versionCount !== 1 ? "s" : ""} · {c.workspace}</p>
              </div>
            </div>
            {/* Version */}
            <div style={{ display: "flex", alignItems: "center" }}>
              <span style={{ fontSize: 11.5, fontFamily: "monospace", fontWeight: 700, color: "var(--text)", background: "var(--border-light)", padding: "2px 7px", borderRadius: 4 }}>{c.latestLabel}</span>
            </div>
            {/* Status */}
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ fontSize: 13, color: status.color }}>{status.text}{isProc ? "…" : ""}</span>
              {isAction && <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", background: "var(--accent)", color: "white", padding: "1px 6px", borderRadius: 4 }}>Action</span>}
            </div>
            {/* Risk */}
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {c.latestRisk
                ? <><span style={{ width: 7, height: 7, borderRadius: 1.5, flexShrink: 0, background: riskColor(c.latestRisk) }} /><span style={{ fontSize: 13, color: riskColor(c.latestRisk) }}>{riskLabel(c.latestRisk)}</span></>
                : <span style={{ color: "var(--text-3)", fontSize: 13 }}>—</span>}
            </div>
            {/* Updated */}
            <div style={{ display: "flex", alignItems: "center" }}>
              <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>{timeAgo(c.updatedAt)}</span>
            </div>
            {/* Arrow */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", color: "var(--text-3)" }}><IconArrowRight /></div>
          </div>
        );
      })}

      {filtered.length === 0 && (
        <div style={{ textAlign: "center", padding: "80px 0", color: "var(--text-3)" }}>
          <p style={{ fontSize: 14 }}>No contracts match this filter.</p>
        </div>
      )}
    </div>
  );
}

// ── Contract Detail Screen ────────────────────────────────────────────────────

function ContractDetailScreen({ navigate, selectedContractId, onViewRun, onAddVersion }) {
  const [detail, setDetail]   = React.useState(null);
  const [loadErr, setLoadErr] = React.useState(false);
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [versionFile, setVersionFile] = React.useState(null);

  React.useEffect(() => {
    if (!selectedContractId) return;
    let active = true;
    setDetail(null); setLoadErr(false);
    window.verdictApi.getContract(selectedContractId)
      .then(data => {
        if (!active) return;
        setDetail(data);
        // Load real finding counts for versions that have a run
        const versionsWithRun = data.versions.filter(v => v.runId);
        if (versionsWithRun.length === 0) return;
        Promise.all(
          versionsWithRun.map(v =>
            window.verdictApi.getRunFindings(v.runId)
              .then(f => ({ runId: v.runId, count: f.length }))
              .catch(() => ({ runId: v.runId, count: 0 }))
          )
        ).then(results => {
          if (!active) return;
          const counts = {};
          results.forEach(r => { counts[r.runId] = r.count; });
          setDetail(prev => prev ? {
            ...prev,
            versions: prev.versions.map(v => ({
              ...v,
              findingCount: v.runId != null ? (counts[v.runId] ?? v.findingCount) : v.findingCount,
            })),
          } : prev);
        });
      })
      .catch(() => { if (active) setLoadErr(true); });
    return () => { active = false; };
  }, [selectedContractId]);

  if (loadErr) {
    return (
      <div style={{ paddingTop: "var(--density-pad)", color: "var(--text-3)", display: "flex", flexDirection: "column", gap: 12 }}>
        <p style={{ fontSize: 14 }}>Could not load contract.</p>
        <button onClick={() => navigate("dashboard")} style={{ fontSize: 13, color: "var(--text-2)", background: "none", border: "none", cursor: "pointer", textAlign: "left" }}>← Back to Dashboard</button>
      </div>
    );
  }
  if (!detail) {
    return <div style={{ paddingTop: "var(--density-pad)", color: "var(--text-3)" }}>Loading contract…</div>;
  }

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 80, animation: "fadeIn 0.35s ease both" }}>
      {/* Back */}
      <button onClick={() => navigate("dashboard")} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-2)", marginBottom: 36, border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" }}
        onMouseEnter={e => e.currentTarget.style.color = "var(--text)"}
        onMouseLeave={e => e.currentTarget.style.color = "var(--text-2)"}>
        <IconArrowLeft />All Contracts
      </button>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 52 }}>
        <div>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 10 }}>{detail.workspace} · Contract</p>
          <h1 style={{ fontFamily: "var(--h-font)", fontSize: 36, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--text)", maxWidth: 620, lineHeight: 1.2 }}>{detail.name}</h1>
        </div>
        <button onClick={() => setUploadOpen(v => !v)} style={{ display: "flex", alignItems: "center", gap: 7, padding: "8px 16px", borderRadius: 7, border: "1px solid var(--border)", fontSize: 13, fontWeight: 500, color: "var(--text)", background: "none", cursor: "pointer", transition: "all 0.12s", flexShrink: 0, marginTop: 6 }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--text-3)"; e.currentTarget.style.background = "var(--hover-bg)"; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.background = "none"; }}>
          <IconPlus size={11} />Add Version
        </button>
      </div>

      {/* Upload inline panel */}
      {uploadOpen && (
        <div style={{ border: "1px dashed var(--border)", borderRadius: 8, padding: "28px 28px", marginBottom: 40, animation: "fadeIn 0.2s ease", display: "flex", gap: 24, alignItems: "center" }}>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 13, fontWeight: 500, color: "var(--text)", marginBottom: 4 }}>Drop a new version to analyze</p>
            <p style={{ fontSize: 12, color: "var(--text-3)" }}>PDF or DOCX · Max 50 MB</p>
          </div>
          <input type="file" accept=".pdf,.doc,.docx" onChange={e => setVersionFile(e.target.files?.[0] ?? null)} style={{ fontSize: 12, color: "var(--text-2)" }} />
          <button onClick={() => { if (versionFile) { setUploadOpen(false); onAddVersion(versionFile); } }} style={{ padding: "8px 18px", borderRadius: 7, background: versionFile ? "var(--text)" : "var(--border-light)", color: versionFile ? "var(--bg)" : "var(--text-3)", fontSize: 13, fontWeight: 600, border: "none", cursor: versionFile ? "pointer" : "not-allowed", flexShrink: 0 }}>Upload &amp; Analyze</button>
          <button onClick={() => setUploadOpen(false)} style={{ padding: "8px 14px", borderRadius: 7, border: "1px solid var(--border)", fontSize: 13, color: "var(--text-2)", background: "none", cursor: "pointer", flexShrink: 0 }}>Cancel</button>
        </div>
      )}

      {/* Version table */}
      <div>
        <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 20 }}>Version History</p>
        <div style={{ display: "grid", gridTemplateColumns: "72px 1fr 144px 96px 120px 100px", gap: "0 16px", padding: "0 0 11px", borderBottom: "1px solid var(--border)" }}>
          {["Version", "File", "Status", "Risk", "Findings", ""].map(h => (
            <span key={h} style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-3)" }}>{h}</span>
          ))}
        </div>
        {detail.versions.map((v, i) => {
          const status = stateLabel(v.runState);
          const isLatest = i === 0;
          return (
            <div key={v.id} style={{ display: "grid", gridTemplateColumns: "72px 1fr 144px 96px 120px 100px", gap: "0 16px", padding: "17px 0", borderBottom: "1px solid var(--border-light)", animation: `fadeIn 0.3s ${i * 0.07}s both`, alignItems: "center" }}>
              <div>
                <span style={{ fontSize: 11.5, fontFamily: "monospace", fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: isLatest ? "rgba(200,151,62,0.12)" : "var(--border-light)", color: isLatest ? "var(--accent)" : "var(--text)" }}>{v.label}</span>
              </div>
              <p style={{ fontSize: 13, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v.filename}</p>
              <span style={{ fontSize: 13, color: status.color }}>{status.text}</span>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {v.risk ? <><span style={{ width: 7, height: 7, borderRadius: 1.5, background: riskColor(v.risk), flexShrink: 0 }} /><span style={{ fontSize: 13, color: riskColor(v.risk) }}>{riskLabel(v.risk)}</span></> : <span style={{ color: "var(--text-3)" }}>—</span>}
              </div>
              <span style={{ fontSize: 13, color: "var(--text-2)" }}>{v.findingCount} finding{v.findingCount !== 1 ? "s" : ""}</span>
              <div style={{ textAlign: "right" }}>
                {v.runId && (
                  <button onClick={() => onViewRun(v.runId)} style={{ fontSize: 12, fontWeight: 500, color: "var(--accent)", textDecoration: "underline", textUnderlineOffset: 3, border: "none", background: "none", cursor: "pointer" }}>View Report →</button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── New Contract Screen ───────────────────────────────────────────────────────

function NewContractScreen({ navigate, onSubmit }) {
  const [name, setName]       = React.useState("");
  const [file, setFile]       = React.useState(null);
  const [dragging, setDrag]   = React.useState(false);
  const fileRef               = React.useRef(null);
  const canSubmit             = name.trim() && file;

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 80, maxWidth: 600, animation: "fadeIn 0.35s ease both" }}>
      <button onClick={() => navigate("dashboard")} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-2)", marginBottom: 36, border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" }}
        onMouseEnter={e => e.currentTarget.style.color = "var(--text)"}
        onMouseLeave={e => e.currentTarget.style.color = "var(--text-2)"}>
        <IconArrowLeft />All Contracts
      </button>

      <h1 style={{ fontFamily: "var(--h-font)", fontSize: 38, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--text)", marginBottom: 8 }}>New Contract</h1>
      <p style={{ fontSize: 14, color: "var(--text-2)", marginBottom: 48, lineHeight: 1.6 }}>Name your contract and upload the first version for AI-powered risk analysis.</p>

      <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
        {/* Name */}
        <div>
          <label style={{ display: "block", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 9 }}>Contract Name</label>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Master Services Agreement, Vendor NDA, Employment Contract"
            style={{ width: "100%", padding: "11px 15px", border: "1px solid var(--border)", borderRadius: 7, fontSize: 14, color: "var(--text)", background: "var(--surface)", outline: "none", transition: "border-color 0.15s" }}
            onFocus={e => e.target.style.borderColor = "var(--text-2)"}
            onBlur={e => e.target.style.borderColor = "var(--border)"} />
        </div>

        {/* Drop zone */}
        <div>
          <label style={{ display: "block", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 9 }}>Document</label>
          <div onClick={() => fileRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={e => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) setFile(f); }}
            style={{ border: `1px dashed ${dragging ? "var(--accent)" : file ? "var(--risk-low)" : "var(--border)"}`, borderRadius: 8, padding: "44px 28px", textAlign: "center", cursor: "pointer", background: dragging ? "rgba(200,151,62,0.03)" : "transparent", transition: "all 0.15s" }}>
            <input ref={fileRef} type="file" accept=".pdf,.doc,.docx" style={{ display: "none" }} onChange={e => setFile(e.target.files[0])} />
            {file ? (
              <div>
                <p style={{ fontSize: 14, fontWeight: 500, color: "var(--risk-low)", marginBottom: 4 }}>{file.name}</p>
                <p style={{ fontSize: 12, color: "var(--text-3)" }}>{(file.size / 1024 / 1024).toFixed(2)} MB · Click to replace</p>
              </div>
            ) : (
              <div>
                <p style={{ fontSize: 14, color: "var(--text-2)", marginBottom: 5 }}>Drop PDF or DOCX here</p>
                <p style={{ fontSize: 12, color: "var(--text-3)" }}>or click to browse files</p>
              </div>
            )}
          </div>
        </div>

        {/* Submit */}
        <button onClick={() => canSubmit && onSubmit(name, file)} style={{ padding: "12px 24px", borderRadius: 8, background: canSubmit ? "var(--text)" : "var(--border-light)", color: canSubmit ? "var(--bg)" : "var(--text-3)", fontSize: 14, fontWeight: 600, border: "none", cursor: canSubmit ? "pointer" : "not-allowed", transition: "all 0.15s" }}
          onMouseEnter={e => { if (canSubmit) e.currentTarget.style.opacity = "0.82"; }}
          onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
          Analyze Contract
        </button>
      </div>
    </div>
  );
}

// ── Processing Screen ─────────────────────────────────────────────────────────

const STAGE_LABELS = {
  create_run:             "Creating Run",
  ingest_pdf:             "Document Ingestion",
  parse_ocr_normalize:    "Parsing & OCR",
  clause_index:           "Clause Indexing",
  harvey_context_load:    "Loading Policy Context",
  harvey_review_block:    "Policy Review",
  kira_review_block:      "Compliance Review",
  admin_merge:            "Merging Analysis",
  final_review_block:     "Final Review",
  awaiting_human_review:  "Ready for Human Review",
};

const DISPLAY_STAGE_NAMES = [
  "ingest_pdf",
  "parse_ocr_normalize",
  "clause_index",
  "harvey_context_load",
  "kira_review_block",
  "admin_merge",
  "awaiting_human_review",
];

function ProcessingScreen({ navigate, fileName, pendingError, processingRunId, selectedContractId }) {
  const [runStages, setRunStages] = React.useState([]);
  const [runState, setRunState]   = React.useState(null);

  React.useEffect(() => {
    if (!processingRunId) return;
    let active = true;

    async function poll() {
      try {
        const run = await window.verdictApi.getRun(processingRunId);
        if (!active) return;
        setRunState(run.state);
        setRunStages(run.stages ?? []);
        const done = ["awaiting_human_review", "finalized", "failed", "blocked"].includes(run.state);
        if (done) {
          setTimeout(() => { if (active) navigate("contract_detail", run.contract_id ?? selectedContractId); }, 800);
        } else {
          setTimeout(poll, 3000);
        }
      } catch {
        if (active) setTimeout(poll, 5000);
      }
    }

    poll();
    return () => { active = false; };
  }, [processingRunId]);

  // Build display list from real backend stage data
  const stageMap = {};
  runStages.forEach(s => { stageMap[s.stage_name] = s.state; });

  const displayStages = DISPLAY_STAGE_NAMES.map(name => {
    const state = stageMap[name] ?? "pending";
    return { name, label: STAGE_LABELS[name] ?? name, state };
  });

  const doneCount  = displayStages.filter(s => s.state === "done").length;
  const totalCount = displayStages.length;
  const pct        = Math.round((doneCount / totalCount) * 100);

  const isFailed  = runState === "failed" || runState === "blocked";
  const isReady   = runState === "awaiting_human_review" || runState === "finalized";

  return (
    <div style={{ paddingTop: "var(--density-pad)", paddingBottom: 80, maxWidth: 520, margin: "0 auto", animation: "fadeIn 0.35s ease both" }}>
      <div style={{ textAlign: "center", marginBottom: 56 }}>
        <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.14em", color: "var(--text-3)", marginBottom: 14 }}>Analysis in Progress</p>
        <h1 style={{ fontFamily: "var(--h-font)", fontSize: 34, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--text)", marginBottom: 10 }}>Processing your contract</h1>
        <p style={{ fontSize: 14, color: "var(--text-2)" }}>{fileName || "Your document"} is being analyzed by the AI engine.</p>
        {pendingError && <p style={{ marginTop: 14, fontSize: 13, color: "var(--risk-high)" }}>{pendingError}</p>}
        {isReady && <p style={{ marginTop: 14, fontSize: 13, color: "var(--risk-low)" }}>Analysis complete — redirecting…</p>}
        {isFailed && <p style={{ marginTop: 14, fontSize: 13, color: "var(--risk-high)" }}>Analysis encountered an error.</p>}
      </div>

      {/* Stage list */}
      <div style={{ marginBottom: 40 }}>
        {displayStages.map((stage, i) => {
          const isDone    = stage.state === "done";
          const isRunning = stage.state === "running" || stage.state === "retrying";
          const isFail    = stage.state === "failed" || stage.state === "blocked";
          return (
            <div key={stage.name} style={{ display: "flex", alignItems: "center", gap: 16, padding: "13px 0", borderBottom: i < displayStages.length - 1 ? "1px solid var(--border-light)" : "none", opacity: stage.state === "pending" ? 0.28 : 1, transition: "opacity 0.4s" }}>
              <div style={{ width: 22, height: 22, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
                {isDone ? (
                  <span style={{ color: "var(--risk-low)" }}><IconCheck size={16} /></span>
                ) : isFail ? (
                  <span style={{ fontSize: 13, color: "var(--risk-high)" }}>✕</span>
                ) : isRunning ? (
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--accent)", display: "block" }} className="pulse" />
                ) : (
                  <span style={{ width: 7, height: 7, borderRadius: "50%", border: "1.5px solid var(--border)", display: "block" }} />
                )}
              </div>
              <span style={{ fontSize: 14, fontWeight: isRunning ? 600 : 400, color: isRunning ? "var(--text)" : isDone ? "var(--text-2)" : isFail ? "var(--risk-high)" : "var(--text-3)", transition: "color 0.3s" }}>{stage.label}</span>
              <span style={{ marginLeft: "auto", fontSize: 11, color: isDone ? "var(--text-3)" : isRunning ? "var(--accent)" : isFail ? "var(--risk-high)" : "transparent", transition: "color 0.3s" }}>
                {isDone ? "Done" : isRunning ? "Running" : isFail ? "Failed" : "—"}
              </span>
            </div>
          );
        })}
      </div>

      {/* Progress bar */}
      <div style={{ height: 2, background: "var(--border)", borderRadius: 1, marginBottom: 32, overflow: "hidden" }}>
        <div style={{ height: "100%", background: isFailed ? "var(--risk-high)" : "var(--accent)", borderRadius: 1, width: `${pct}%`, transition: "width 1s ease" }} />
      </div>

      <div style={{ textAlign: "center" }}>
        <p style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 12 }}>This may take a few minutes depending on document length.</p>
        <button onClick={() => navigate("dashboard")} style={{ fontSize: 13, color: "var(--text-3)", textDecoration: "underline", textUnderlineOffset: 3, border: "none", background: "none", cursor: "pointer", transition: "color 0.12s" }}
          onMouseEnter={e => e.currentTarget.style.color = "var(--text-2)"}
          onMouseLeave={e => e.currentTarget.style.color = "var(--text-3)"}>
          Run in background — go to dashboard
        </button>
      </div>
    </div>
  );
}

Object.assign(window, { DashboardScreen, ContractDetailScreen, NewContractScreen, ProcessingScreen });
