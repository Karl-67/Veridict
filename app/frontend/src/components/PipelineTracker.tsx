import { motion, AnimatePresence } from "framer-motion";
import {
  Shield,
  FileSearch,
  FileText,
  GitMerge,
  Users,
  CheckCircle2,
  UserCheck,
  Scale,
  Loader2,
  XCircle,
  RefreshCw,
  Circle,
  Lock,
  Database,
  ChevronDown,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { StageStatus, RunState } from "@/types";

interface PipelineTrackerProps {
  stages: StageStatus[];
  runState: RunState | null;
}

type StageDisplayInfo = {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const STAGE_DISPLAY: Record<string, StageDisplayInfo> = {
  create_run:            { label: "Initializing",      icon: Lock },
  ingest_pdf:            { label: "Ingesting PDF",      icon: FileText },
  parse_ocr_normalize:   { label: "Parsing & OCR",      icon: FileSearch },
  clause_index:          { label: "Indexing Clauses",   icon: Database },
  harvey_context_load:   { label: "Harvey Context",     icon: Shield },
  kira_context_load:     { label: "Kira Context",       icon: FileSearch },
  harvey_review_block:   { label: "Harvey Review",      icon: Shield },
  kira_review_block:     { label: "Kira Review",        icon: FileSearch },
  admin_merge:           { label: "Merging Findings",   icon: GitMerge },
  final_review_block:    { label: "Final Review",       icon: Users },
  awaiting_human_review: { label: "Human Review Gate",  icon: UserCheck },
  finalized:             { label: "Verdict Ready",      icon: Scale },
};

const STAGE_ORDER = [
  "create_run", "ingest_pdf", "parse_ocr_normalize", "clause_index",
  "harvey_context_load", "kira_context_load", "harvey_review_block",
  "kira_review_block", "admin_merge", "final_review_block",
  "awaiting_human_review", "finalized",
];

function pickLatest(stages: StageStatus[], name: string): StageStatus | undefined {
  const matches = stages.filter((s) => s.stage_name === name);
  if (!matches.length) return undefined;
  // prefer running > retrying > failed > done > pending
  const priority: Record<string, number> = {
    running: 5, retrying: 4, failed: 3, done: 2, pending: 1, blocked: 0,
  };
  return matches.sort((a, b) => (priority[b.state] ?? 0) - (priority[a.state] ?? 0))[0];
}

function statusColors(state: string) {
  switch (state) {
    case "done":     return { ring: "border-risk-low bg-risk-low/10",      text: "text-risk-low",    label: "Complete" };
    case "running":  return { ring: "border-accent bg-accent/10",           text: "text-accent",      label: "Running…" };
    case "retrying": return { ring: "border-risk-medium bg-risk-medium/10", text: "text-risk-medium", label: "Retrying…" };
    case "failed":   return { ring: "border-risk-high bg-risk-high/10",     text: "text-risk-high",   label: "Failed" };
    case "blocked":  return { ring: "border-risk-high bg-risk-high/10",     text: "text-risk-high",   label: "Blocked" };
    default:         return { ring: "border-border bg-background",          text: "text-text-secondary/40", label: "Pending" };
  }
}

export default function PipelineTracker({ stages, runState }: PipelineTrackerProps) {
  const [expandedError, setExpandedError] = useState<string | null>(null);

  // If no stages yet — show skeleton pulse
  if (!stages.length) {
    return (
      <div className="space-y-4">
        {STAGE_ORDER.slice(0, 6).map((name) => (
          <div key={name} className="flex items-center gap-4 animate-pulse">
            <div className="h-10 w-10 rounded-full border-2 border-border bg-background shrink-0" />
            <div className="h-3 w-32 rounded bg-border" />
          </div>
        ))}
      </div>
    );
  }

  // Build ordered display list — skip finalized unless it's done/running
  const rows = STAGE_ORDER
    .map((name) => ({ name, stage: pickLatest(stages, name) }))
    .filter(({ name, stage }) => {
      if (!stage) return false;
      if (name === "finalized" && stage.state === "pending") return false;
      return true;
    });

  return (
    <div className="space-y-0">
      {rows.map(({ name, stage }, index) => {
        if (!stage) return null;
        const display = STAGE_DISPLAY[name] ?? { label: name, icon: Circle };
        const Icon = display.icon;
        const colors = statusColors(stage.state);
        const isLast = index === rows.length - 1;
        const isErrorExpanded = expandedError === name;
        const hasError = (stage.state === "failed" || stage.state === "blocked") && stage.error_detail;
        const retryLabel = stage.state === "retrying"
          ? `Retrying (${stage.retry_count}/${stage.max_retries})`
          : stage.state === "failed"
          ? `Failed after ${stage.retry_count} retries`
          : null;

        return (
          <motion.div
            key={name}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.04, duration: 0.25 }}
          >
            <div className="flex items-start gap-4">
              {/* Icon + connector line */}
              <div className="flex flex-col items-center shrink-0">
                <div
                  className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-full border-2",
                    colors.ring
                  )}
                >
                  {stage.state === "done" && <CheckCircle2 className="h-5 w-5 text-risk-low" />}
                  {stage.state === "running" && <Loader2 className="h-5 w-5 text-accent animate-spin" />}
                  {stage.state === "retrying" && <RefreshCw className="h-4 w-4 text-risk-medium animate-spin" />}
                  {(stage.state === "failed" || stage.state === "blocked") && (
                    <XCircle className="h-5 w-5 text-risk-high" />
                  )}
                  {stage.state === "pending" && <Icon className="h-4 w-4 text-text-secondary/30" />}
                </div>
                {!isLast && (
                  <div
                    className={cn(
                      "w-0.5 h-7",
                      stage.state === "done" ? "bg-risk-low/30" : "bg-border"
                    )}
                  />
                )}
              </div>

              {/* Row content */}
              <div className="flex-1 pt-1.5 pb-1">
                <button
                  className={cn(
                    "flex w-full items-center justify-between",
                    hasError ? "cursor-pointer" : "cursor-default"
                  )}
                  onClick={() => {
                    if (hasError) setExpandedError(isErrorExpanded ? null : name);
                  }}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon
                      className={cn(
                        "h-3.5 w-3.5",
                        stage.state === "pending"
                          ? "text-text-secondary/30"
                          : colors.text
                      )}
                    />
                    <span
                      className={cn(
                        "text-sm",
                        stage.state === "done" ? "text-text-primary" :
                        stage.state === "running" ? "text-text-primary font-semibold" :
                        (stage.state === "failed" || stage.state === "blocked") ? "text-risk-high font-semibold" :
                        stage.state === "retrying" ? "text-risk-medium font-medium" :
                        "text-text-secondary/40"
                      )}
                    >
                      {display.label}
                    </span>
                    {retryLabel && (
                      <span className="text-[10px] text-text-secondary/60 italic">
                        {retryLabel}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className={cn("text-xs font-medium italic", colors.text)}>
                      {colors.label}
                    </span>
                    {hasError && (
                      <ChevronDown
                        className={cn(
                          "h-3 w-3 text-risk-high/60 transition-transform duration-200",
                          isErrorExpanded ? "rotate-180" : ""
                        )}
                      />
                    )}
                  </div>
                </button>

                {/* Error detail expansion */}
                <AnimatePresence>
                  {hasError && isErrorExpanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      <div className="mt-2 rounded-lg bg-risk-high/5 border border-risk-high/20 px-3 py-2">
                        <p className="text-[11px] font-mono text-risk-high/80 break-all leading-relaxed">
                          {stage.error_detail}
                        </p>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </motion.div>
        );
      })}

      {/* Overall failed/blocked banner */}
      {(runState === "failed" || runState === "blocked") && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4 rounded-xl bg-risk-high/8 border border-risk-high/25 px-4 py-3"
        >
          <p className="text-sm font-semibold text-risk-high mb-0.5">
            {runState === "blocked" ? "Run Blocked" : "Run Failed"}
          </p>
          <p className="text-xs text-risk-high/70">
            Click the failed stage above to see the error detail.
            Failures are logged to <span className="font-mono">logs/failures.jsonl</span>.
          </p>
        </motion.div>
      )}
    </div>
  );
}
