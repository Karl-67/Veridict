import { Lightbulb } from "lucide-react";

export default function QuickTip() {
  return (
    <div className="pt-5 border-t border-border/60">
      <div className="flex items-center gap-2 mb-1.5">
        <Lightbulb className="h-3.5 w-3.5 text-accent" />
        <span className="text-[10px] font-bold uppercase tracking-widest text-accent">
          Quick Tip
        </span>
      </div>
      <p className="text-sm leading-relaxed text-text-secondary">
        Compare multiple versions of the same contract to highlight subtle
        changes in liability clauses automatically.
      </p>
    </div>
  );
}
