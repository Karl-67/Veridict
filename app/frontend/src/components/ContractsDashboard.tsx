import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  FileText, ChevronRight, Plus, Clock, AlertTriangle,
  ShieldCheck, ShieldAlert, Loader2, FolderOpen, CircleDot, CheckCircle2, X,
} from "lucide-react";
import { listContracts, cancelRun } from "@/lib/api";
import type { ContractSummary, Workspace } from "@/types";
import { cn } from "@/lib/utils";
import { useAuth } from "@/context/AuthContext";

interface ContractsDashboardProps {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  onWorkspaceChange: (id: string | null) => void;
  onNewContract: () => void;
  onOpenContract: (contract: ContractSummary) => void;
}

const riskIcon = (risk: string | null, cls = "h-3.5 w-3.5") => {
  if (risk === "high" || risk === "critical") return <ShieldAlert className={cn(cls, "text-risk-high")} />;
  if (risk === "medium") return <AlertTriangle className={cn(cls, "text-risk-medium")} />;
  if (risk === "low") return <ShieldCheck className={cn(cls, "text-risk-low")} />;
  return null;
};

const riskLabel = (risk: string | null) => {
  if (!risk) return null;
  const map: Record<string, string> = { low: "Low", medium: "Medium", high: "High", critical: "High" };
  return map[risk] ?? risk;
};

const riskColor = (risk: string | null) => {
  if (risk === "high" || risk === "critical") return "text-risk-high";
  if (risk === "medium") return "text-risk-medium";
  if (risk === "low") return "text-risk-low";
  return "text-text-secondary/40";
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function stateLabel(state: string | null): { text: string; color: string } {
  if (!state) return { text: "No runs", color: "text-text-secondary/40" };
  const map: Record<string, { text: string; color: string }> = {
    finalized: { text: "Finalized", color: "text-risk-low" },
    awaiting_human_review: { text: "Awaiting Review", color: "text-accent" },
    under_review: { text: "Under Review", color: "text-risk-medium" },
    processing: { text: "Processing", color: "text-accent" },
    pending: { text: "Queued", color: "text-text-secondary/60" },
    failed: { text: "Failed", color: "text-risk-high" },
    blocked: { text: "Blocked", color: "text-risk-high" },
  };
  return map[state] ?? { text: state, color: "text-text-secondary/60" };
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function firstName(displayName: string): string {
  return displayName.split(" ")[0];
}

export default function ContractsDashboard({
  workspaces,
  activeWorkspaceId,
  onWorkspaceChange,
  onNewContract,
  onOpenContract,
}: ContractsDashboardProps) {
  const { user } = useAuth();
  const [contracts, setContracts] = useState<ContractSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  async function handleCancel(e: React.MouseEvent, runId: string) {
    e.stopPropagation();
    setCancellingId(runId);
    try {
      await cancelRun(runId);
      setContracts((prev) =>
        prev.map((c) =>
          c.latest_run_id === runId ? { ...c, latest_run_state: "cancelled" } : c
        )
      );
    } catch (err) {
      console.error("Cancel failed:", err);
    } finally {
      setCancellingId(null);
    }
  }

  const isAdmin = workspaces.some((w) => w.role === "org_admin");
  const effectiveWsId = activeWorkspaceId;

  const hasActiveRuns = contracts.some(
    (c) => c.latest_run_state === "processing" || c.latest_run_state === "created"
  );

  useEffect(() => {
    setLoading(true);
    listContracts(effectiveWsId ?? undefined)
      .then(setContracts)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [effectiveWsId]);

  useEffect(() => {
    if (!hasActiveRuns) return;
    const id = setInterval(() => {
      listContracts(effectiveWsId ?? undefined)
        .then(setContracts)
        .catch(console.error);
    }, 5000);
    return () => clearInterval(id);
  }, [hasActiveRuns, effectiveWsId]);

  const awaitingReview = contracts.filter((c) => c.latest_run_state === "awaiting_human_review").length;
  const finalized = contracts.filter((c) => c.latest_run_state === "finalized").length;
  const inProgress = contracts.filter(
    (c) => c.latest_run_state && !["finalized", "awaiting_human_review", "failed", "blocked"].includes(c.latest_run_state)
  ).length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.4 }}
      className="space-y-14"
    >
      {/* Welcome header */}
      <div>
        <p className="font-serif text-2xl text-text-secondary/70 mb-1">{greeting()},</p>
        <h1 className="font-serif text-5xl lg:text-6xl font-bold tracking-tight text-text-primary">
          {user ? firstName(user.display_name) : "Welcome"}
        </h1>
        <p className="mt-3 text-base text-text-secondary">
          Here's what's happening with your contracts.
        </p>
      </div>

      {/* Stats row */}
      {!loading && contracts.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            {
              label: "Total Contracts",
              value: contracts.length,
              icon: <FolderOpen className="h-4 w-4" />,
              color: "text-text-secondary",
              bg: "bg-border/30",
            },
            {
              label: "Awaiting Review",
              value: awaitingReview,
              icon: <CircleDot className="h-4 w-4" />,
              color: awaitingReview > 0 ? "text-accent" : "text-text-secondary/40",
              bg: awaitingReview > 0 ? "bg-accent/8" : "bg-border/30",
            },
            {
              label: "In Progress",
              value: inProgress,
              icon: <Loader2 className={cn("h-4 w-4", inProgress > 0 && "animate-spin")} />,
              color: inProgress > 0 ? "text-text-secondary" : "text-text-secondary/40",
              bg: "bg-border/30",
            },
            {
              label: "Finalized",
              value: finalized,
              icon: <CheckCircle2 className="h-4 w-4" />,
              color: finalized > 0 ? "text-risk-low" : "text-text-secondary/40",
              bg: finalized > 0 ? "bg-risk-low/8" : "bg-border/30",
            },
          ].map((stat) => (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
              className={cn("rounded-2xl border border-border p-5", stat.bg)}
            >
              <div className={cn("flex items-center gap-2 mb-3", stat.color)}>
                {stat.icon}
                <span className="text-xs font-semibold uppercase tracking-widest opacity-70">{stat.label}</span>
              </div>
              <p className={cn("text-3xl font-bold font-serif tracking-tight", stat.color)}>
                {stat.value}
              </p>
            </motion.div>
          ))}
        </div>
      )}

      {/* Workspace tabs + New Contract */}
      <div className="flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-1">
          {isAdmin && (
            <button
              onClick={() => onWorkspaceChange(null)}
              className={cn(
                "px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px cursor-pointer",
                activeWorkspaceId === null
                  ? "border-accent text-text-primary"
                  : "border-transparent text-text-secondary hover:text-text-primary"
              )}
            >
              All
            </button>
          )}
          {workspaces.map((ws) => (
            <button
              key={ws.workspace_id}
              onClick={() => onWorkspaceChange(ws.workspace_id)}
              className={cn(
                "px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px cursor-pointer",
                activeWorkspaceId === ws.workspace_id
                  ? "border-accent text-text-primary"
                  : "border-transparent text-text-secondary hover:text-text-primary"
              )}
            >
              {ws.name}
            </button>
          ))}
        </div>
        <button
          onClick={onNewContract}
          className="flex items-center gap-2 rounded-xl bg-text-primary px-4 py-2 text-sm font-semibold text-background hover:opacity-80 transition-opacity cursor-pointer self-center mb-1"
        >
          <Plus className="h-3.5 w-3.5" />
          New Contract
        </button>
      </div>

      {/* Contract list */}
      {loading ? (
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-6 w-6 text-text-secondary/40 animate-spin" />
        </div>
      ) : contracts.length === 0 ? (
        <div className="py-24 text-center">
          <div className="inline-flex items-center justify-center h-16 w-16 rounded-2xl border border-border bg-surface mb-5">
            <FileText className="h-7 w-7 text-text-secondary/30" />
          </div>
          <p className="text-base font-medium text-text-primary">No contracts yet</p>
          <p className="text-sm text-text-secondary mt-1 mb-5">Upload your first contract to get started.</p>
          {activeWorkspaceId && (
            <button
              onClick={onNewContract}
              className="inline-flex items-center gap-2 rounded-xl bg-text-primary px-5 py-2.5 text-sm font-semibold text-background hover:opacity-80 transition-opacity cursor-pointer"
            >
              <Plus className="h-4 w-4" />
              New Contract
            </button>
          )}
        </div>
      ) : (
        <div>
          <div className="grid grid-cols-[1fr_80px_160px_120px_120px_40px] gap-4 pb-3 border-b border-border">
            <span className="text-xs font-semibold uppercase tracking-widest text-text-secondary/50">Contract</span>
            <span className="text-xs font-semibold uppercase tracking-widest text-text-secondary/50">Version</span>
            <span className="text-xs font-semibold uppercase tracking-widest text-text-secondary/50">Status</span>
            <span className="text-xs font-semibold uppercase tracking-widest text-text-secondary/50">Risk</span>
            <span className="text-xs font-semibold uppercase tracking-widest text-text-secondary/50">Updated</span>
            <span />
          </div>

          {contracts.map((c, i) => {
            const status = stateLabel(c.latest_run_state);
            const needsAction = c.latest_run_state === "awaiting_human_review" || c.latest_run_state === "under_review";
            return (
              <motion.div
                key={c.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04, duration: 0.25 }}
                onClick={() => onOpenContract(c)}
                className={cn(
                  "group grid grid-cols-[1fr_80px_160px_120px_120px_40px] gap-4 py-4 border-b border-border/60 last:border-0 transition-colors cursor-pointer -mx-3 px-3 rounded-xl",
                  needsAction
                    ? "hover:bg-accent/5"
                    : "hover:bg-drop-zone/20"
                )}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className={cn(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border",
                    needsAction
                      ? "border-accent/30 bg-accent/8 text-accent"
                      : "border-border bg-surface text-text-secondary/50"
                  )}>
                    <FileText className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-text-primary truncate">{c.name}</p>
                    <p className="text-[10px] font-mono text-text-secondary/40">
                      #{c.id} · {c.version_count} version{c.version_count !== 1 ? "s" : ""}
                      {activeWorkspaceId === null && c.workspace_name && (
                        <> · <span className="text-text-secondary/60">{c.workspace_name}</span></>
                      )}
                    </p>
                  </div>
                </div>

                <div className="flex items-center">
                  {c.latest_label ? (
                    <span className="text-xs font-mono font-semibold text-text-primary bg-border/40 px-2 py-0.5 rounded">
                      {c.latest_label}
                    </span>
                  ) : (
                    <span className="text-xs text-text-secondary/40">—</span>
                  )}
                </div>

                {/* Status column */}
                <div className="flex items-center gap-2">
                  <span className={cn("text-xs font-medium", status.color)}>
                    {status.text}
                  </span>
                  {needsAction && (
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-accent bg-accent/10 px-1.5 py-0.5 rounded-md">
                      Action
                    </span>
                  )}
                </div>

                {/* Risk column */}
                <div className="flex items-center gap-1.5">
                  {c.latest_risk ? (
                    <>
                      {riskIcon(c.latest_risk)}
                      <span className={cn("text-xs font-medium", riskColor(c.latest_risk))}>
                        {riskLabel(c.latest_risk)}
                      </span>
                    </>
                  ) : (
                    <span className="text-xs text-text-secondary/30">—</span>
                  )}
                </div>

                <div className="flex items-center gap-1.5 text-xs text-text-secondary/50">
                  <Clock className="h-3 w-3" />
                  {timeAgo(c.updated_at)}
                </div>

                <div className="flex items-center justify-end">
                  {(c.latest_run_state === "processing" || c.latest_run_state === "created" || c.latest_run_state === "pending") && c.latest_run_id ? (
                    <button
                      onClick={(e) => handleCancel(e, c.latest_run_id!)}
                      disabled={cancellingId === c.latest_run_id}
                      title="Cancel analysis"
                      className="rounded-lg p-0.5 text-text-secondary/40 hover:text-risk-high hover:bg-risk-high/10 cursor-pointer disabled:cursor-default transition-colors"
                    >
                      {cancellingId === c.latest_run_id
                        ? <Loader2 className="h-4 w-4 animate-spin" />
                        : <X className="h-4 w-4" />}
                    </button>
                  ) : (
                    <ChevronRight className="h-4 w-4 text-text-secondary/30" />
                  )}
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </motion.div>
  );
}
