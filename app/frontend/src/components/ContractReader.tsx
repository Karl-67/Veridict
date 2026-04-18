import { useState, useCallback, useMemo } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { Loader2, ChevronLeft, ChevronRight, AlertCircle } from "lucide-react";
import { getRunFileUrl } from "@/lib/api";
import type { Finding } from "@/types";
import { cn } from "@/lib/utils";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

// ── Severity styling ─────────────────────────────────────────────────────────

const SEVERITY_CLASSES: Record<string, string> = {
  high: "cr-high",
  critical: "cr-high",
  medium: "cr-medium",
  low: "cr-low",
};

const SEVERITY_CHIP: Record<string, string> = {
  high: "bg-risk-high/15 text-risk-high border-risk-high/30",
  critical: "bg-risk-high/15 text-risk-high border-risk-high/30",
  medium: "bg-risk-medium/15 text-risk-medium border-risk-medium/30",
  low: "bg-risk-low/15 text-risk-low border-risk-low/30",
};

// ── Ordered findings ──────────────────────────────────────────────────────────

interface OrderedFinding {
  finding: Finding;
  index: number;       // 1-based display number
  firstPage: number;   // earliest page this finding appears on
}

function orderFindings(findings: Finding[]): OrderedFinding[] {
  return findings
    .map((f) => ({
      finding: f,
      firstPage: f.evidence.length > 0 ? Math.min(...f.evidence.map((e) => e.page)) : 999,
    }))
    .sort((a, b) => a.firstPage - b.firstPage)
    .map((item, i) => ({ finding: item.finding, index: i + 1, firstPage: item.firstPage }));
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface ContractReaderProps {
  runId: string;
  findings: Finding[];
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function ContractReader({ runId, findings }: ContractReaderProps) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [loadError, setLoadError] = useState(false);

  const ordered = useMemo(() => orderFindings(findings), [findings]);
  const fileUrl = getRunFileUrl(runId);

  // Build a lookup: page → list of OrderedFinding on that page
  const findingsByPage = useMemo(() => {
    const map = new Map<number, OrderedFinding[]>();
    for (const of_ of ordered) {
      const pages = of_.finding.evidence.map((e) => e.page);
      const uniquePages = [...new Set(pages)];
      for (const p of uniquePages) {
        if (!map.has(p)) map.set(p, []);
        map.get(p)!.push(of_);
      }
    }
    return map;
  }, [ordered]);

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setLoadError(false);
  }, []);

  const onDocumentLoadError = useCallback(() => setLoadError(true), []);

  // customTextRenderer: highlight text items matching any finding's normalized_text on this page
  const makeTextRenderer = useCallback(
    (pageNum: number) =>
      (textItem: { str: string }) => {
        const str = textItem.str;
        const trimmed = str.trim();
        if (trimmed.length < 30) return str;

        const pagefindings = findingsByPage.get(pageNum) ?? [];

        // Word-overlap matching: highlight text items that share 3+ meaningful
        // words (≥5 chars) with the finding's description. This works even when
        // normalized_text is the whole document (LLM extraction artifact).
        const strWords = new Set(trimmed.toLowerCase().match(/\b\w{5,}\b/g) ?? []);
        if (strWords.size === 0) return str;

        const match = pagefindings.find((of_) => {
          if (!of_.finding.evidence.some((e) => e.page === pageNum)) return false;

          // 1. Direct substring match against short clause_text (precise, when < 600 chars)
          const shortEvidence = of_.finding.evidence.find(
            (e) => e.page === pageNum && e.normalized_text.length < 600
          );
          if (shortEvidence && shortEvidence.normalized_text.includes(trimmed)) return true;

          // 2. Word-overlap: pool words from description + short clause_text combined
          const textPool = of_.finding.description
            + (shortEvidence ? " " + shortEvidence.normalized_text : "");
          const poolWords = textPool.toLowerCase().match(/\b\w{5,}\b/g) ?? [];
          const overlap = poolWords.filter((w) => strWords.has(w));
          // Require 3+ overlapping words with a discriminative word (>8 chars).
          // Exception: if any overlapping word is very long (>12 chars), 2 matches suffice
          // — e.g. "confidentiality" alone is specific enough to avoid false positives.
          const hasVeryLong = overlap.some((w) => w.length > 12);
          const minOverlap = hasVeryLong ? 2 : 3;
          return overlap.length >= minOverlap && overlap.some((w) => w.length > 8);
        });
        if (!match) return str;

        const cls = SEVERITY_CLASSES[match.finding.severity] ?? "cr-low";
        const rawTip = `#${match.index} · ${match.finding.description.slice(0, 120)}${match.finding.description.length > 120 ? "…" : ""}`;
        const tip = rawTip.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        return `<mark class="cr-mark ${cls}" data-num="${match.index}" data-tip="${tip}">${str}</mark>`;
      },
    [findingsByPage]
  );

  const pagefindings = findingsByPage.get(page) ?? [];

  return (
    <div className="w-full">
      {/* Injected CSS for highlights and tooltip */}
      <style>{`
        .cr-mark {
          border-radius: 2px;
          cursor: pointer;
          position: relative;
          transition: opacity 0.15s;
          color: transparent; /* keep text layer invisible; only show background */
        }
        .cr-mark.cr-high   { background: rgba(239,68,68,0.35);  }
        .cr-mark.cr-medium { background: rgba(234,179,8,0.35);  }
        .cr-mark.cr-low    { background: rgba(34,197,94,0.35);  }
        .cr-mark:hover { opacity: 0.75; }
        .cr-mark::after {
          content: attr(data-tip);
          position: absolute;
          bottom: calc(100% + 6px);
          left: 50%;
          transform: translateX(-50%);
          background: var(--color-surface, #1a1a1a);
          border: 1px solid var(--color-border, #333);
          color: var(--color-text-primary, #fff);
          font-size: 11px;
          line-height: 1.4;
          padding: 6px 10px;
          border-radius: 6px;
          white-space: pre-wrap;
          max-width: 260px;
          word-break: break-word;
          pointer-events: none;
          opacity: 0;
          transition: opacity 0.15s;
          z-index: 50;
        }
        .cr-mark:hover::after { opacity: 1; }
        /* Allow tooltips to escape the pdf.js text layer container */
        .react-pdf__Page__textContent { overflow: visible !important; }
        .react-pdf__Page { overflow: visible !important; }
      `}</style>

      <div className="flex gap-8 items-start">
        {/* ── PDF viewer column ── */}
        <div className="flex-1 min-w-0">
          {loadError ? (
            <div className="flex items-center gap-2 py-12 text-sm text-risk-high">
              <AlertCircle className="h-4 w-4 shrink-0" />
              Could not load the PDF file. It may no longer be on disk.
            </div>
          ) : (
            <Document
              file={fileUrl}
              onLoadSuccess={onDocumentLoadSuccess}
              onLoadError={onDocumentLoadError}
              loading={
                <div className="flex items-center justify-center py-24">
                  <Loader2 className="h-5 w-5 animate-spin text-text-secondary/40" />
                </div>
              }
            >
              {numPages && (
                <div className="rounded-xl overflow-hidden border border-border shadow-sm">
                  <Page
                    pageNumber={page}
                    width={Math.min(800, window.innerWidth - 400)}
                    renderAnnotationLayer={false}
                    customTextRenderer={makeTextRenderer(page)}
                  />
                </div>
              )}
            </Document>
          )}

          {/* Pagination */}
          {numPages && numPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="flex items-center gap-1 text-sm font-medium text-text-secondary hover:text-text-primary disabled:opacity-30 transition-colors cursor-pointer disabled:cursor-not-allowed"
              >
                <ChevronLeft className="h-4 w-4" />
                Previous
              </button>
              <span className="text-xs text-text-secondary/60">
                Page {page} of {numPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(numPages, p + 1))}
                disabled={page === numPages}
                className="flex items-center gap-1 text-sm font-medium text-text-secondary hover:text-text-primary disabled:opacity-30 transition-colors cursor-pointer disabled:cursor-not-allowed"
              >
                Next
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>

        {/* ── Findings sidebar ── */}
        <div className="w-72 shrink-0 space-y-2 sticky top-24">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary/50 mb-3">
            Findings · {ordered.length} total
          </p>

          {ordered.map(({ finding, index, firstPage }) => {
            const isOnPage = (findingsByPage.get(page) ?? []).some((f) => f.index === index);
            const chipCls = SEVERITY_CHIP[finding.severity] ?? SEVERITY_CHIP.low;
            return (
              <button
                key={finding.finding_id}
                onClick={() => setPage(firstPage)}
                className={cn(
                  "w-full text-left rounded-lg border px-3 py-3 transition-all cursor-pointer",
                  isOnPage
                    ? "border-accent/40 bg-accent/5"
                    : "border-border hover:border-border/80 hover:bg-drop-zone/20"
                )}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded border", chipCls)}>
                    #{index}
                  </span>
                  <span className={cn("text-[10px] font-semibold uppercase", chipCls.split(" ")[1])}>
                    {finding.severity === "critical" ? "CRITICAL" : finding.severity.toUpperCase()}
                  </span>
                  <span className="ml-auto text-[10px] text-text-secondary/40">p.{firstPage}</span>
                </div>
                <p className="text-xs font-medium text-text-primary leading-snug line-clamp-2 mb-1">
                  {finding.description}
                </p>
                {finding.recommendation_detail && (
                  <p className="text-[10px] text-text-secondary/70 leading-snug line-clamp-2 italic">
                    → {finding.recommendation_detail}
                  </p>
                )}
              </button>
            );
          })}

          {/* Page jump chips */}
          {pagefindings.length > 0 && (
            <div className="pt-3 border-t border-border/60">
              <p className="text-[10px] text-text-secondary/50 mb-2">On this page:</p>
              <div className="flex flex-wrap gap-1.5">
                {pagefindings.map(({ index, finding }) => {
                  const chipCls = SEVERITY_CHIP[finding.severity] ?? SEVERITY_CHIP.low;
                  return (
                    <span
                      key={index}
                      className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded border", chipCls)}
                    >
                      #{index}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
