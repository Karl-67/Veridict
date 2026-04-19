import { useState, useEffect, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle, ShieldAlert, ShieldCheck, ChevronDown,
  ArrowRight, Download, FileEdit, CalendarDays,
  CheckCircle2, XCircle, Loader2, Zap, MessageSquare,
} from "lucide-react";
import type { ReviewResult, Finding, Comment } from "@/types";
import { cn } from "@/lib/utils";
import ContractReader from "@/components/ContractReader";
import CommentThread from "@/components/CommentThread";
import { listContractComments, createContractComment, deleteContractComment } from "@/lib/api";

// ─── Props ────────────────────────────────────────────────────────────────────

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

// ─── Design config ────────────────────────────────────────────────────────────

const riskConfig = {
  high:   { color: "text-risk-high",   bg: "bg-risk-high/10",   Icon: ShieldAlert,   label: "HIGH RISK EXPOSURE" },
  medium: { color: "text-risk-medium", bg: "bg-risk-medium/10", Icon: AlertTriangle, label: "MEDIUM RISK EXPOSURE" },
  low:    { color: "text-risk-low",    bg: "bg-risk-low/10",    Icon: ShieldCheck,   label: "LOW RISK EXPOSURE" },
};

const severityConfig = {
  critical: { label: "CRITICAL", badge: "bg-risk-high/15 text-risk-high",     border: "border-l-risk-high",      dot: "bg-risk-high" },
  high:     { label: "HIGH",     badge: "bg-risk-high/10 text-risk-high",     border: "border-l-risk-high/50",   dot: "bg-risk-high/60" },
  medium:   { label: "WARNING",  badge: "bg-risk-medium/15 text-risk-medium", border: "border-l-risk-medium",    dot: "bg-risk-medium" },
  low:      { label: "LOW",      badge: "bg-risk-low/10 text-risk-low",       border: "border-l-risk-low/40",    dot: "bg-risk-low/50" },
};

const BENCHMARKS = [
  { metric: "Liability Cap",      document: "300% Fees", flag: true,  industry: "100% Fees", firm: "100% Fees" },
  { metric: "Termination Notice", document: "90 Days",   flag: true,  industry: "45 Days",   firm: "30 Days" },
  { metric: "Warranty Period",    document: "12 Months", flag: false, industry: "6 Months",  firm: "12 Months" },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatAction(raw: string): { title: string; detail: string } {
  const map: Record<string, { title: string; detail: string }> = {
    accept_with_note:      { title: "Accept with notation",       detail: "Document the clause as accepted and attach a risk note for future reference" },
    seek_legal_advice:     { title: "Seek legal counsel",         detail: "Consult a qualified attorney before proceeding with this agreement" },
    negotiate_terms:       { title: "Negotiate revised terms",    detail: "Propose amended language to reduce your firm's risk exposure" },
    reject_clause:         { title: "Reject this clause",         detail: "Require removal or substantial revision of this clause before signing" },
    escalate:              { title: "Escalate to senior counsel", detail: "Flag this issue for partner-level review before proceeding" },
    request_clarification: { title: "Request clarification",      detail: "Ask the counterparty to provide more precise and unambiguous language" },
    standard_review:       { title: "Standard legal review",      detail: "Route through your standard contract approval process" },
    immediate_review:      { title: "Immediate review required",  detail: "This requires urgent attention before any further action" },
  };
  const key = raw.toLowerCase().replace(/[\s\-]+/g, "_");
  if (map[key]) return map[key];
  if (raw.includes(" ") && !raw.includes("_")) {
    const parts = raw.split(".");
    return { title: parts[0]?.trim() || raw, detail: parts.slice(1).join(".").trim() };
  }
  return { title: raw.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()), detail: "" };
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionHeading({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p className={cn("text-[10px] font-bold uppercase tracking-[0.16em] text-text-secondary/40 mb-6", className)}>
      {children}
    </p>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

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
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [rejectMode, setRejectMode] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const risk = riskConfig[result.risk_level];
  const RiskIcon = risk.Icon;
  const alignmentScore = result.risk_level === "high" ? 42 : result.risk_level === "medium" ? 65 : 88;

  // Prefer full Finding objects (richer data) over clause_flags
  const displayFindings = useMemo(() => {
    if (findings && findings.length > 0) {
      return findings.map(f => ({
        id: f.finding_id,
        severity: f.severity as keyof typeof severityConfig,
        title: f.description.split(/[.\n]/)[0]?.slice(0, 100) || f.clause_uid,
        quote: f.description,
        recommendation: f.recommendation_detail || f.recommendation,
      }));
    }
    return result.clause_flags.map((f, i) => ({
      id: String(i),
      severity: (f.severity === "high" ? "critical" : f.severity) as keyof typeof severityConfig,
      title: f.clause,
      quote: f.issue,
      recommendation: "This clause requires legal review and potential renegotiation.",
    }));
  }, [findings, result.clause_flags]);

  const counts = useMemo(() => {
    const c = { critical: 0, high: 0, medium: 0, low: 0 };
    displayFindings.forEach(f => { if (f.severity in c) c[f.severity as keyof typeof c]++; });
    return c;
  }, [displayFindings]);

  // Comments
  const fetchComments = useCallback(async () => {
    if (!runId) return;
    try { setComments(await listContractComments(runId)); } catch { /* ignore */ }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    setCommentsLoading(true);
    fetchComments().finally(() => setCommentsLoading(false));
    const id = setInterval(fetchComments, 5000);
    return () => clearInterval(id);
  }, [runId, fetchComments]);

  const handlePost = useCallback(async (body: string) => {
    if (!runId) return;
    const comment = await createContractComment(runId, body);
    setComments(prev => [...prev, comment]);
  }, [runId]);

  const handleDelete = useCallback(async (id: string) => {
    if (!runId) return;
    await deleteContractComment(runId, id);
    setComments(prev => prev.filter(c => c.id !== id));
  }, [runId]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.5 }}
      className="w-full"
    >

      {/* ── Header ──────────────────────────────────────────────── */}
      <div className="mb-16 pb-10 border-b border-border/60">
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-secondary/35 mb-4">
          Contract Analysis Report
        </p>
        <h1 className="font-serif text-4xl lg:text-5xl font-bold text-text-primary leading-tight mb-3 max-w-3xl">
          {fileName}
        </h1>
        <p className="text-sm text-text-secondary/50 mb-8">
          {displayFindings.length} clause{displayFindings.length !== 1 ? "s" : ""} flagged &nbsp;·&nbsp;{" "}
          {new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
        </p>

        {/* Badges row */}
        <div className="flex flex-wrap items-center gap-3">
          <div className={cn("inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-bold tracking-widest", risk.bg, risk.color)}>
            <RiskIcon className="h-3.5 w-3.5" />
            {risk.label}
          </div>

          {humanAction === "approved" && (
            <div className="inline-flex items-center gap-2 rounded-full px-4 py-2 bg-risk-low/10 text-xs font-bold tracking-widest text-risk-low">
              <CheckCircle2 className="h-3.5 w-3.5" /> APPROVED
            </div>
          )}
          {humanAction === "rejected" && (
            <div className="inline-flex items-center gap-2 rounded-full px-4 py-2 bg-risk-high/10 text-xs font-bold tracking-widest text-risk-high">
              <XCircle className="h-3.5 w-3.5" /> REJECTED
            </div>
          )}

          {(counts.critical > 0 || counts.high > 0 || counts.medium > 0 || counts.low > 0) && (
            <div className="h-4 w-px bg-border mx-1" />
          )}

          {counts.critical > 0 && (
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-risk-high">
              <span className="h-2 w-2 rounded-full bg-risk-high" />{counts.critical} critical
            </span>
          )}
          {counts.high > 0 && (
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-risk-high/60">
              <span className="h-2 w-2 rounded-full bg-risk-high/50" />{counts.high} high
            </span>
          )}
          {counts.medium > 0 && (
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-risk-medium">
              <span className="h-2 w-2 rounded-full bg-risk-medium" />{counts.medium} medium
            </span>
          )}
          {counts.low > 0 && (
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-text-secondary/40">
              <span className="h-2 w-2 rounded-full bg-text-secondary/25" />{counts.low} low
            </span>
          )}
        </div>
      </div>

      {/* ── Contract Reader ──────────────────────────────────────── */}
      {runId && findings && findings.length > 0 && (
        <div className="mb-20">
          <SectionHeading>Contract Document</SectionHeading>
          <ContractReader runId={runId} findings={findings} />
        </div>
      )}

      {/* ── Two-column layout ────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-20 items-start">

        {/* LEFT COLUMN */}
        <div className="space-y-20 min-w-0">

          {/* Flagged clauses */}
          <div>
            <SectionHeading>Flagged Clauses &amp; Risks</SectionHeading>
            <div className="space-y-3">
              {displayFindings.map((f, i) => {
                const cfg = severityConfig[f.severity] ?? severityConfig.low;
                const open = expandedIdx === i;
                return (
                  <div
                    key={f.id}
                    className={cn(
                      "rounded-2xl border border-l-4 transition-all duration-200",
                      cfg.border,
                      open
                        ? "border-border bg-surface"
                        : "border-border/50 bg-surface/30 hover:bg-surface/60 hover:border-border"
                    )}
                  >
                    <button
                      onClick={() => setExpandedIdx(open ? null : i)}
                      className="flex w-full items-start gap-4 px-5 py-4 text-left cursor-pointer"
                    >
                      <span className={cn("shrink-0 mt-0.5 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide whitespace-nowrap", cfg.badge)}>
                        {cfg.label}
                      </span>
                      <span className="flex-1 text-sm font-medium text-text-primary leading-snug">
                        {f.title}
                      </span>
                      <motion.span
                        animate={{ rotate: open ? 180 : 0 }}
                        transition={{ duration: 0.2 }}
                        className="shrink-0 mt-0.5 text-text-secondary/30"
                      >
                        <ChevronDown className="h-4 w-4" />
                      </motion.span>
                    </button>

                    <AnimatePresence>
                      {open && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.22 }}
                          className="overflow-hidden"
                        >
                          <div className="px-5 pb-5 pt-1 space-y-4 border-t border-border/40">
                            <blockquote className="pl-4 border-l-2 border-text-secondary/15 text-sm italic text-text-secondary leading-relaxed">
                              &ldquo;{f.quote}&rdquo;
                            </blockquote>
                            {f.recommendation && (
                              <div className="flex items-start gap-2.5 rounded-xl bg-accent/5 px-4 py-3">
                                <Zap className="h-3.5 w-3.5 text-accent shrink-0 mt-0.5" />
                                <p className="text-xs font-medium text-text-primary/70 leading-relaxed">
                                  {f.recommendation}
                                </p>
                              </div>
                            )}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Compliance benchmarking */}
          <div>
            <SectionHeading>Compliance Benchmarking</SectionHeading>
            <div className="rounded-2xl border border-border/60 overflow-hidden">
              <div className="grid grid-cols-4 gap-0 bg-surface/60 border-b border-border/60 px-6 py-3.5">
                {["Metric", "This Document", "Industry Avg", "Firm Standard"].map(h => (
                  <span key={h} className="text-[10px] font-bold uppercase tracking-widest text-text-secondary/40">{h}</span>
                ))}
              </div>
              {BENCHMARKS.map((row) => (
                <div
                  key={row.metric}
                  className={cn(
                    "grid grid-cols-4 gap-0 px-6 py-4 border-b border-border/40 last:border-0",
                    row.flag && "bg-risk-high/[0.03]"
                  )}
                >
                  <span className="text-sm font-medium text-text-primary">{row.metric}</span>
                  <div className="flex items-center gap-2">
                    {row.flag && <span className="h-1.5 w-1.5 rounded-full bg-risk-high shrink-0" />}
                    <span className={cn("text-sm font-semibold", row.flag ? "text-risk-high" : "text-text-primary")}>
                      {row.document}
                    </span>
                  </div>
                  <span className="text-sm text-text-secondary/60">{row.industry}</span>
                  <span className="text-sm text-text-secondary/60">{row.firm}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Alignment score */}
          <div className="rounded-2xl border border-border/60 bg-surface/20 px-8 py-8">
            <div className="flex items-end justify-between mb-8">
              <div>
                <SectionHeading className="mb-2">Policy Alignment Score</SectionHeading>
                <p className="text-xs text-text-secondary/40">Measured against firm standard of 85%</p>
              </div>
              <span className={cn(
                "text-6xl font-bold tabular-nums leading-none",
                alignmentScore >= 70 ? "text-risk-low" : alignmentScore >= 50 ? "text-risk-medium" : "text-risk-high"
              )}>
                {alignmentScore}<span className="text-4xl">%</span>
              </span>
            </div>

            <div className="relative h-2 rounded-full bg-border/60 overflow-visible">
              <motion.div
                className={cn(
                  "h-full rounded-full",
                  alignmentScore >= 70 ? "bg-risk-low" : alignmentScore >= 50 ? "bg-risk-medium" : "bg-risk-high"
                )}
                initial={{ width: 0 }}
                animate={{ width: `${alignmentScore}%` }}
                transition={{ duration: 1.2, ease: "easeOut", delay: 0.2 }}
              />
              {/* Firm standard tick */}
              <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-5 w-px bg-text-secondary/30" style={{ left: "85%" }} />
            </div>

            <div className="flex justify-between items-start mt-3 mb-5">
              <span className="text-xs text-text-secondary/25">0%</span>
              <span className="text-[10px] text-text-secondary/35 flex flex-col items-center gap-0.5">
                <span>↑</span>
                <span>Firm standard 85%</span>
              </span>
              <span className="text-xs text-text-secondary/25">100%</span>
            </div>

            <p className={cn(
              "text-xs font-semibold",
              alignmentScore >= 70 ? "text-risk-low" : alignmentScore >= 50 ? "text-risk-medium" : "text-risk-high"
            )}>
              {alignmentScore >= 70
                ? "Within acceptable range — minor attention needed"
                : alignmentScore >= 50
                  ? "Moderately below standard — review recommended before signing"
                  : "Significantly below firm standard — action required before proceeding"}
            </p>
          </div>

        </div>

        {/* RIGHT COLUMN — sticky */}
        <div className="space-y-10 lg:sticky lg:top-8 lg:self-start">

          {/* ── Decision card ── */}
          {isAwaitingReview && (
            <div className="rounded-2xl border border-accent/20 bg-gradient-to-b from-accent/[0.06] to-transparent p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="h-10 w-10 rounded-xl bg-accent/15 flex items-center justify-center shrink-0">
                  <ShieldCheck className="h-5 w-5 text-accent" />
                </div>
                <div>
                  <p className="text-sm font-bold text-text-primary">Sign-off Required</p>
                  <p className="text-xs text-text-secondary/50 mt-0.5">Your decision finalizes this contract review</p>
                </div>
              </div>

              {reviewError && (
                <p className="text-xs text-risk-high bg-risk-high/8 rounded-xl px-4 py-2.5 mb-4">{reviewError}</p>
              )}

              <AnimatePresence>
                {rejectMode && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="mb-4 space-y-3">
                      <p className="text-xs font-semibold text-risk-high/80 uppercase tracking-wide">
                        Reason for rejection
                      </p>
                      <textarea
                        value={rejectionReason}
                        onChange={e => setRejectionReason(e.target.value)}
                        rows={3}
                        placeholder="Describe why this contract cannot be approved..."
                        className="w-full rounded-xl border border-border/60 bg-background px-4 py-3 text-sm text-text-primary placeholder:text-text-secondary/30 resize-none focus:outline-none focus:border-risk-high/30 transition-colors"
                        autoFocus
                      />
                      <div className="flex gap-2">
                        <button
                          onClick={() => { setRejectMode(false); setReviewError(null); }}
                          className="flex-1 rounded-xl border border-border px-3 py-2.5 text-xs font-semibold text-text-secondary hover:bg-drop-zone transition-colors cursor-pointer"
                        >
                          Cancel
                        </button>
                        <button
                          disabled={rejecting}
                          onClick={async () => {
                            if (!rejectionReason.trim()) { setReviewError("Please provide a reason."); return; }
                            setRejecting(true); setReviewError(null);
                            try { await onReject?.(rejectionReason); }
                            catch (e) { setReviewError((e as Error).message); setRejecting(false); }
                          }}
                          className="flex-1 rounded-xl bg-risk-high px-3 py-2.5 text-xs font-semibold text-white hover:bg-risk-high/80 transition-colors disabled:opacity-40 cursor-pointer"
                        >
                          {rejecting ? <Loader2 className="h-3.5 w-3.5 animate-spin mx-auto" /> : "Confirm Rejection"}
                        </button>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {!rejectMode && (
                <div className="flex gap-3">
                  <button
                    disabled={approving}
                    onClick={() => { setRejectMode(true); setReviewError(null); }}
                    className="flex-1 flex items-center justify-center gap-2 rounded-xl border border-border bg-background px-4 py-3 text-sm font-semibold text-text-secondary hover:border-risk-high/30 hover:text-risk-high transition-all disabled:opacity-40 cursor-pointer"
                  >
                    <XCircle className="h-4 w-4" /> Reject
                  </button>
                  <button
                    disabled={approving}
                    onClick={async () => {
                      setApproving(true); setReviewError(null);
                      try { await onApprove?.(); }
                      catch (e) { setReviewError((e as Error).message); setApproving(false); }
                    }}
                    className="flex-1 flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white hover:bg-accent-hover transition-colors disabled:opacity-40 cursor-pointer shadow-sm"
                  >
                    {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <><CheckCircle2 className="h-4 w-4" /> Approve</>}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* ── Legal Team Notes ── */}
          <div>
            <div className="flex items-center gap-2 mb-5">
              <MessageSquare className="h-3 w-3 text-text-secondary/35" />
              <SectionHeading className="mb-0">Legal Team Notes</SectionHeading>
            </div>
            <CommentThread
              comments={comments}
              loading={commentsLoading}
              onPost={handlePost}
              onDelete={handleDelete}
            />
          </div>

          {/* ── Immediate Actions ── */}
          {result.recommendations.length > 0 && (
            <div>
              <SectionHeading>Immediate Actions</SectionHeading>
              <div className="space-y-2.5">
                {result.recommendations.slice(0, 3).map((rec, i) => {
                  const { title, detail } = formatAction(rec);
                  return (
                    <div
                      key={i}
                      className="flex gap-4 rounded-xl border border-border/50 bg-surface/30 px-5 py-4 hover:bg-surface/60 transition-colors"
                    >
                      <span className="text-[22px] font-bold text-accent/20 tabular-nums leading-none shrink-0 pt-0.5 select-none">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <div>
                        <p className="text-sm font-semibold text-text-primary leading-snug">{title}</p>
                        {detail && (
                          <p className="text-xs text-text-secondary/50 leading-relaxed mt-1">{detail}</p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Next Steps ── */}
          <div>
            <SectionHeading>Next Steps</SectionHeading>
            <div className="space-y-2.5">
              {[
                {
                  icon: FileEdit,
                  label: "Generate Redline",
                  description: "AI-drafted revision with tracked changes",
                  accent: true,
                },
                {
                  icon: CalendarDays,
                  label: "Schedule Partner Review",
                  description: "Book a review session with your team",
                  accent: false,
                },
                {
                  icon: Download,
                  label: "Export Report",
                  description: "Download full analysis as PDF",
                  accent: false,
                },
              ].map(({ icon: Icon, label, description, accent }) => (
                <button
                  key={label}
                  className={cn(
                    "group flex w-full items-center gap-4 rounded-2xl border px-5 py-4 text-left transition-all duration-200 cursor-pointer",
                    accent
                      ? "border-accent/25 bg-accent/[0.06] hover:bg-accent/10 hover:border-accent/40"
                      : "border-border/60 bg-surface/20 hover:bg-surface/60 hover:border-border"
                  )}
                >
                  <div className={cn(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-colors",
                    accent
                      ? "bg-accent/15 text-accent group-hover:bg-accent/20"
                      : "bg-border/40 text-text-secondary/50 group-hover:bg-border/70 group-hover:text-text-secondary"
                  )}>
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className={cn(
                      "text-sm font-semibold leading-snug",
                      accent ? "text-text-primary" : "text-text-primary/80"
                    )}>
                      {label}
                    </p>
                    <p className="text-xs text-text-secondary/45 mt-0.5">{description}</p>
                  </div>
                  <ArrowRight className={cn(
                    "h-3.5 w-3.5 shrink-0 transition-all duration-200 -translate-x-1 opacity-0 group-hover:translate-x-0 group-hover:opacity-100",
                    accent ? "text-accent" : "text-text-secondary/40"
                  )} />
                </button>
              ))}
            </div>
          </div>

          {/* ── Back link ── */}
          <button
            onClick={onReset}
            className="flex items-center gap-1.5 text-sm text-text-secondary/40 hover:text-text-secondary transition-colors cursor-pointer"
          >
            {resetLabel}
            <ArrowRight className="h-3.5 w-3.5" />
          </button>

        </div>
      </div>
    </motion.div>
  );
}
