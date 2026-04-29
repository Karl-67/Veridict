import { useState, useEffect, useRef, useCallback } from "react";
import { Play, Settings2, BarChart3, Terminal, CheckCircle2, XCircle, Loader2, ArrowUp, ArrowDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("veridict_token");
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function api(method: string, path: string, body?: unknown) {
  const res = await fetch(`${API_BASE}${path}`, {
    method, headers: authHeaders(), credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  return res.json();
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface TrainingStatus {
  status: "idle" | "starting" | "running" | "completed" | "failed";
  is_running: boolean;
  started_at?: string;
  finished_at?: string;
  error?: string;
  log_tail: string[];
}

interface EvalMetrics {
  model: string;
  endpoint: string;
  sample_count: number;
  json_validity_rate: number;
  schema_compliance_rate: number;
  issue_type_accuracy: number;
  severity_accuracy: number;
  clause_uid_f1: number;
  recommended_change_avg_tokens: number;
  rouge_l_description: number;
}

interface StatsResponse {
  available: boolean;
  message?: string;
  before?: EvalMetrics;
  after?: EvalMetrics;
  deltas?: Record<string, number | null>;
}

// ── Metric display config ─────────────────────────────────────────────────────

const METRIC_LABELS: Record<string, { label: string; format: (v: number) => string; higherIsBetter: boolean }> = {
  json_validity_rate:          { label: "JSON Validity",        format: v => `${(v * 100).toFixed(1)}%`, higherIsBetter: true },
  schema_compliance_rate:      { label: "Schema Compliance",    format: v => `${(v * 100).toFixed(1)}%`, higherIsBetter: true },
  issue_type_accuracy:         { label: "Issue Type Accuracy",  format: v => `${(v * 100).toFixed(1)}%`, higherIsBetter: true },
  severity_accuracy:           { label: "Severity Accuracy",    format: v => `${(v * 100).toFixed(1)}%`, higherIsBetter: true },
  clause_uid_f1:               { label: "Clause Coverage F1",   format: v => `${(v * 100).toFixed(1)}%`, higherIsBetter: true },
  recommended_change_avg_tokens: { label: "Rewrite Specificity", format: v => `${v.toFixed(0)} tokens`,  higherIsBetter: true },
  rouge_l_description:         { label: "ROUGE-L (Description)", format: v => `${(v * 100).toFixed(1)}%`, higherIsBetter: true },
};

// ── Delta badge ───────────────────────────────────────────────────────────────

function DeltaBadge({ delta, higherIsBetter }: { delta: number | null; higherIsBetter: boolean }) {
  if (delta === null) return <span className="text-text-secondary text-xs">—</span>;
  const improved = higherIsBetter ? delta > 0 : delta < 0;
  const neutral = Math.abs(delta) < 0.001;
  const formatted = delta > 0 ? `+${(delta * 100).toFixed(1)}%` : `${(delta * 100).toFixed(1)}%`;
  if (neutral) return (
    <span className="flex items-center gap-0.5 text-text-secondary text-xs"><Minus size={10} />{formatted}</span>
  );
  return (
    <span className={cn("flex items-center gap-0.5 text-xs font-medium", improved ? "text-risk-low" : "text-risk-critical")}>
      {improved ? <ArrowUp size={10} /> : <ArrowDown size={10} />}
      {formatted}
    </span>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { cls: string; label: string }> = {
    idle:      { cls: "bg-border/40 text-text-secondary",   label: "Idle" },
    starting:  { cls: "bg-risk-medium/15 text-risk-medium", label: "Starting…" },
    running:   { cls: "bg-accent/15 text-accent",           label: "Training" },
    completed: { cls: "bg-risk-low/15 text-risk-low",       label: "Completed" },
    failed:    { cls: "bg-risk-critical/15 text-risk-critical", label: "Failed" },
  };
  const { cls, label } = cfg[status] ?? cfg.idle;
  return (
    <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded border uppercase tracking-wide", cls)}>
      {label}
    </span>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function FineTunePanel() {
  const [host, setHost] = useState("");
  const [keyPath, setKeyPath] = useState("");
  const [hfToken, setHfToken] = useState("");
  const [savingConfig, setSavingConfig] = useState(false);
  const [configSaved, setConfigSaved] = useState(false);

  const [status, setStatus] = useState<TrainingStatus>({ status: "idle", is_running: false, log_tail: [] });
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [launching, setLaunching] = useState(false);
  const [skipGdrive, setSkipGdrive] = useState(false);
  const [skipEval, setSkipEval] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const logRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api("GET", "/fine-tune/status");
      if (s) setStatus(s);
    } catch { /* ignore */ }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const s = await api("GET", "/fine-tune/stats");
      if (s) setStats(s);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchStats();
  }, [fetchStatus, fetchStats]);

  // Poll while running
  useEffect(() => {
    if (status.is_running || status.status === "starting") {
      if (!pollRef.current) {
        pollRef.current = setInterval(() => { fetchStatus(); }, 3000);
      }
    } else {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      if (status.status === "completed") fetchStats();
    }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [status.is_running, status.status, fetchStatus, fetchStats]);

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [status.log_tail]);

  const saveConfig = async () => {
    setSavingConfig(true);
    setConfigSaved(false);
    try {
      await api("POST", "/fine-tune/config", {
        runpod_host: host,
        runpod_ssh_key_path: keyPath,
        hf_token: hfToken,
      });
      setConfigSaved(true);
      setTimeout(() => setConfigSaved(false), 2500);
    } finally {
      setSavingConfig(false);
    }
  };

  const startTraining = async () => {
    setError(null);
    setLaunching(true);
    try {
      const res = await api("POST", "/fine-tune/start", { skip_gdrive: skipGdrive, skip_eval: skipEval });
      if (res?.detail) { setError(res.detail); return; }
      await fetchStatus();
    } catch (e: any) {
      setError(e?.message ?? "Failed to start training");
    } finally {
      setLaunching(false);
    }
  };

  const isActive = status.is_running || status.status === "starting";

  return (
    <div className="space-y-6">

      {/* Config card */}
      <div className="rounded-xl border border-border bg-surface p-5 space-y-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-text-primary">
          <Settings2 size={15} className="text-accent" />
          RunPod Connection
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label className="text-xs text-text-secondary font-medium">RunPod Host</label>
            <input
              value={host} onChange={e => setHost(e.target.value)}
              placeholder="user@ssh.runpod.io or IP"
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-text-primary placeholder-text-secondary/50 focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-text-secondary font-medium">SSH Key Path</label>
            <input
              value={keyPath} onChange={e => setKeyPath(e.target.value)}
              placeholder="~/.ssh/runpod_key"
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-text-primary placeholder-text-secondary/50 focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <label className="text-xs text-text-secondary font-medium">HuggingFace Token (for gated Gemma 4)</label>
            <input
              value={hfToken} onChange={e => setHfToken(e.target.value)}
              placeholder="hf_..."
              type="password"
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-text-primary placeholder-text-secondary/50 focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        </div>
        <button
          onClick={saveConfig} disabled={savingConfig || (!host && !keyPath)}
          className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 transition-colors"
        >
          {savingConfig ? <Loader2 size={14} className="animate-spin" /> : configSaved ? <CheckCircle2 size={14} /> : <Settings2 size={14} />}
          {configSaved ? "Saved" : "Save Config"}
        </button>
      </div>

      {/* Launch card */}
      <div className="rounded-xl border border-border bg-surface p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <Play size={15} className="text-accent" />
            Fine-Tune Kira (Gemma 4 26B)
          </div>
          <StatusBadge status={status.status} />
        </div>

        <p className="text-xs text-text-secondary leading-relaxed">
          Downloads labeled data from Google Drive, exports to training format, runs QLoRA fine-tuning on your RunPod L4, downloads the adapter, and computes before/after quality metrics.
        </p>

        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
            <input type="checkbox" checked={skipGdrive} onChange={e => setSkipGdrive(e.target.checked)} className="rounded" />
            Skip Drive download (data already local)
          </label>
          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
            <input type="checkbox" checked={skipEval} onChange={e => setSkipEval(e.target.checked)} className="rounded" />
            Skip before/after eval
          </label>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-lg bg-risk-critical/10 border border-risk-critical/30 px-3 py-2 text-xs text-risk-critical">
            <XCircle size={13} className="mt-0.5 shrink-0" />
            {error}
          </div>
        )}

        {status.error && (
          <div className="flex items-start gap-2 rounded-lg bg-risk-critical/10 border border-risk-critical/30 px-3 py-2 text-xs text-risk-critical">
            <XCircle size={13} className="mt-0.5 shrink-0" />
            Training error: {status.error}
          </div>
        )}

        <button
          onClick={startTraining}
          disabled={isActive || launching}
          className="flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-accent/90 disabled:opacity-50 transition-colors"
        >
          {isActive || launching
            ? <><Loader2 size={14} className="animate-spin" /> Training in progress…</>
            : <><Play size={14} /> Start Fine-Tuning</>
          }
        </button>

        {/* Live log */}
        {(isActive || status.log_tail.length > 0) && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-xs text-text-secondary font-medium">
              <Terminal size={11} />
              Training log
              {isActive && <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />}
            </div>
            <div
              ref={logRef}
              className="rounded-lg bg-background border border-border p-3 text-[11px] font-mono text-text-secondary leading-relaxed max-h-52 overflow-y-auto"
            >
              {status.log_tail.length === 0
                ? <span className="text-text-secondary/40">Waiting for output…</span>
                : status.log_tail.map((line, i) => <div key={i}>{line || " "}</div>)
              }
            </div>
          </div>
        )}
      </div>

      {/* Before/After stats */}
      {stats?.available && (
        <div className="rounded-xl border border-border bg-surface p-5 space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <BarChart3 size={15} className="text-accent" />
            Quality Metrics
          </div>
          <div className="grid grid-cols-3 gap-x-4 gap-y-3 text-xs">
            {/* Header */}
            <div className="text-text-secondary font-medium">Metric</div>
            <div className="text-center text-text-secondary font-medium">
              Before<br />
              <span className="text-[10px] font-normal opacity-60">{stats.before?.model ?? "baseline"}</span>
            </div>
            <div className="text-center text-text-secondary font-medium">
              After<br />
              <span className="text-[10px] font-normal opacity-60">{stats.after?.model ?? "fine-tuned"}</span>
            </div>

            {/* Metric rows */}
            {Object.entries(METRIC_LABELS).map(([key, { label, format, higherIsBetter }]) => {
              const before = stats.before?.[key as keyof EvalMetrics] as number | undefined;
              const after = stats.after?.[key as keyof EvalMetrics] as number | undefined;
              const delta = stats.deltas?.[key] ?? null;
              return (
                <>
                  <div key={`${key}-label`} className="text-text-primary">{label}</div>
                  <div key={`${key}-before`} className="text-center tabular-nums text-text-secondary">
                    {before !== undefined ? format(before) : "—"}
                  </div>
                  <div key={`${key}-after`} className="text-center tabular-nums flex flex-col items-center gap-0.5">
                    <span className="text-text-primary">{after !== undefined ? format(after) : "—"}</span>
                    <DeltaBadge delta={delta} higherIsBetter={higherIsBetter} />
                  </div>
                </>
              );
            })}
          </div>
          <p className="text-[10px] text-text-secondary/60">
            Evaluated on {stats.before?.sample_count ?? 0} held-out samples from data/kira/ft/val.jsonl
          </p>
        </div>
      )}

      {stats && !stats.available && (
        <div className="rounded-xl border border-border bg-surface/60 p-5 text-center text-sm text-text-secondary">
          {stats.message ?? "Quality metrics will appear here after a completed training run."}
        </div>
      )}
    </div>
  );
}
