import { Lightbulb } from "lucide-react";

export default function QuickTip() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-center gap-2 mb-2">
        <Lightbulb className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-bold text-text-primary">Quick Tip</h3>
      </div>
      <p className="text-sm leading-relaxed text-text-secondary">
        Compare multiple versions of the same contract to highlight subtle
        changes in liability clauses automatically.
      </p>
    </div>
  );
}
