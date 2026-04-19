import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2, XCircle, Loader2, ShieldCheck,
  ShieldAlert, AlertTriangle, ChevronsUpDown, ChevronDown,
} from "lucide-react";
import { getRunFindings, submitHumanReview } from "@/lib/api";
import type { Finding } from "@/types";
import { cn } from "@/lib/utils";

interface HumanReviewPanelProps {
  runId: string;
  fileName: string;
  contractId?: number | null;
  onStartReview: () => void;
  onRejected: () => void;
}

type DecisionState = "hidden" | "idle" | "confirming_reject" | "submitting_reject";

const severityConfig: Record<string, { label: string; style: string }> = {
  critical: { label: "CRITICAL", style: "bg-risk-high/15 text-risk-high" },
  high:     { label: "HIGH",     style: "bg-risk-high/15 text-risk-high" },
  medium:   { label: "WARNING",  style: "bg-risk-medium/15 text-risk-medium" },
  low:      { label: "LOW",      style: "bg-risk-low/15 text-risk-low" },
};

function overallRisk(findings: Finding[]): "high" | "medium" | "low" {
  if (findings.some((f) => f.severity === "critical" || f.severity === "high")) return "high";
  if (findings.some((f) => f.severity === "medium")) return "medium";
  return "low";
}

const riskBadge = {
  high:   { color: "text-risk-high",   bg: "bg-risk-high/10",   Icon: ShieldAlert,   label: "HIGH RISK EXPOSURE" },
  medium: { color: "text-risk-medium", bg: "bg-risk-medium/10", Icon: AlertTriangle, label: "MEDIUM RISK EXPOSURE" },
  low:    { color: "text-risk-low",    bg: "bg-risk-low/10",    Icon: ShieldCheck,   label: "LOW RISK EXPOSURE" },
};

export default function HumanReviewPanel({
  runId,
  fileName,
  onStartReview,
  onRejected,
}: HumanReviewPanelProps) {
  const [decisionState, setDecisionState] = useState<DecisionState>("hidden");
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loadingFindings, setLoadingFindings] = useState(true);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(0);
  const [rejectionReason, setRejectionReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRunFindings(runId)
      .then(setFindings)
      .catch(() => setFindings([]))
      .finally(() => setLoadingFindings(false));
  }, [runId]);

  const isSubmitting = decisionState === "submitting_reject";
  const risk = overallRisk(findings);
  const badge = riskBadge[risk];
  const BadgeIcon = badge.Icon;

  const handleReject = async () => {
    if (!rejectionReason.trim()) { setError("Please enter a rejection reason."); return; }
    setDecisionState("submitting_reject");
    setError(null);
    try {
      await submitHumanReview(runId, {
        run_action: "rejected",
        reviewer_id: "verdict-user",
        rejection_reason: rejectionReason,
      });
      onRejected();
    } catch (err) {
      setError((err as Error).message);
      setDecisionState("confirming_reject");
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="w-full"
    >
      {/* Page header */}
      <div className="text-center mb-8">
        <h1 className="font-serif text-4xl lg:text-5xl font-bold text-text-primary mb-3">
          Review Ready
        </h1>
        <p className="text-text-secondary mb-5">
          AI analysis complete for{" "}
          <span className="italic text-text-primary">{fileName}</span>
        </p>
        {!loadingFindings && findings.length > 0 && (
          <div className="flex justify-center">
            <div className={cn("inline-flex items-center gap-2 rounded-full px-5 py-2", badge.bg)}>
              <BadgeIcon className={cn("h-4 w-4", badge.color)} />
              <span className={cn("text-xs font-bold tracking-widest", badge.color)}>
                {badge.label}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Findings — same style as VerdictCard */}
      {loadingFindings ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 text-text-secondary/40 animate-spin" />
        </div>
      ) : findings.length === 0 ? (
        <div className="py-16 text-center text-text-secondary text-sm">No findings recorded for this run.</div>
      ) : (
        <div className="mb-14">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-6 pb-3 border-b border-border">
            Flagged Clauses &amp; Document Text
          </h3>
          {findings.map((f, i) => {
            const cfg = severityConfig[f.severity] ?? severityConfig.medium;
            const isOpen = expandedIdx === i;
            return (
              <div key={f.finding_id} className="border-b border-border/60 last:border-0">
                <button
                  onClick={() => setExpandedIdx(isOpen ? null : i)}
                  className="flex w-full items-center justify-between py-4 text-left cursor-pointer"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={cn("shrink-0 rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide", cfg.style)}>
                      {cfg.label}
                    </span>
                    <span className="text-sm font-semibold text-text-primary truncate">
                      {f.description.split(/[.\n]/)[0]?.slice(0, 80) || f.clause_uid}
                    </span>
                  </div>
                  <ChevronsUpDown className="h-4 w-4 text-text-secondary/50 shrink-0 ml-3" />
                </button>
                <AnimatePresence>
                  {isOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      <div className="pb-5 pl-4 border-l-2 border-accent/30 space-y-2">
                        <p className="text-sm italic text-text-secondary leading-relaxed">
                          &ldquo;{f.description}&rdquo;
                        </p>
                        {f.recommendation && (
                          <p className="text-xs text-text-primary/70">{f.recommendation}</p>
                        )}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>
      )}

      {/* "I've reviewed" trigger */}
      {!loadingFindings && decisionState === "hidden" && (
        <div className="flex justify-center py-6 border-t border-border">
          <button
            onClick={() => setDecisionState("idle")}
            className="flex items-center gap-2 text-sm font-semibold text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
          >
            I&apos;ve reviewed — make a decision
            <ChevronDown className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Decision panel — old UI style */}
      <AnimatePresence>
        {decisionState !== "hidden" && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.4 }}
            className="max-w-2xl mx-auto space-y-8 pt-6"
          >
            {/* Analysis Complete card */}
            <div className="rounded-2xl border border-border bg-surface p-8 space-y-6">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-risk-low/10 border border-risk-low/30">
                  <ShieldCheck className="h-6 w-6 text-risk-low" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-text-primary uppercase tracking-widest">
                    Analysis Complete
                  </p>
                  <p className="text-sm text-text-secondary mt-0.5">
                    All AI reviewer stages have finished. Your sign-off is required to finalize.
                  </p>
                </div>
              </div>
              <div className="border-t border-border pt-6 space-y-3 text-sm text-text-secondary">
                <div className="flex justify-between">
                  <span>Harvey branch (internal policy)</span>
                  <span className="text-risk-low font-medium">Complete</span>
                </div>
                <div className="flex justify-between">
                  <span>Kira branch (compliance)</span>
                  <span className="text-risk-low font-medium">Complete</span>
                </div>
                <div className="flex justify-between">
                  <span>Final reviewer consensus</span>
                  <span className="text-risk-low font-medium">Complete</span>
                </div>
              </div>
            </div>

            {/* Reject reason */}
            <AnimatePresence>
              {decisionState === "confirming_reject" && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="space-y-4 border-t border-risk-high/25 pt-4"
                >
                  <p className="text-sm font-semibold text-risk-high">Provide a reason for rejection</p>
                  <textarea
                    value={rejectionReason}
                    onChange={(e) => setRejectionReason(e.target.value)}
                    rows={3}
                    placeholder="e.g. Insufficient evidence for flagged clauses..."
                    className="w-full border-b border-border bg-transparent px-0 py-2 text-sm text-text-primary placeholder:text-text-secondary/40 resize-none focus:outline-none focus:border-risk-high/50 transition-colors"
                    autoFocus
                  />
                  <div className="flex gap-3">
                    <button
                      onClick={() => { setDecisionState("idle"); setError(null); }}
                      className="flex-1 rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-text-secondary hover:bg-drop-zone transition-colors cursor-pointer"
                    >
                      Cancel
                    </button>
                    <button
                      disabled={isSubmitting}
                      onClick={handleReject}
                      className="flex-1 rounded-xl bg-risk-high px-4 py-2.5 text-sm font-semibold text-white hover:bg-risk-high/80 transition-colors disabled:opacity-40 cursor-pointer"
                    >
                      {isSubmitting ? "Submitting..." : "Confirm Rejection"}
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {error && <p className="text-sm text-risk-high text-center">{error}</p>}

            {/* Action buttons */}
            {decisionState !== "confirming_reject" && (
              <div className="flex gap-4">
                <button
                  disabled={isSubmitting}
                  onClick={() => { setDecisionState("confirming_reject"); setError(null); }}
                  className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-border px-6 py-3.5 text-sm font-semibold text-text-secondary hover:bg-drop-zone hover:text-text-primary transition-colors disabled:opacity-40 cursor-pointer"
                >
                  <XCircle className="h-4 w-4" />
                  Reject
                </button>
                <button
                  disabled={isSubmitting}
                  onClick={onStartReview}
                  className="flex flex-2 flex-1 items-center justify-center gap-2 rounded-xl bg-accent px-8 py-3.5 text-sm font-semibold text-white hover:bg-accent-hover transition-colors disabled:opacity-40 cursor-pointer"
                >
                  <CheckCircle2 className="h-4 w-4" /> Start Reviewing
                </button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
