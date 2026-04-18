import { useEffect, useState } from "react";
import { FileText, ChevronRight, Loader2 } from "lucide-react";
import { listContracts } from "@/lib/api";
import type { ContractSummary } from "@/types";
import { cn } from "@/lib/utils";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function statusText(c: ContractSummary): string {
  if (!c.latest_run_state) return "No analysis yet";
  const map: Record<string, string> = {
    finalized: c.latest_risk
      ? `${c.latest_risk.charAt(0).toUpperCase() + c.latest_risk.slice(1)} risk · ${timeAgo(c.updated_at)}`
      : `Analyzed ${timeAgo(c.updated_at)}`,
    awaiting_human_review: "Awaiting review",
    processing: "Processing…",
    pending: "Queued",
    failed: "Analysis failed",
    blocked: "Blocked",
  };
  return map[c.latest_run_state] ?? c.latest_run_state;
}

interface RecentActivityProps {
  onViewAll?: () => void;
  onOpen?: (contract: ContractSummary) => void;
}

export default function RecentActivity({ onViewAll, onOpen }: RecentActivityProps) {
  const [contracts, setContracts] = useState<ContractSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // No workspace filter — returns all contracts visible to the user
    listContracts()
      .then((data) => setContracts(data.slice(0, 3)))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-bold uppercase tracking-widest text-accent">
          Recent Contracts
        </h3>
        {onViewAll && (
          <button
            onClick={onViewAll}
            className="text-xs text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
          >
            View All
          </button>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="h-4 w-4 animate-spin text-text-secondary/40" />
        </div>
      ) : contracts.length === 0 ? (
        <p className="text-xs text-text-secondary/50 py-4">No contracts yet.</p>
      ) : (
        <div>
          {contracts.map((c) => (
            <div
              key={c.id}
              onClick={() => onOpen?.(c)}
              className={cn(
                "flex items-center gap-3 py-3 border-b border-border/60 last:border-0 transition-colors -mx-2 px-2",
                onOpen ? "hover:bg-drop-zone/20 cursor-pointer" : "cursor-default",
                c.latest_run_state === "awaiting_human_review" && "border-l-2 border-l-accent ml-0 pl-2"
              )}
            >
              <FileText className="h-4 w-4 text-text-secondary/60 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-text-primary truncate">{c.name}</p>
                <p className="text-xs text-text-secondary">{statusText(c)}</p>
              </div>
              {onOpen && <ChevronRight className="h-4 w-4 text-text-secondary/40 shrink-0" />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
