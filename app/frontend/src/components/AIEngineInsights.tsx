import { Sparkles } from "lucide-react";

interface AIEngineInsightsProps {
  fileName: string;
  charCount: number;
}

export default function AIEngineInsights({
  fileName,
  charCount,
}: AIEngineInsightsProps) {
  const rows = [
    { label: "Document Name", value: fileName },
    { label: "Character Count", value: charCount.toLocaleString() },
    { label: "Language Detected", value: "ENGLISH (US)", isBadge: true },
    { label: "Estimated Complexity", value: "High", isBar: true },
    { label: "Neural Tokens", value: `${(charCount / 3.4).toFixed(1)}k consumed` },
  ];

  return (
    <div className="rounded-2xl border border-border bg-surface p-6 h-fit">
      <div className="flex items-center gap-2 mb-6">
        <Sparkles className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold text-accent">
          AI Engine Insights
        </h3>
      </div>
      <div className="space-y-4">
        {rows.map((row) => (
          <div
            key={row.label}
            className="flex items-center justify-between gap-4"
          >
            <span className="text-sm text-text-secondary whitespace-nowrap">
              {row.label}
            </span>
            {row.isBadge ? (
              <span className="rounded-md bg-text-primary/10 px-2 py-0.5 text-xs font-bold tracking-wide text-text-primary">
                {row.value}
              </span>
            ) : row.isBar ? (
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-16 rounded-full bg-border overflow-hidden">
                  <div className="h-full w-[85%] rounded-full bg-accent" />
                </div>
                <span className="text-sm font-medium text-text-primary">
                  {row.value}
                </span>
              </div>
            ) : (
              <span className="text-sm font-medium text-text-primary text-right truncate max-w-[180px]">
                {row.value}
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="mt-6 rounded-xl bg-accent/8 border border-accent/15 p-4">
        <p className="text-xs italic leading-relaxed text-text-secondary">
          Scanning specifically for indemnification loops and jurisdiction
          conflicts common in Tech MSA frameworks.
        </p>
      </div>
    </div>
  );
}
