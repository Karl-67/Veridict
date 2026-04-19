import { useEffect, useRef, useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, FileText, ShieldAlert, ShieldCheck, AlertTriangle, X } from "lucide-react";
import { listContracts } from "@/lib/api";
import type { ContractSummary } from "@/types";
import { cn } from "@/lib/utils";

interface SearchModalProps {
  open: boolean;
  onClose: () => void;
  onSelect: (contract: ContractSummary) => void;
}

function riskIcon(risk: string | null) {
  if (risk === "high" || risk === "critical") return <ShieldAlert className="h-3.5 w-3.5 text-risk-high" />;
  if (risk === "medium") return <AlertTriangle className="h-3.5 w-3.5 text-risk-medium" />;
  if (risk === "low") return <ShieldCheck className="h-3.5 w-3.5 text-risk-low" />;
  return null;
}

function stateColor(state: string | null): string {
  if (!state) return "text-text-secondary/30";
  if (state === "finalized") return "text-risk-low";
  if (state === "awaiting_human_review" || state === "under_review") return "text-accent";
  if (state === "failed" || state === "blocked") return "text-risk-high";
  return "text-text-secondary/50";
}

function stateLabel(state: string | null): string {
  const map: Record<string, string> = {
    finalized: "Finalized",
    awaiting_human_review: "Awaiting Review",
    under_review: "Under Review",
    processing: "Processing",
    pending: "Queued",
    failed: "Failed",
    blocked: "Blocked",
  };
  return state ? (map[state] ?? state) : "No runs";
}

export default function SearchModal({ open, onClose, onSelect }: SearchModalProps) {
  const [query, setQuery] = useState("");
  const [contracts, setContracts] = useState<ContractSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) { setQuery(""); setActiveIdx(0); return; }
    inputRef.current?.focus();
    if (contracts.length === 0) {
      setLoading(true);
      listContracts().then(setContracts).catch(() => {}).finally(() => setLoading(false));
    }
  }, [open]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return contracts.slice(0, 8);
    return contracts.filter(c =>
      c.name.toLowerCase().includes(q) ||
      (c.workspace_name?.toLowerCase().includes(q))
    ).slice(0, 8);
  }, [query, contracts]);

  useEffect(() => setActiveIdx(0), [results]);

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, results.length - 1)); }
    if (e.key === "ArrowUp")   { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, 0)); }
    if (e.key === "Enter" && results[activeIdx]) { onSelect(results[activeIdx]); onClose(); }
    if (e.key === "Escape") onClose();
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={onClose}
            className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.97, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -8 }}
            transition={{ duration: 0.15 }}
            className="fixed left-1/2 top-[15%] z-50 w-full max-w-xl -translate-x-1/2"
          >
            <div className="rounded-2xl border border-border bg-surface shadow-2xl shadow-black/30 overflow-hidden">
              {/* Input */}
              <div className="flex items-center gap-3 px-4 py-3.5 border-b border-border/60">
                <Search className="h-4 w-4 text-text-secondary/40 shrink-0" />
                <input
                  ref={inputRef}
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  onKeyDown={handleKey}
                  placeholder="Search contracts..."
                  className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-secondary/30 focus:outline-none"
                />
                <button onClick={onClose} className="shrink-0 text-text-secondary/30 hover:text-text-secondary transition-colors cursor-pointer">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              {/* Results */}
              <div className="max-h-80 overflow-y-auto">
                {loading ? (
                  <div className="py-10 text-center text-xs text-text-secondary/40">Loading…</div>
                ) : results.length === 0 ? (
                  <div className="py-10 text-center text-xs text-text-secondary/40">
                    {query ? `No contracts matching "${query}"` : "No contracts found"}
                  </div>
                ) : (
                  <>
                    {query === "" && (
                      <p className="px-4 pt-3 pb-1 text-[10px] font-bold uppercase tracking-widest text-text-secondary/30">
                        Recent
                      </p>
                    )}
                    {results.map((c, i) => (
                      <button
                        key={c.id}
                        onClick={() => { onSelect(c); onClose(); }}
                        onMouseEnter={() => setActiveIdx(i)}
                        className={cn(
                          "w-full flex items-center gap-3 px-4 py-3 text-left transition-colors cursor-pointer",
                          i === activeIdx ? "bg-accent/8" : "hover:bg-drop-zone/20"
                        )}
                      >
                        <div className={cn(
                          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
                          i === activeIdx ? "border-accent/25 bg-accent/10 text-accent" : "border-border bg-surface/50 text-text-secondary/40"
                        )}>
                          <FileText className="h-3.5 w-3.5" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-text-primary truncate">{c.name}</p>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className={cn("text-xs", stateColor(c.latest_run_state))}>
                              {stateLabel(c.latest_run_state)}
                            </span>
                            {c.latest_risk && (
                              <>
                                <span className="text-text-secondary/20 text-xs">·</span>
                                <span className="flex items-center gap-1">{riskIcon(c.latest_risk)}</span>
                              </>
                            )}
                            {c.workspace_name && (
                              <>
                                <span className="text-text-secondary/20 text-xs">·</span>
                                <span className="text-xs text-text-secondary/35 truncate">{c.workspace_name}</span>
                              </>
                            )}
                          </div>
                        </div>
                        {c.latest_label && (
                          <span className="shrink-0 rounded bg-border/50 px-1.5 py-0.5 text-[10px] font-mono text-text-secondary/50">
                            {c.latest_label}
                          </span>
                        )}
                      </button>
                    ))}
                  </>
                )}
              </div>

              {/* Footer hint */}
              <div className="flex items-center gap-4 px-4 py-2.5 border-t border-border/40 bg-surface/40">
                <span className="text-[10px] text-text-secondary/30">
                  <kbd className="rounded border border-border/60 px-1.5 py-0.5 font-mono text-[9px]">↑↓</kbd> navigate
                </span>
                <span className="text-[10px] text-text-secondary/30">
                  <kbd className="rounded border border-border/60 px-1.5 py-0.5 font-mono text-[9px]">↵</kbd> open
                </span>
                <span className="text-[10px] text-text-secondary/30">
                  <kbd className="rounded border border-border/60 px-1.5 py-0.5 font-mono text-[9px]">Esc</kbd> close
                </span>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
