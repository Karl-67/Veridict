import { useEffect, useState, useMemo } from "react";
import { motion } from "framer-motion";
import {
  Clock, ShieldAlert, ShieldCheck, AlertTriangle,
  CheckCircle2, XCircle, Loader2, ChevronRight, Activity, X,
} from "lucide-react";
import { listHistory, cancelRun } from "@/lib/api";
import type { HistoryEntry } from "@/types";
import { cn } from "@/lib/utils";

interface HistoryPageProps {
  onOpenContract: (contractId: number) => void;
}

type FilterState = "all" | "finalized" | "awaiting_human_review" | "under_review" | "failed";

const FILTERS: { key: FilterState; label: string }[] = [
  { key: "all",                   label: "All" },
  { key: "finalized",             label: "Finalized" },
  { key: "awaiting_human_review", label: "Awaiting Review" },
  { key: "under_review",          label: "Under Review" },
  { key: "failed",                label: "Failed" },
];

function eventDotColor(entry: HistoryEntry): string {
  if (entry.human_action === "approved") return "bg-risk-low";
  if (entry.human_action === "rejected") return "bg-risk-high";
  if (entry.state === "awaiting_human_review" || entry.state === "under_review") return "bg-accent";
  if (entry.state === "failed" || entry.state === "blocked") return "bg-risk-high";
  if (entry.state === "finalized") return "bg-risk-low";
  return "bg-text-secondary/25";
}

function eventSentence(entry: HistoryEntry): React.ReactNode {
  const name = <span className="font-semibold text-text-primary">{entry.contract_name}</span>;
  const ver  = <span className="font-mono text-text-secondary/60">{entry.version_label}</span>;

  if (entry.human_action === "approved")
    return <>{name} {ver} was <span className="text-risk-low font-semibold">approved</span></>;
  if (entry.human_action === "rejected")
    return <>{name} {ver} was <span className="text-risk-high font-semibold">rejected</span></>;
  if (entry.state === "awaiting_human_review")
    return <>{name} {ver} is <span className="text-accent font-semibold">awaiting review</span></>;
  if (entry.state === "under_review")
    return <>{name} {ver} is <span className="text-risk-medium font-semibold">under review</span></>;
  if (entry.state === "finalized")
    return <>{name} {ver} was <span className="text-risk-low font-semibold">finalized</span></>;
  if (entry.state === "failed" || entry.state === "blocked")
    return <>{name} {ver} <span className="text-risk-high font-semibold">failed</span></>;
  return <>{name} {ver} — {entry.state}</>;
}

function riskBadge(risk: string | null) {
  if (!risk) return null;
  if (risk === "high" || risk === "critical")
    return <span className="inline-flex items-center gap-1 text-[11px] font-medium text-risk-high"><ShieldAlert className="h-3 w-3" />High risk</span>;
  if (risk === "medium")
    return <span className="inline-flex items-center gap-1 text-[11px] font-medium text-risk-medium"><AlertTriangle className="h-3 w-3" />Medium risk</span>;
  if (risk === "low")
    return <span className="inline-flex items-center gap-1 text-[11px] font-medium text-risk-low"><ShieldCheck className="h-3 w-3" />Low risk</span>;
  return null;
}

function formatTimestamp(iso: string): { relative: string; absolute: string } {
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const m = Math.floor(diff / 60000);
  let relative: string;
  if (m < 1) relative = "just now";
  else if (m < 60) relative = `${m}m ago`;
  else if (m < 1440) relative = `${Math.floor(m / 60)}h ago`;
  else relative = `${Math.floor(m / 1440)}d ago`;
  const absolute = d.toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
  return { relative, absolute };
}

function dateGroup(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today     = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  const weekAgo   = new Date(today); weekAgo.setDate(today.getDate() - 7);
  const entryDay  = new Date(d.getFullYear(), d.getMonth(), d.getDate());

  if (entryDay >= today)     return "Today";
  if (entryDay >= yesterday) return "Yesterday";
  if (entryDay >= weekAgo)   return "This week";
  return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

export default function HistoryPage({ onOpenContract }: HistoryPageProps) {
  const [entries, setEntries]     = useState<HistoryEntry[]>([]);
  const [loading, setLoading]     = useState(true);
  const [filter, setFilter]       = useState<FilterState>("all");
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  async function handleCancel(e: React.MouseEvent, runId: string) {
    e.stopPropagation();
    setCancellingId(runId);
    try {
      await cancelRun(runId);
      setEntries((prev) =>
        prev.map((en) => en.run_id === runId ? { ...en, state: "cancelled" as const } : en)
      );
    } catch (err) {
      console.error("Cancel failed:", err);
    } finally {
      setCancellingId(null);
    }
  }

  useEffect(() => {
    setLoading(true);
    listHistory()
      .then(setEntries)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    if (filter === "all") return entries;
    return entries.filter((e) => e.state === filter);
  }, [entries, filter]);

  const grouped = useMemo(() => {
    const groups: { label: string; entries: HistoryEntry[] }[] = [];
    const seen = new Map<string, number>();
    for (const e of filtered) {
      const g = dateGroup(e.created_at);
      if (!seen.has(g)) { seen.set(g, groups.length); groups.push({ label: g, entries: [] }); }
      groups[seen.get(g)!].entries.push(e);
    }
    return groups;
  }, [filtered]);

  const totalApproved = entries.filter((e) => e.human_action === "approved").length;
  const totalRejected = entries.filter((e) => e.human_action === "rejected").length;

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
          <div className="flex items-center gap-2 mb-3">
            <Activity className="h-3.5 w-3.5 text-accent" />
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-accent">Activity Log</p>
          </div>
          <h1 className="font-serif text-4xl lg:text-5xl font-bold tracking-tight text-text-primary mb-3">
            Run History
          </h1>
          <p className="text-base text-text-secondary">
            Every analysis event, in order.
          </p>
        </div>

        {/* Summary bar */}
        {!loading && entries.length > 0 && (
          <div className="hidden sm:flex items-center gap-6 pb-1">
            <div className="text-right">
              <p className="text-2xl font-bold font-serif text-text-primary">{entries.length}</p>
              <p className="text-[10px] uppercase tracking-widest text-text-secondary/40 font-semibold">Total runs</p>
            </div>
            <div className="h-10 w-px bg-border" />
            <div className="text-right">
              <p className="text-2xl font-bold font-serif text-risk-low">{totalApproved}</p>
              <p className="text-[10px] uppercase tracking-widest text-text-secondary/40 font-semibold">Approved</p>
            </div>
            <div className="h-10 w-px bg-border" />
            <div className="text-right">
              <p className={cn("text-2xl font-bold font-serif", totalRejected > 0 ? "text-risk-high" : "text-text-secondary/30")}>{totalRejected}</p>
              <p className="text-[10px] uppercase tracking-widest text-text-secondary/40 font-semibold">Rejected</p>
            </div>
          </div>
        )}
      </div>

      {/* Filter pills */}
      {!loading && entries.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => {
            const count = f.key === "all"
              ? entries.length
              : entries.filter((e) => e.state === f.key).length;
            if (f.key !== "all" && count === 0) return null;
            return (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all cursor-pointer",
                  filter === f.key
                    ? "bg-text-primary text-background"
                    : "border border-border/70 text-text-secondary hover:text-text-primary hover:border-text-secondary/30"
                )}
              >
                {f.label}
                <span className={cn("tabular-nums", filter === f.key ? "opacity-50" : "opacity-35")}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Timeline */}
      {loading ? (
        <div className="flex items-center justify-center py-32">
          <Loader2 className="h-5 w-5 animate-spin text-text-secondary/30" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-32 text-center">
          <div className="inline-flex items-center justify-center h-16 w-16 rounded-2xl border border-border bg-surface mb-5">
            <Clock className="h-7 w-7 text-text-secondary/20" />
          </div>
          <p className="text-base font-medium text-text-primary">No activity yet</p>
          <p className="text-sm text-text-secondary mt-1">
            {filter === "all" ? "Run an analysis to see it here." : "No events match this filter."}
          </p>
        </div>
      ) : (
        <div className="space-y-10">
          {grouped.map((group) => (
            <div key={group.label}>
              {/* Date label */}
              <div className="flex items-center gap-3 mb-5">
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-text-secondary/35 shrink-0">
                  {group.label}
                </p>
                <div className="flex-1 h-px bg-border/40" />
              </div>

              {/* Timeline entries */}
              <div className="relative pl-6">
                {/* Vertical line */}
                <div className="absolute left-[7px] top-2 bottom-2 w-px bg-border/40" />

                <div className="space-y-1">
                  {group.entries.map((entry, i) => {
                    const { relative, absolute } = formatTimestamp(entry.created_at);
                    const dotColor = eventDotColor(entry);
                    const rb = riskBadge(entry.risk_level);
                    const needsAction = entry.state === "awaiting_human_review" || entry.state === "under_review";

                    return (
                      <motion.div
                        key={entry.run_id}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.03, duration: 0.2 }}
                        className="relative group"
                      >
                        {/* Timeline dot */}
                        <div className={cn(
                          "absolute -left-6 top-[18px] h-3.5 w-3.5 rounded-full border-2 border-background",
                          dotColor
                        )} />

                        <div
                          role="button"
                          tabIndex={0}
                          onClick={() => onOpenContract(entry.contract_id)}
                          onKeyDown={(e) => e.key === "Enter" && onOpenContract(entry.contract_id)}
                          className={cn(
                            "w-full flex items-center gap-5 rounded-xl px-4 py-3.5 text-left transition-all duration-150 cursor-pointer",
                            needsAction
                              ? "hover:bg-accent/5"
                              : "hover:bg-surface/50"
                          )}
                        >
                          {/* Event text */}
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-text-secondary leading-snug">
                              {eventSentence(entry)}
                            </p>
                            <div className="flex items-center gap-3 mt-1.5 flex-wrap">
                              {rb}
                              {entry.human_action === "approved" && (
                                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-risk-low">
                                  <CheckCircle2 className="h-3 w-3" />Approved
                                </span>
                              )}
                              {entry.human_action === "rejected" && (
                                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-risk-high">
                                  <XCircle className="h-3 w-3" />Rejected
                                </span>
                              )}
                              {entry.workspace_name && (
                                <span className="text-[11px] text-text-secondary/35">{entry.workspace_name}</span>
                              )}
                              {entry.filename && (
                                <span className="text-[11px] font-mono text-text-secondary/25 truncate max-w-[200px]">
                                  {entry.filename}
                                </span>
                              )}
                            </div>
                          </div>

                          {/* Timestamp + chevron/cancel */}
                          <div className="flex items-center gap-2 shrink-0">
                            <span
                              className="text-xs text-text-secondary/35 tabular-nums"
                              title={absolute}
                            >
                              {relative}
                            </span>
                            {entry.state === "processing" || entry.state === "created" ? (
                              <button
                                onClick={(e) => handleCancel(e, entry.run_id)}
                                disabled={cancellingId === entry.run_id}
                                title="Cancel analysis"
                                className="opacity-0 group-hover:opacity-100 transition-opacity rounded-lg p-0.5 text-text-secondary/30 hover:text-risk-high hover:bg-risk-high/10 cursor-pointer disabled:cursor-default"
                              >
                                {cancellingId === entry.run_id
                                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  : <X className="h-3.5 w-3.5" />}
                              </button>
                            ) : (
                              <ChevronRight className="h-3.5 w-3.5 text-text-secondary/15 group-hover:text-text-secondary/40 transition-colors" />
                            )}
                          </div>
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
}
