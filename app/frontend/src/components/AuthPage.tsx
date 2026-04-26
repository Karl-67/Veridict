import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import type { AuthUser } from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api";

type Mode = "login" | "create-org" | "register-invite";

interface InvitePreview {
  email: string;
  org_name: string;
  invited_by: string;
  workspace_name: string | null;
  workspace_role: string;
  account_exists: boolean;
}

function parseInviteToken(): string | null {
  return new URLSearchParams(window.location.search).get("invite");
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
        if (data.detail) {
          setError(data.detail);
          return;
        }
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
          body: JSON.stringify({
            org_name: orgName,
            display_name: displayName,
            job_title: jobTitle || null,
            department: department || null,
            email,
            password,
          }),
        });
      } else {
        res = await fetch(`${API_BASE}/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            token: inviteToken,
            display_name: displayName,
            job_title: jobTitle || null,
            department: department || null,
            password,
          }),
        });
      }

      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Something went wrong");
        return;
      }
      login(mapResponse(data));
      if (inviteToken) window.history.replaceState({}, "", "/");
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  if (loadingPreview) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center text-sm text-text-secondary">
        Loading invite...
      </div>
    );
  }

  return (
    <div className="min-h-screen grid bg-background text-text-primary transition-colors lg:grid-cols-2">
      <section className="relative hidden overflow-hidden bg-text-primary px-16 py-12 text-background lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute inset-0 opacity-30 [background-image:repeating-linear-gradient(0deg,transparent,transparent_60px,rgba(255,255,255,0.06)_60px,rgba(255,255,255,0.06)_61px)]" />
        <div className="relative">
          <p className="font-serif text-[22px] font-bold tracking-tight text-white/95">Veridict</p>
          <p className="mt-1 text-xs font-semibold uppercase tracking-[0.16em] text-white/35">Contract Intelligence</p>
        </div>

        <div className="relative max-w-md">
          <h1 className="font-serif text-[34px] font-bold leading-tight tracking-tight text-white/90">
            Legal intelligence for firms that move fast.
          </h1>
          <div className="mt-10 space-y-4">
            {[
              "Clause extraction across a wide range of contract types",
              "Policy alignment scoring against your firm's standards",
              "Human-in-the-loop review and sign-off workflows",
              "Full audit trail, version history, and team comments",
            ].map((feature) => (
              <div key={feature} className="flex items-start gap-3">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-[2px] bg-accent" />
                <p className="text-[13.5px] leading-relaxed text-white/55">{feature}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="relative text-xs text-white/25">© 2026 Veridict — Legal Intelligence Platform</p>
      </section>

      <main className="flex min-h-screen items-center justify-center px-6 py-14 sm:px-10 lg:px-[72px]">
        <div className="w-full max-w-[360px]">
          {!inviteToken && (
            <div className="mb-10 flex border-b border-border">
              {[
                { key: "login" as Mode, label: "Sign In" },
                { key: "create-org" as Mode, label: "Create Organisation" },
              ].map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => {
                    setMode(item.key);
                    setError(null);
                  }}
                  className={`-mb-px flex-1 border-b-2 py-2.5 text-sm font-medium transition-colors ${
                    mode === item.key
                      ? "border-text-primary text-text-primary"
                      : "border-transparent text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}

          <div className="mb-7">
            <h2 className="font-serif text-[26px] font-bold tracking-tight text-text-primary">
              {mode === "login"
                ? "Welcome back"
                : mode === "create-org"
                  ? "Get started"
                  : invitePreview?.account_exists
                    ? "Accept your invite"
                    : "Complete your account"}
            </h2>
            <p className="mt-1.5 text-[13.5px] text-text-secondary">
              {mode === "login"
                ? "Sign in to your workspace."
                : mode === "create-org"
                  ? "Create your organisation account."
                  : `Join ${invitePreview?.org_name ?? "your workspace"}.`}
            </p>
          </div>

          {invitePreview && (
            <div className="mb-5 rounded-lg border border-accent/25 bg-accent/5 px-4 py-3 text-xs text-text-secondary">
              <p className="font-semibold text-accent">You've been invited</p>
              <p className="mt-1 leading-relaxed">
                <span className="font-medium text-text-primary">{invitePreview.invited_by}</span> invited you to{" "}
                <span className="font-medium text-text-primary">{invitePreview.org_name}</span>
                {invitePreview.workspace_name ? ` · ${invitePreview.workspace_name} as ${invitePreview.workspace_role}` : ""}
              </p>
            </div>
          )}

          <form onSubmit={submit} className="space-y-[18px]">
            {mode === "create-org" && (
              <>
                <Field label="Organisation Name" value={orgName} onChange={setOrgName} placeholder="e.g. Meridian Law LLP" required />
                <Field label="Your Full Name" value={displayName} onChange={setDisplayName} placeholder="e.g. Sarah Johnson" required />
                <Field label="Job Title" value={jobTitle} onChange={setJobTitle} placeholder="e.g. Senior Associate" />
                <Field label="Department" value={department} onChange={setDepartment} placeholder="e.g. Corporate M&A" />
              </>
            )}

            {mode === "register-invite" && !invitePreview?.account_exists && (
              <>
                <Field label="Your Full Name" value={displayName} onChange={setDisplayName} placeholder="e.g. Sarah Johnson" required />
                <Field label="Job Title" value={jobTitle} onChange={setJobTitle} placeholder="e.g. Senior Associate" />
                <Field label="Department" value={department} onChange={setDepartment} placeholder="e.g. Corporate M&A" />
              </>
            )}

            <Field
              label="Email"
              type="email"
              value={email}
              onChange={setEmail}
              placeholder="you@firm.com"
              required
              disabled={mode === "register-invite"}
              autoComplete="email"
            />
            <Field
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              placeholder="••••••••"
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />

            {error && (
              <div className="rounded-lg border border-risk-high/20 bg-risk-high/10 px-3.5 py-2.5 text-xs text-risk-high">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="mt-1 w-full rounded-lg bg-text-primary px-6 py-3 text-sm font-semibold text-background transition-opacity hover:opacity-85 disabled:cursor-wait disabled:opacity-70"
            >
              {loading
                ? "Working..."
                : mode === "login"
                  ? "Sign In"
                  : mode === "create-org"
                    ? "Create Account"
                    : invitePreview?.account_exists
                      ? "Sign In & Accept Invite"
                      : "Complete Registration"}
            </button>

            {mode === "login" && (
              <p className="text-center text-xs text-text-secondary/70">
                Joining via invite link? Open the invite URL your admin sent you.
              </p>
            )}
          </form>
        </div>
      </main>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required = false,
  disabled = false,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
  autoComplete?: string;
}) {
  return (
    <div>
      <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.12em] text-text-secondary/70">{label}</label>
      <input
        type={type}
        value={value}
        required={required}
        disabled={disabled}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm text-text-primary outline-none transition-colors placeholder:text-text-secondary/40 focus:border-text-secondary disabled:cursor-not-allowed disabled:opacity-60"
      />
    </div>
  );
}
