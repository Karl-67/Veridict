import { useState } from "react";
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
  Send,
} from "lucide-react";
import type { ReviewResult } from "@/types";
import { cn } from "@/lib/utils";

interface VerdictCardProps {
  result: ReviewResult;
  fileName: string;
  onReset: () => void;
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

const LEGAL_NOTES = [
  {
    author: "J. Sterling",
    time: "2h ago",
    text: "Section 14.2 is a non-starter. We need to push back hard on the liability cap before the Monday call.",
  },
  {
    author: "A. Chen",
    time: "4h ago",
    text: "Check if the Data Sovereignty clause affects our cloud migration plan.",
  },
];

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
}: VerdictCardProps) {
  const [expandedClause, setExpandedClause] = useState<number | null>(0);
  const risk = riskConfig[result.risk_level];
  const RiskIcon = risk.icon;

  const alignmentScore = result.risk_level === "high" ? 42 : result.risk_level === "medium" ? 65 : 88;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.5 }}
      className="w-full"
    >
      {/* Centered header */}
      <div className="text-center mb-8">
        <h1 className="font-serif text-4xl lg:text-5xl font-bold text-text-primary mb-3">
          Your Verdict
        </h1>
        <p className="text-text-secondary mb-4">
          Comprehensive risk analysis for{" "}
          <span className="italic text-text-primary">{fileName}</span>
        </p>
        <div className="flex justify-center">
          <div
            className={cn(
              "inline-flex items-center gap-2 rounded-full px-5 py-2",
              risk.bg
            )}
          >
            <RiskIcon className={cn("h-4 w-4", risk.color)} />
            <span
              className={cn("text-xs font-bold tracking-widest", risk.color)}
            >
              {risk.label}
            </span>
          </div>
        </div>
      </div>

      {/* Quote panel */}
      <div className="rounded-2xl border border-border bg-surface p-8 lg:p-10 mb-10">
        <p className="text-center font-serif text-lg lg:text-xl italic leading-relaxed text-text-primary/85">
          &ldquo;{result.summary}&rdquo;
        </p>
      </div>

      {/* Two-column grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-8 items-start">
        {/* Left column */}
        <div className="space-y-8">
          {/* Flagged Clauses */}
          <div>
            <div className="flex items-center gap-3 mb-6">
              <div className="h-px flex-1 bg-border" />
              <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary whitespace-nowrap">
                Flagged Clauses &amp; Document Text
              </h3>
              <div className="h-px flex-1 bg-border" />
            </div>
            <div className="space-y-4">
              {result.clause_flags.map((flag, i) => (
                <div
                  key={i}
                  className="rounded-2xl border border-border bg-surface overflow-hidden"
                >
                  <button
                    onClick={() =>
                      setExpandedClause(expandedClause === i ? null : i)
                    }
                    className="flex w-full items-center justify-between px-5 py-4 text-left cursor-pointer"
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={cn(
                          "rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
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
                        <div className="px-5 pb-5 space-y-3">
                          <div className="rounded-xl bg-drop-zone border border-border p-4">
                            <p className="text-sm italic text-text-secondary leading-relaxed">
                              &ldquo;{flag.issue}&rdquo;
                            </p>
                          </div>
                          <p className="text-sm text-text-primary/80">
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

          {/* Compliance Benchmarking */}
          <div>
            <div className="flex items-center gap-3 mb-6">
              <div className="h-px flex-1 bg-border" />
              <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary whitespace-nowrap">
                Compliance Benchmarking
              </h3>
              <div className="h-px flex-1 bg-border" />
            </div>
            <div className="rounded-2xl border border-border bg-surface overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-widest text-text-secondary">
                      Metric
                    </th>
                    <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-widest text-text-secondary">
                      This Document
                    </th>
                    <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-widest text-text-secondary">
                      Industry Avg
                    </th>
                    <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-widest text-text-secondary">
                      Firm Standard
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {BENCHMARKS.map((row) => (
                    <tr key={row.metric} className="border-b border-border last:border-0">
                      <td className="px-5 py-3 font-medium text-text-primary">
                        {row.metric}
                      </td>
                      <td
                        className={cn(
                          "px-5 py-3 font-medium",
                          row.documentFlag ? "text-risk-high" : "text-text-primary"
                        )}
                      >
                        {row.document}
                      </td>
                      <td className="px-5 py-3 text-text-secondary">
                        {row.industry}
                      </td>
                      <td className="px-5 py-3 text-text-secondary">
                        {row.firm}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Alignment score */}
              <div className="px-5 py-4 bg-drop-zone/50">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary">
                    Overall Alignment Score
                  </span>
                  <span className="text-2xl font-bold text-text-primary">
                    {alignmentScore}%
                  </span>
                </div>
                <div className="h-2 w-full rounded-full bg-border overflow-hidden">
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
        </div>

        {/* Right column */}
        <div className="space-y-6 lg:mt-12">
          {/* Legal Team Notes */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">
              Legal Team Notes
            </h3>
            <div className="space-y-3">
              {LEGAL_NOTES.map((note, i) => (
                <div
                  key={i}
                  className="rounded-xl border border-border bg-surface p-4 border-l-2 border-l-accent/40"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-semibold text-text-primary">
                      {note.author}
                    </span>
                    <span className="text-xs text-text-secondary">
                      {note.time}
                    </span>
                  </div>
                  <p className="text-sm leading-relaxed text-text-secondary">
                    {note.text}
                  </p>
                </div>
              ))}
            </div>
            {/* Comment input */}
            <div className="mt-3 relative">
              <textarea
                placeholder="Add a comment..."
                rows={2}
                className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-sm text-text-primary placeholder:text-text-secondary/50 resize-none focus:outline-none focus:border-accent/50"
              />
              <button className="absolute bottom-3 right-3 text-accent hover:text-accent-hover transition-colors cursor-pointer">
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Immediate Actions */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">
              Immediate Actions
            </h3>
            <div className="space-y-3">
              {result.recommendations.slice(0, 2).map((rec, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span className="text-2xl font-bold text-accent/40 leading-none">
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

          {/* Next Steps */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">
              Next Steps
            </h3>
            <div className="space-y-3">
              <button className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white hover:bg-accent-hover transition-colors cursor-pointer">
                <FileEdit className="h-4 w-4" />
                Generate Redline
              </button>
              <button className="flex w-full items-center justify-center gap-2 rounded-xl bg-text-primary/10 px-4 py-3 text-sm font-semibold text-text-primary hover:bg-text-primary/15 transition-colors cursor-pointer">
                <CalendarDays className="h-4 w-4" />
                Schedule Partner Review
              </button>
              <button className="flex w-full items-center justify-center gap-2 rounded-xl border border-border px-4 py-3 text-sm font-medium text-text-secondary hover:bg-drop-zone hover:text-text-primary transition-colors cursor-pointer">
                <Download className="h-4 w-4" />
                Export Report
              </button>
            </div>
          </div>

          {/* Review another */}
          <button
            onClick={onReset}
            className="flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary transition-colors cursor-pointer mx-auto"
          >
            Review another document
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </motion.div>
  );
}
