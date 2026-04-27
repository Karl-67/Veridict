
// ── Auth Screen ───────────────────────────────────────────────────────────────

function AuthScreen({ onLogin }) {
  const [mode, setMode]       = React.useState("login"); // "login" | "create-org"
  const [email, setEmail]     = React.useState("");
  const [password, setPass]   = React.useState("");
  const [name, setName]       = React.useState("");
  const [orgName, setOrg]     = React.useState("");
  const [jobTitle, setJobTitle] = React.useState("");
  const [dept, setDept]         = React.useState("");
  const [loading, setLoading]   = React.useState(false);
  const [error, setError]       = React.useState(null);

  function submit(e) {
    e.preventDefault();
    if (!email || !password) { setError("Please fill in all required fields."); return; }
    setLoading(true);
    setError(null);
    setTimeout(() => { setLoading(false); onLogin(); }, 900);
  }

  const inputStyle = {
    width: "100%", padding: "11px 14px",
    border: "1px solid var(--border)", borderRadius: 7,
    fontSize: 14, color: "var(--text)", background: "var(--surface)",
    outline: "none", transition: "border-color 0.15s",
    fontFamily: "var(--font-sans)",
  };


  return (
    <div style={{ minHeight: "100vh", display: "grid", gridTemplateColumns: "1fr 1fr", background: "var(--bg)", transition: "background 0.3s" }}>

      {/* ── Left panel — brand ── */}
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", padding: "52px 64px", background: "var(--text)", position: "relative", overflow: "hidden" }}>
        {/* Subtle texture lines */}
        <div style={{ position: "absolute", inset: 0, backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 60px, rgba(255,255,255,0.02) 60px, rgba(255,255,255,0.02) 61px)", pointerEvents: "none" }} />

        <div style={{ position: "relative" }}>
          <p style={{ fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 700, color: "rgba(255,255,255,0.95)", letterSpacing: "-0.01em", marginBottom: 4 }}>Veridict</p>
          <p style={{ fontSize: 12, color: "rgba(255,255,255,0.35)", letterSpacing: "0.06em", textTransform: "uppercase", fontWeight: 600 }}>Contract Intelligence</p>
        </div>

        <div style={{ position: "relative" }}>
          <p style={{ fontFamily: "var(--font-serif)", fontSize: 34, fontWeight: 700, color: "rgba(255,255,255,0.92)", lineHeight: 1.25, letterSpacing: "-0.02em", marginBottom: 40, maxWidth: 360 }}>
            Legal intelligence for firms that move fast.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {[
              "Clause extraction across a wide range of contract types",
              "Policy alignment scoring against your firm's standards",
              "Human-in-the-loop review and sign-off workflows",
              "Full audit trail, version history, and team comments",
            ].map((f, i) => (
              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                <span style={{ width: 6, height: 6, borderRadius: 1.5, background: "var(--accent)", flexShrink: 0, marginTop: 5 }} />
                <p style={{ fontSize: 13.5, color: "rgba(255,255,255,0.52)", lineHeight: 1.6 }}>{f}</p>
              </div>
            ))}
          </div>
        </div>

        <p style={{ position: "relative", fontSize: 11.5, color: "rgba(255,255,255,0.2)" }}>© 2026 Veridict — Legal Intelligence Platform</p>
      </div>

      {/* ── Right panel — form ── */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "60px 72px" }}>
        <div style={{ width: "100%", maxWidth: 360 }}>

          {/* Mode switch */}
          <div style={{ display: "flex", gap: 0, marginBottom: 40, borderBottom: "1px solid var(--border)" }}>
            {[{ key: "login", label: "Sign In" }, { key: "create-org", label: "Create Organisation" }].map(m => (
              <button key={m.key} onClick={() => { setMode(m.key); setError(null); }} style={{ flex: 1, padding: "9px 0", fontSize: 13, fontWeight: 500, color: mode === m.key ? "var(--text)" : "var(--text-2)", background: "none", border: "none", borderBottom: mode === m.key ? "2px solid var(--text)" : "2px solid transparent", marginBottom: -1, cursor: "pointer", transition: "all 0.15s" }}>
                {m.label}
              </button>
            ))}
          </div>

          {mode === "login" && (
            <div style={{ marginBottom: 28 }}>
              <h2 style={{ fontFamily: "var(--h-font)", fontSize: 26, fontWeight: 700, color: "var(--text)", marginBottom: 6, letterSpacing: "-0.01em" }}>Welcome back</h2>
              <p style={{ fontSize: 13.5, color: "var(--text-2)" }}>Sign in to your workspace.</p>
            </div>
          )}
          {mode === "create-org" && (
            <div style={{ marginBottom: 28 }}>
              <h2 style={{ fontFamily: "var(--h-font)", fontSize: 26, fontWeight: 700, color: "var(--text)", marginBottom: 6, letterSpacing: "-0.01em" }}>Get started</h2>
              <p style={{ fontSize: 13.5, color: "var(--text-2)" }}>Create your organisation account.</p>
            </div>
          )}

          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {mode === "create-org" && (
              <>
                <Field label="Organisation Name" value={orgName}  onChange={setOrg}      placeholder="e.g. Meridian Law LLP"  style={inputStyle} />
                <Field label="Your Full Name"    value={name}     onChange={setName}     placeholder="e.g. Sarah Johnson"     style={inputStyle} />
                <Field label="Job Title"         value={jobTitle} onChange={setJobTitle} placeholder="e.g. Senior Associate"  style={inputStyle} />
                <Field label="Department"        value={dept}     onChange={setDept}     placeholder="e.g. Corporate M&A"    style={inputStyle} />
              </>
            )}
            <Field label="Email" type="email" value={email} onChange={setEmail} placeholder="you@firm.com" autoComplete="email" style={inputStyle} />
            <Field label="Password" type="password" value={password} onChange={setPass} placeholder="••••••••" autoComplete={mode === "login" ? "current-password" : "new-password"} style={inputStyle} />

            {error && (
              <div style={{ padding: "10px 14px", background: "rgba(196,67,43,0.07)", border: "1px solid rgba(196,67,43,0.2)", borderRadius: 7, fontSize: 12.5, color: "var(--risk-high)" }}>
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} style={{ marginTop: 4, padding: "12px 24px", borderRadius: 8, background: "var(--text)", color: "var(--bg)", fontSize: 14, fontWeight: 600, border: "none", cursor: loading ? "wait" : "pointer", opacity: loading ? 0.7 : 1, transition: "opacity 0.15s" }}>
              {loading ? "Signing in…" : mode === "login" ? "Sign In" : "Create Account"}
            </button>

            {mode === "login" && (
              <p style={{ fontSize: 12, color: "var(--text-3)", textAlign: "center" }}>
                Joining via invite link?{" "}
                <span style={{ color: "var(--accent)", cursor: "pointer", textDecoration: "underline", textUnderlineOffset: 3 }}
                  onClick={() => { /* mock */ }}>Open invite</span>
              </p>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}

// ── Tiny field helper ─────────────────────────────────────────────────────────

function Field({ label, value, onChange, type = "text", placeholder, autoComplete, style }) {
  return (
    <div>
      <label style={{ display: "block", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 8 }}>{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} autoComplete={autoComplete}
        style={style}
        onFocus={e => e.target.style.borderColor = "var(--text-2)"}
        onBlur={e => e.target.style.borderColor = "var(--border)"} />
    </div>
  );
}

Object.assign(window, { AuthScreen, Field });
