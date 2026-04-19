import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  ShieldAlert,
  ShieldCheck,
  ChevronsUpDown,
  ArrowRight,
  Download,
  FileEdit,
  CalendarDays,
  CheckCircle2,
  XCircle,
  Loader2,
} from "lucide-react";
import type { ReviewResult, Finding, Comment } from "@/types";
import { cn } from "@/lib/utils";
import ContractReader from "@/components/ContractReader";
import CommentThread from "@/components/CommentThread";
import { listContractComments, createContractComment, deleteContractComment } from "@/lib/api";

interface VerdictCardProps {
  result: ReviewResult;
  fileName: string;
  onReset: () => void;
  resetLabel?: string;
  runId?: string;
  findings?: Finding[];
  isAwaitingReview?: boolean;
  humanAction?: "approved" | "edited" | "rejected" | null;
  onApprove?: () => Promise<void>;
  onReject?: (reason: string) => Promise<void>;
}

const riskConfig = {
  high: {
    color: "text-risk-high",
    bg: "bg-risk-high/12",
    icon: ShieldAlert,
    label: "HIGH RISK EXPOSURE",
  },
  medium: {
    color: "text-risk-medium",
    bg: "bg-risk-medium/12",
    icon: AlertTriangle,
    label: "MEDIUM RISK EXPOSURE",
  },
  low: {
    color: "text-risk-low",
    bg: "bg-risk-low/12",
    icon: ShieldCheck,
    label: "LOW RISK EXPOSURE",
  },
};

const severityLabels: Record<string, string> = {
  high: "CRITICAL",
  medium: "WARNING",
  low: "LOW",
};

const severityStyles: Record<string, string> = {
  high: "bg-risk-high/15 text-risk-high",
  medium: "bg-risk-medium/15 text-risk-medium",
  low: "bg-risk-low/15 text-risk-low",
};


const BENCHMARKS = [
  {
    metric: "Liability Cap",
    document: "300% Fees",
    documentFlag: true,
    industry: "100% Fees",
    firm: "100% Fees",
  },
  {
    metric: "Termination Notice",
    document: "90 Days",
    documentFlag: true,
    industry: "45 Days",
    firm: "30 Days",
  },
  {
    metric: "Warranty Period",
    document: "12 Months",
    documentFlag: false,
    industry: "6 Months",
    firm: "12 Months",
  },
];

export default function VerdictCard({
  result,
  fileName,
  onReset,
  resetLabel = "Review another document",
  runId,
  findings,
  isAwaitingReview = false,
  humanAction,
  onApprove,
  onReject,
}: VerdictCardProps) {
  const [expandedClause, setExpandedClause] = useState<number | null>(0);
  const [comments, setComments] = useState<Comment[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [rejectMode, setRejectMode] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const risk = riskConfig[result.risk_level];
  const RiskIcon = risk.icon;

  // Fetch comments + poll every 5s when we have a runId
  const fetchComments = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await listContractComments(runId);
      setComments(data);
    } catch { /* ignore */ }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    setCommentsLoading(true);
    fetchComments().finally(() => setCommentsLoading(false));
    const interval = setInterval(fetchComments, 5000);
    return () => clearInterval(interval);
  }, [runId, fetchComments]);

  const handlePostComment = useCallback(async (body: string) => {
    if (!runId) return;
    const comment = await createContractComment(runId, body);
    setComments((prev) => [...prev, comment]);
  }, [runId]);

  const handleDeleteComment = useCallback(async (id: string) => {
    if (!runId) return;
    await deleteContractComment(runId, id);
    setComments((prev) => prev.filter((c) => c.id !== id));
  }, [runId]);

  const alignmentScore =
    result.risk_level === "high" ? 42 : result.risk_level === "medium" ? 65 : 88;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.5 }}
      className="w-full"
    >
      {/* Page header */}
      <div className="text-center mb-8">
        <h1 className="font-serif text-4xl lg:text-5xl font-bold text-text-primary mb-3">
          Your Verdict
        </h1>
        <p className="text-text-secondary mb-4">
          Comprehensive risk analysis for{" "}
          <span className="italic text-text-primary">{fileName}</span>
        </p>
        <div className="flex justify-center gap-3 flex-wrap">
          <div className={cn("inline-flex items-center gap-2 rounded-full px-5 py-2", risk.bg)}>
            <RiskIcon className={cn("h-4 w-4", risk.color)} />
            <span className={cn("text-xs font-bold tracking-widest", risk.color)}>
              {risk.label}
            </span>
          </div>
          {humanAction === "approved" && (
            <div className="inline-flex items-center gap-2 rounded-full px-5 py-2 bg-risk-low/10">
              <CheckCircle2 className="h-4 w-4 text-risk-low" />
              <span className="text-xs font-bold tracking-widest text-risk-low">APPROVED</span>
            </div>
          )}
          {humanAction === "rejected" && (
            <div className="inline-flex items-center gap-2 rounded-full px-5 py-2 bg-risk-high/10">
              <XCircle className="h-4 w-4 text-risk-high" />
              <span className="text-xs font-bold tracking-widest text-risk-high">REJECTED</span>
            </div>
          )}
        </div>
      </div>

      {/* Contract Reader — before findings */}
      {runId && findings && findings.length > 0 && (
        <div className="mb-14 pt-2">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-6 pb-3 border-b border-border">
            Contract Document
          </h2>
          <ContractReader runId={runId} findings={findings} />
        </div>
      )}

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-16 items-start">

        {/* ── Left column ── */}
        <div className="space-y-14">

          {/* Flagged Clauses */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-6 pb-3 border-b border-border">
              Flagged Clauses &amp; Document Text
            </h3>
            <div>
              {result.clause_flags.map((flag, i) => (
                <div key={i} className="border-b border-border/60 last:border-0">
                  <button
                    onClick={() => setExpandedClause(expandedClause === i ? null : i)}
                    className="flex w-full items-center justify-between py-4 text-left cursor-pointer"
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={cn(
                          "rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                          severityStyles[flag.severity]
                        )}
                      >
                        {severityLabels[flag.severity]}
                      </span>
                      <span className="text-sm font-semibold text-text-primary">
                        {flag.clause}
                      </span>
                    </div>
                    <ChevronsUpDown className="h-4 w-4 text-text-secondary/50 shrink-0" />
                  </button>

                  <AnimatePresence>
                    {expandedClause === i && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                      >
                        <div className="pb-5 pl-4 border-l-2 border-accent/30 ml-0 space-y-2">
                          <p className="text-sm italic text-text-secondary leading-relaxed">
                            &ldquo;{flag.issue}&rdquo;
                          </p>
                          <p className="text-xs text-text-primary/70">
                            This clause requires immediate legal review and
                            potential renegotiation.
                          </p>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              ))}
            </div>
          </div>

          {/* Compliance Benchmarking — table only, no wrapper card */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-6 pb-3 border-b border-border">
              Compliance Benchmarking
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="pb-3 text-left text-xs font-semibold uppercase tracking-widest text-text-secondary">
                    Metric
                  </th>
                  <th className="pb-3 text-left text-xs font-semibold uppercase tracking-widest text-text-secondary">
                    This Document
                  </th>
                  <th className="pb-3 text-left text-xs font-semibold uppercase tracking-widest text-text-secondary">
                    Industry Avg
                  </th>
                  <th className="pb-3 text-left text-xs font-semibold uppercase tracking-widest text-text-secondary">
                    Firm Standard
                  </th>
                </tr>
              </thead>
              <tbody>
                {BENCHMARKS.map((row) => (
                  <tr key={row.metric} className="border-b border-border/50 last:border-0">
                    <td className="py-3 font-medium text-text-primary">
                      {row.metric}
                    </td>
                    <td
                      className={cn(
                        "py-3 font-medium",
                        row.documentFlag ? "text-risk-high" : "text-text-primary"
                      )}
                    >
                      {row.document}
                    </td>
                    <td className="py-3 text-text-secondary">{row.industry}</td>
                    <td className="py-3 text-text-secondary">{row.firm}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Alignment score */}
            <div className="mt-5 pt-5 border-t border-border">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary">
                  Overall Alignment Score
                </span>
                <span className="text-2xl font-bold text-text-primary">
                  {alignmentScore}%
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-border overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-1000",
                    alignmentScore >= 70
                      ? "bg-risk-low"
                      : alignmentScore >= 50
                        ? "bg-risk-medium"
                        : "bg-risk-high"
                  )}
                  style={{ width: `${alignmentScore}%` }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* ── Right column ── */}
        <div className="space-y-12 lg:mt-12">

          {/* Legal Team Notes — real shared comments */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">
              Legal Team Notes
            </h3>
            <CommentThread
              comments={comments}
              loading={commentsLoading}
              onPost={handlePostComment}
              onDelete={handleDeleteComment}
            />
          </div>

          {/* Immediate Actions — clean numbered list */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">
              Immediate Actions
            </h3>
            <div className="space-y-4">
              {result.recommendations.slice(0, 2).map((rec, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span className="text-lg font-bold text-accent/40 leading-tight shrink-0 w-6">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-text-primary">
                      {rec.split(".")[0] || rec}
                    </p>
                    {rec.split(".")[1] && (
                      <p className="text-xs text-text-secondary mt-0.5">
                        {rec.split(".").slice(1).join(".").trim()}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Next Steps — tiered buttons */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">
              Next Steps
            </h3>
            <div className="space-y-2">
              <button className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white hover:bg-accent-hover transition-colors cursor-pointer">
                <FileEdit className="h-4 w-4" />
                Generate Redline
              </button>
              <button className="flex w-full items-center justify-center gap-2 rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-text-secondary hover:text-text-primary hover:border-text-secondary/40 transition-colors cursor-pointer">
                <CalendarDays className="h-4 w-4" />
                Schedule Partner Review
              </button>
              <button className="flex w-full items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-text-secondary/60 hover:text-text-secondary transition-colors cursor-pointer">
                <Download className="h-4 w-4" />
                Export Report
              </button>
            </div>
          </div>

          {/* Approve / Reject — shown when human review is pending */}
          {isAwaitingReview && (
            <div className="space-y-3 border-t border-border pt-6">
              <p className="text-xs font-semibold uppercase tracking-widest text-text-secondary">
                Your Decision
              </p>
              {reviewError && (
                <p className="text-xs text-risk-high">{reviewError}</p>
              )}
              <AnimatePresence>
                {rejectMode && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="space-y-3"
                  >
                    <textarea
                      value={rejectionReason}
                      onChange={(e) => setRejectionReason(e.target.value)}
                      rows={3}
                      placeholder="Reason for rejection..."
                      className="w-full border-b border-border bg-transparent px-0 py-2 text-sm text-text-primary placeholder:text-text-secondary/40 resize-none focus:outline-none focus:border-risk-high/50 transition-colors"
                      autoFocus
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={() => { setRejectMode(false); setReviewError(null); }}
                        className="flex-1 rounded-xl border border-border px-3 py-2 text-xs font-medium text-text-secondary hover:bg-drop-zone transition-colors cursor-pointer"
                      >
                        Cancel
                      </button>
                      <button
                        disabled={rejecting}
                        onClick={async () => {
                          if (!rejectionReason.trim()) { setReviewError("Please enter a reason."); return; }
                          setRejecting(true); setReviewError(null);
                          try { await onReject?.(rejectionReason); }
                          catch (e) { setReviewError((e as Error).message); setRejecting(false); }
                        }}
                        className="flex-1 rounded-xl bg-risk-high px-3 py-2 text-xs font-semibold text-white hover:bg-risk-high/80 transition-colors disabled:opacity-40 cursor-pointer"
                      >
                        {rejecting ? <Loader2 className="h-3.5 w-3.5 animate-spin mx-auto" /> : "Confirm Rejection"}
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
              {!rejectMode && (
                <div className="flex gap-2">
                  <button
                    disabled={approving || rejecting}
                    onClick={() => { setRejectMode(true); setReviewError(null); }}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-border px-3 py-2.5 text-xs font-semibold text-text-secondary hover:bg-drop-zone transition-colors disabled:opacity-40 cursor-pointer"
                  >
                    <XCircle className="h-3.5 w-3.5" /> Reject
                  </button>
                  <button
                    disabled={approving || rejecting}
                    onClick={async () => {
                      setApproving(true); setReviewError(null);
                      try { await onApprove?.(); }
                      catch (e) { setReviewError((e as Error).message); setApproving(false); }
                    }}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-accent px-3 py-2.5 text-xs font-semibold text-white hover:bg-accent-hover transition-colors disabled:opacity-40 cursor-pointer"
                  >
                    {approving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <><CheckCircle2 className="h-3.5 w-3.5" /> Approve</>}
                  </button>
                </div>
              )}
            </div>
          )}

          <button
            onClick={onReset}
            className="flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary transition-colors cursor-pointer mx-auto"
          >
            {resetLabel}
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

    </motion.div>
  );
}
