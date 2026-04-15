import { FileText, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const ITEMS = [
  { name: "SaaS_Agreement_V2.pdf", status: "Analyzed 2h ago", accent: false },
  { name: "Employment_Contract_...", status: "Draft saved", accent: true },
  { name: "Office_Lease_Standard...", status: "Analyzed 1d ago", accent: false },
];

export default function RecentActivity() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-bold uppercase tracking-widest text-accent">
          Recent Activity
        </h3>
        <a
          href="#"
          className="text-xs text-text-secondary hover:text-text-primary transition-colors"
        >
          View All
        </a>
      </div>
      <div className="space-y-1">
        {ITEMS.map((item, i) => (
          <div
            key={i}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3 py-3 transition-colors hover:bg-drop-zone cursor-pointer",
              item.accent && "border-l-2 border-accent"
            )}
          >
            <FileText className="h-4 w-4 text-text-secondary/60 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-text-primary truncate">
                {item.name}
              </p>
              <p className="text-xs text-text-secondary">{item.status}</p>
            </div>
            <ChevronRight className="h-4 w-4 text-text-secondary/40 shrink-0" />
          </div>
        ))}
      </div>
    </div>
  );
}
