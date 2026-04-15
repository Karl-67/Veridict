import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { FileText, ChevronRight, Plus, Clock, AlertTriangle, ShieldCheck, ShieldAlert, Loader2 } from "lucide-react";
import { listContracts } from "@/lib/api";
import type { ContractSummary } from "@/types";
import { cn } from "@/lib/utils";

interface ContractsDashboardProps {
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
    processing: { text: "Processing", color: "text-accent" },
    pending: { text: "Queued", color: "text-text-secondary/60" },
    failed: { text: "Failed", color: "text-risk-high" },
    blocked: { text: "Blocked", color: "text-risk-high" },
  };
  return map[state] ?? { text: state, color: "text-text-secondary/60" };
}

export default function ContractsDashboard({ onNewContract, onOpenContract }: ContractsDashboardProps) {
  const [contracts, setContracts] = useState<ContractSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listContracts()
      .then(setContracts)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.4 }}
      className="space-y-12"
    >
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="font-serif text-4xl lg:text-5xl font-bold tracking-tight text-text-primary">
            Contracts
          </h1>
          <p className="mt-3 text-lg text-text-secondary">
            All your contracts and their review history.
          </p>
        </div>
        <button
          onClick={onNewContract}
          className="flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-accent-hover transition-colors cursor-pointer"
        >
          <Plus className="h-4 w-4" />
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
          <FileText className="h-10 w-10 text-text-secondary/20 mx-auto mb-4" />
          <p className="text-text-secondary">No contracts yet.</p>
          <button
            onClick={onNewContract}
            className="mt-4 text-sm font-medium text-accent hover:text-accent-hover transition-colors cursor-pointer underline underline-offset-2"
          >
            Upload your first contract
          </button>
        </div>
      ) : (
        <div>
          {/* Table header */}
          <div className="grid grid-cols-[1fr_80px_160px_120px_40px] gap-4 pb-3 border-b border-border">
            <span className="text-xs font-semibold uppercase tracking-widest text-text-secondary/60">Contract</span>
            <span className="text-xs font-semibold uppercase tracking-widest text-text-secondary/60">Version</span>
            <span className="text-xs font-semibold uppercase tracking-widest text-text-secondary/60">Status</span>
            <span className="text-xs font-semibold uppercase tracking-widest text-text-secondary/60">Updated</span>
            <span />
          </div>

          {/* Rows */}
          {contracts.map((c, i) => {
            const status = stateLabel(c.latest_run_state);
            return (
              <motion.div
                key={c.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04, duration: 0.25 }}
                onClick={() => onOpenContract(c)}
                className="grid grid-cols-[1fr_80px_160px_120px_40px] gap-4 py-4 border-b border-border/60 last:border-0 hover:bg-drop-zone/20 transition-colors cursor-pointer -mx-3 px-3 rounded-lg"
              >
                {/* Name + ID */}
                <div className="flex items-center gap-3 min-w-0">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-text-secondary/50">
                    <FileText className="h-3.5 w-3.5" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-text-primary truncate">{c.name}</p>
                    <p className="text-[10px] font-mono text-text-secondary/40">#{c.id} · {c.version_count} version{c.version_count !== 1 ? "s" : ""}</p>
                  </div>
                </div>

                {/* Latest version */}
                <div className="flex items-center">
                  {c.latest_label ? (
                    <span className="text-xs font-mono font-semibold text-text-primary bg-border/40 px-2 py-0.5 rounded">
                      {c.latest_label}
                    </span>
                  ) : (
                    <span className="text-xs text-text-secondary/40">—</span>
                  )}
                </div>

                {/* Status + risk */}
                <div className="flex items-center gap-2">
                  {riskIcon(c.latest_risk)}
                  <span className={cn("text-xs font-medium", c.latest_risk ? riskColor(c.latest_risk) : status.color)}>
                    {c.latest_risk ? riskLabel(c.latest_risk) : status.text}
                  </span>
                  {c.latest_run_state === "awaiting_human_review" && (
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-accent bg-accent/10 px-1.5 py-0.5 rounded">
                      Action needed
                    </span>
                  )}
                </div>

                {/* Date */}
                <div className="flex items-center gap-1.5 text-xs text-text-secondary/60">
                  <Clock className="h-3 w-3" />
                  {timeAgo(c.updated_at)}
                </div>

                {/* Arrow */}
                <div className="flex items-center justify-end">
                  <ChevronRight className="h-4 w-4 text-text-secondary/30" />
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </motion.div>
  );
}
