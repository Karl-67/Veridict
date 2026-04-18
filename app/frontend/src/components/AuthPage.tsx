import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Loader2, Building2, LogIn } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import type { AuthUser } from "@/types";

const API_BASE = "http://localhost:8000/api";

type Mode = "login" | "create-org" | "register-invite";

function parseInviteToken(): string | null {
  const params = new URLSearchParams(window.location.search);
  return params.get("invite");
}

interface InvitePreview {
  email: string;
  org_name: string;
  invited_by: string;
  workspace_name: string | null;
  workspace_role: string;
  account_exists: boolean;
}

function mapResponse(data: Record<string, unknown>): AuthUser {
  return {
    user_id: data.user_id as string,
    email: data.email as string,
    display_name: data.display_name as string,
    job_title: (data.job_title as string) ?? null,
    department: (data.department as string) ?? null,
    avatar_color: (data.avatar_color as string) ?? "#6366f1",
    org_id: (data.org_id as string) ?? null,
    org_role: (data.org_role as string) ?? "member",
    org_name: (data.org_name as string) ?? null,
    token: data.access_token as string,
  };
}

export default function AuthPage() {
  const { login } = useAuth();
  const inviteToken = parseInviteToken();
  const [mode, setMode] = useState<Mode>(inviteToken ? "register-invite" : "login");
  const [invitePreview, setInvitePreview] = useState<InvitePreview | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);

  // Fields
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [department, setDepartment] = useState("");
  const [orgName, setOrgName] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!inviteToken) return;
    setLoadingPreview(true);
    fetch(`${API_BASE}/auth/invite-preview/${inviteToken}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.detail) { setError(data.detail); return; }
        setInvitePreview(data);
        setEmail(data.email);
      })
      .catch(() => setError("Could not load invite details"))
      .finally(() => setLoadingPreview(false));
  }, [inviteToken]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      let res: Response;
      if (mode === "login") {
        res = await fetch(`${API_BASE}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ email, password }),
        });
      } else if (mode === "create-org") {
        res = await fetch(`${API_BASE}/auth/create-org`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ org_name: orgName, display_name: displayName, job_title: jobTitle || null, department: department || null, email, password }),
        });
      } else {
        res = await fetch(`${API_BASE}/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ token: inviteToken, display_name: displayName, job_title: jobTitle || null, department: department || null, password }),
        });
      }
      const data = await res.json();
      if (!res.ok) { setError(data.detail || "Something went wrong"); return; }
      login(mapResponse(data));
      // Clear invite param from URL
      if (inviteToken) window.history.replaceState({}, "", "/");
    } catch {
      setError("Network error — please try again");
    } finally {
      setLoading(false);
    }
  };

  if (loadingPreview) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-text-secondary/40" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-10">
          <span className="font-serif text-3xl font-bold text-text-primary tracking-tight">Veridict</span>
          <p className="text-sm text-text-secondary mt-1">AI Contract Review Platform</p>
        </div>

        {/* Mode tabs — only show when not coming from invite */}
        {!inviteToken && (
          <div className="flex rounded-xl border border-border bg-surface overflow-hidden mb-6">
            {([
              { m: "login" as Mode, label: "Sign In", icon: LogIn },
              { m: "create-org" as Mode, label: "New Firm", icon: Building2 },
            ] as const).map(({ m, label, icon: Icon }) => (
              <button
                key={m}
                onClick={() => { setMode(m); setError(null); }}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 text-xs font-semibold transition-colors cursor-pointer ${mode === m ? "bg-accent text-white" : "text-text-secondary hover:text-text-primary"}`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
        )}

        {/* Invite banner */}
        {invitePreview && (
          <div className="mb-5 rounded-xl border border-accent/30 bg-accent/5 px-4 py-3">
            <p className="text-xs font-semibold text-accent mb-0.5">You've been invited</p>
            <p className="text-xs text-text-secondary">
              <span className="font-medium text-text-primary">{invitePreview.invited_by}</span> invited you to{" "}
              <span className="font-medium text-text-primary">{invitePreview.org_name}</span>
              {invitePreview.workspace_name && (
                <> · <span className="italic">{invitePreview.workspace_name}</span> as <span className="font-medium">{invitePreview.workspace_role}</span></>
              )}
            </p>
          </div>
        )}

        <div className="rounded-2xl border border-border bg-surface p-8">
          <h2 className="text-base font-semibold text-text-primary mb-6">
            {mode === "login" ? "Sign in to your account" : mode === "create-org" ? "Set up your firm" : invitePreview?.account_exists ? "Sign in to accept invite" : "Complete your account"}
          </h2>

          <form onSubmit={submit} className="space-y-4">
            {mode === "create-org" && (
              <Field label="Firm Name" value={orgName} onChange={setOrgName} placeholder="Meridian Legal Partners" required />
            )}

            <Field
              label="Email"
              type="email"
              value={email}
              onChange={setEmail}
              placeholder="you@firm.com"
              required
              disabled={mode === "register-invite"}
            />

            {mode !== "login" && !invitePreview?.account_exists && (
              <>
                <Field label="Display Name" value={displayName} onChange={setDisplayName} placeholder="J. Sterling" required />
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Job Title" value={jobTitle} onChange={setJobTitle} placeholder="Partner" />
                  <Field label="Department" value={department} onChange={setDepartment} placeholder="M&A" />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1.5 uppercase tracking-wider">Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-xl border border-border bg-transparent px-4 py-2.5 text-sm text-text-primary placeholder:text-text-secondary/40 focus:border-accent focus:outline-none transition-colors"
                placeholder="••••••••"
              />
              {mode !== "login" && !invitePreview?.account_exists && (
                <p className="mt-1 text-[10px] text-text-secondary/50">Min 8 chars, one uppercase, one number</p>
              )}
            </div>

            {error && <p className="text-xs text-risk-high">{error}</p>}

            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50 transition-colors cursor-pointer disabled:cursor-not-allowed mt-2"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {mode === "login" ? "Sign In" : mode === "create-org" ? "Create Firm & Account" : invitePreview?.account_exists ? "Sign In & Accept Invite" : "Complete Registration"}
            </button>
          </form>

          {!inviteToken && mode !== "login" && (
            <p className="mt-5 text-center text-xs text-text-secondary/60">
              Already have an account?{" "}
              <button onClick={() => { setMode("login"); setError(null); }} className="text-accent hover:underline cursor-pointer">Sign in</button>
            </p>
          )}
        </div>

        {mode === "create-org" && (
          <p className="mt-4 text-center text-[10px] text-text-secondary/40">
            To join an existing firm, ask your admin to send you an invite link.
          </p>
        )}
      </motion.div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, type = "text", required = false, disabled = false }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string; required?: boolean; disabled?: boolean;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-text-secondary mb-1.5 uppercase tracking-wider">{label}</label>
      <input
        type={type}
        required={required}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-xl border border-border bg-transparent px-4 py-2.5 text-sm text-text-primary placeholder:text-text-secondary/40 focus:border-accent focus:outline-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      />
    </div>
  );
}
