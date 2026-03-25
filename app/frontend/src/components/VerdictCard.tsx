import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  ShieldAlert,
  ShieldCheck,
  ChevronDown,
  ArrowRight,
  Download,
} from "lucide-react";
import type { ReviewResult } from "@/types";
import { cn } from "@/lib/utils";

interface VerdictCardProps {
  result: ReviewResult;
}

const riskConfig = {
  high: { color: "text-risk-high", bg: "bg-risk-high/15", icon: ShieldAlert, label: "High Risk" },
  medium: { color: "text-risk-medium", bg: "bg-risk-medium/15", icon: AlertTriangle, label: "Medium Risk" },
  low: { color: "text-risk-low", bg: "bg-risk-low/15", icon: ShieldCheck, label: "Low Risk" },
};

const severityStyles = {
  high: "bg-risk-high/15 text-risk-high",
  medium: "bg-risk-medium/15 text-risk-medium",
  low: "bg-risk-low/15 text-risk-low",
};

export default function VerdictCard({ result }: VerdictCardProps) {
  const [expandedClause, setExpandedClause] = useState<number | null>(null);
  const risk = riskConfig[result.risk_level];
  const RiskIcon = risk.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: "easeOut" }}
      className="w-full max-w-2xl mx-auto"
    >
      <div className="rounded-xl border border-border bg-surface shadow-xl shadow-black/30 overflow-hidden">
        {/* Risk Badge */}
        <div className="flex items-center gap-3 border-b border-border px-6 py-4">
          <div className={cn("flex items-center gap-2 rounded-full px-3 py-1.5", risk.bg)}>
            <RiskIcon className={cn("h-4 w-4", risk.color)} />
            <span className={cn("text-sm font-semibold", risk.color)}>
              {risk.label}
            </span>
          </div>
          <span className="text-sm text-text-muted">Contract Verdict</span>
        </div>

        <div className="p-6 space-y-6">
          {/* Summary */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
              Summary
            </h4>
            <p className="text-sm leading-relaxed text-text-primary/90">
              {result.summary}
            </p>
          </div>

          {/* Flagged Clauses */}
          {result.clause_flags.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
                Flagged Clauses ({result.clause_flags.length})
              </h4>
              <div className="space-y-2">
                {result.clause_flags.map((flag, i) => (
                  <div
                    key={i}
                    className="rounded-lg border border-border bg-background/50"
                  >
                    <button
                      onClick={() =>
                        setExpandedClause(expandedClause === i ? null : i)
                      }
                      className="flex w-full items-center justify-between px-4 py-3 text-left cursor-pointer"
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className={cn(
                            "rounded-full px-2 py-0.5 text-xs font-medium",
                            severityStyles[flag.severity]
                          )}
                        >
                          {flag.severity}
                        </span>
                        <span className="text-sm font-medium text-text-primary">
                          {flag.clause}
                        </span>
                      </div>
                      <ChevronDown
                        className={cn(
                          "h-4 w-4 text-text-muted transition-transform",
                          expandedClause === i && "rotate-180"
                        )}
                      />
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
                          <p className="px-4 pb-3 text-sm text-text-muted">
                            {flag.issue}
                          </p>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommendations */}
          {result.recommendations.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
                Recommendations
              </h4>
              <ol className="space-y-2">
                {result.recommendations.map((rec, i) => (
                  <li key={i} className="flex items-start gap-3 text-sm">
                    <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <span className="text-text-primary/90">{rec}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>

        {/* Export button */}
        <div className="border-t border-border px-6 py-4">
          <button className="flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-text-muted transition-colors hover:bg-background hover:text-text-primary cursor-pointer">
            <Download className="h-4 w-4" />
            Export Report
          </button>
        </div>
      </div>
    </motion.div>
  );
}
