import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  Download,
  Edit3,
  FileText,
  GitCompare,
  MessageSquare,
  Trash2,
  X,
} from "lucide-react";
import {
  acceptFinding,
  createAnnotation,
  deleteAnnotation,
  dismissFinding,
  getDocxExportUrl,
  getEditedPdfUrl,
  getRunFileUrl,
  listAnnotations,
} from "@/lib/api";
import type {
  DocumentAnnotation,
  Finding,
} from "@/types";
import { cn } from "@/lib/utils";
import DocumentEditor, { type CommentDraft } from "@/components/DocumentEditor";

const SEV_COLOR: Record<string, string> = {
  critical: "#dc2626",
  high: "#dc2626",
  medium: "#d97706",
  low: "#16a34a",
};

const SEV_BG: Record<string, string> = {
  critical: "rgba(220,38,38,0.07)",
  high: "rgba(220,38,38,0.07)",
  medium: "rgba(217,119,6,0.07)",
  low: "rgba(22,163,74,0.07)",
};

const SEV_BORDER: Record<string, string> = {
  critical: "rgba(220,38,38,0.25)",
  high: "rgba(220,38,38,0.25)",
  medium: "rgba(217,119,6,0.25)",
  low: "rgba(22,163,74,0.25)",
};

const COMMENT_COLOR = "#2563eb";
const COMMENT_BG = "rgba(37,99,235,0.06)";
const COMMENT_BORDER = "rgba(37,99,235,0.22)";

type ViewMode = "comment" | "edit";

interface OrderedFinding {
  finding: Finding;
  index: number;
}

interface ContractReaderProps {
  runId: string;
  findings: Finding[];
  jumpToIndex?: number | null;
  onJumpHandled?: () => void;
}

function orderFindings(findings: Finding[]): OrderedFinding[] {
  return findings.map((f, i) => ({ finding: f, index: i + 1 }));
}

function firstFindingQuote(finding: Finding): string {
  return (
    finding.contract_evidence?.[0]?.text ||
    finding.evidence?.[0]?.normalized_text ||
    "No direct quote available."
  );
}

type DiffChunk = { type: "keep" | "del" | "add"; text: string };

function computeWordDiff(original: string, replacement: string): DiffChunk[] {
  const origWords = original.trim().split(/\s+/).filter(Boolean);
  const replWords = replacement.trim().split(/\s+/).filter(Boolean);
  const m = origWords.length;
  const n = replWords.length;
  if (m > 400 || n > 400) {
    return [
      { type: "del", text: original.trim() },
      { type: "add", text: replacement.trim() },
    ];
  }
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = origWords[i - 1].toLowerCase() === replWords[j - 1].toLowerCase()
        ? dp[i - 1][j - 1] + 1
        : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }
  const ops: Array<{ type: "keep" | "del" | "add"; word: string }> = [];
  let i = m, j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && origWords[i - 1].toLowerCase() === replWords[j - 1].toLowerCase()) {
      ops.unshift({ type: "keep", word: replWords[j - 1] }); i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      ops.unshift({ type: "add", word: replWords[j - 1] }); j--;
    } else {
      ops.unshift({ type: "del", word: origWords[i - 1] }); i--;
    }
  }
  const chunks: DiffChunk[] = [];
  for (const op of ops) {
    const last = chunks[chunks.length - 1];
    if (last && last.type === op.type) last.text += " " + op.word;
    else chunks.push({ type: op.type, text: op.word });
  }
  return chunks;
}

function DiffView({ chunks, fontSize = 11 }: { chunks: DiffChunk[]; fontSize?: number }) {
  return (
    <span style={{ fontSize, lineHeight: 1.5, fontFamily: "Georgia, 'Times New Roman', serif", wordBreak: "break-word" }}>
      {chunks.map((chunk, i) => {
        if (chunk.type === "del")
          return <span key={i} style={{ textDecoration: "line-through", color: "#dc2626", opacity: 0.85 }}>{chunk.text} </span>;
        if (chunk.type === "add")
          return <span key={i} style={{ color: "#15803d", background: "rgba(21,128,61,0.08)", borderRadius: 2 }}>{chunk.text} </span>;
        return <span key={i} style={{ color: "#374151" }}>{chunk.text} </span>;
      })}
    </span>
  );
}

export default function ContractReader({ runId, findings, jumpToIndex, onJumpHandled }: ContractReaderProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("comment");
  const [showRedlines, setShowRedlines] = useState(true);
  const [annotations, setAnnotations] = useState<DocumentAnnotation[]>([]);
  const [hiddenFindingIds, setHiddenFindingIds] = useState<Set<string>>(new Set());
  const [expandedFindingIds, setExpandedFindingIds] = useState<Set<string>>(new Set());
  const [actionError, setActionError] = useState("");
  const [selectionDraft, setSelectionDraft] = useState<CommentDraft | null>(null);
  const [activeAnnotationId, setActiveAnnotationId] = useState<string | null>(null);
  const [hoveredAnnotationId, setHoveredAnnotationId] = useState<string | null>(null);
  const [draftRefreshKey, setDraftRefreshKey] = useState(0);

  const fileUrl = getRunFileUrl(runId);
  const [exportOpen, setExportOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setExportOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const ordered = useMemo(
    () => orderFindings(findings.filter((f) => !hiddenFindingIds.has(f.finding_id))),
    [findings, hiddenFindingIds],
  );

  // Load annotations and poll
  useEffect(() => {
    if (!runId) return;
    listAnnotations(runId).then(setAnnotations).catch(() => {});
    const id = setInterval(() => {
      listAnnotations(runId).then(setAnnotations).catch(() => {});
    }, 8000);
    return () => clearInterval(id);
  }, [runId]);

  // Jump-to-finding: scroll the browser to that finding's card in the right sidebar
  useEffect(() => {
    if (jumpToIndex == null) return;
    onJumpHandled?.();
  }, [jumpToIndex, onJumpHandled]);

  async function handleAccept(findingId: string, replacementText: string) {
    setActionError("");
    try {
      await acceptFinding(runId, findingId, replacementText);
      setHiddenFindingIds((prev) => new Set(prev).add(findingId));
      setDraftRefreshKey((k) => k + 1);
    } catch (err) {
      setActionError((err as Error).message || "Failed to accept suggestion.");
    }
  }

  async function handleDismiss(findingId: string) {
    setActionError("");
    try {
      await dismissFinding(runId, findingId);
      setHiddenFindingIds((prev) => new Set(prev).add(findingId));
    } catch (err) {
      setActionError((err as Error).message || "Failed to dismiss suggestion.");
    }
  }

  async function saveSelectionComment() {
    if (!selectionDraft) return;
    setActionError("");
    try {
      const annotation = await createAnnotation(runId, {
        clause_uid: selectionDraft.clauseUid,
        annotation_type: "comment",
        body: commentBody.trim(),
        selected_text: selectionDraft.selectedText,
        span_start: selectionDraft.fromPos,
        span_end: selectionDraft.toPos,
        page_number: selectionDraft.pageNumber,
      });
      setAnnotations((prev) => [...prev, annotation]);
      setSelectionDraft(null);
      setCommentBody("");
      setDraftRefreshKey((k) => k + 1);
    } catch (err) {
      setActionError((err as Error).message || "Failed to save comment.");
    }
  }

  async function removeAnnotation(annotationId: string) {
    await deleteAnnotation(runId, annotationId);
    setAnnotations((prev) => prev.filter((a) => a.id !== annotationId));
    setDraftRefreshKey((k) => k + 1);
  }

  const [commentBody, setCommentBody] = useState("");
  // Clear body when a new selection draft is set
  useEffect(() => { if (selectionDraft) setCommentBody(""); }, [selectionDraft]);

  return (
    <div className="w-full">
      {/* Toolbar */}
      <div className="mb-5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 text-xs text-text-secondary/60">
          <span>{ordered.length} AI finding{ordered.length !== 1 ? "s" : ""}</span>
          <span style={{ color: COMMENT_COLOR }}>
            {annotations.length} comment{annotations.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex h-9 overflow-hidden rounded-lg border border-border bg-surface text-sm font-semibold shadow-sm">
            <button
              onClick={() => setViewMode("comment")}
              className={cn(
                "flex min-w-[112px] items-center justify-center gap-2 px-3 transition-all",
                viewMode === "comment"
                  ? "bg-accent/12 text-accent"
                  : "text-text-secondary hover:bg-drop-zone/20 hover:text-text-primary",
              )}
            >
              <MessageSquare className="h-4 w-4 shrink-0" /> Comment
            </button>
            <button
              onClick={() => setViewMode("edit")}
              className={cn(
                "flex min-w-[92px] items-center justify-center gap-2 border-l border-border px-3 transition-all",
                viewMode === "edit"
                  ? "bg-accent/12 text-accent"
                  : "text-text-secondary hover:bg-drop-zone/20 hover:text-text-primary",
              )}
            >
              <Edit3 className="h-4 w-4 shrink-0" /> Edit
            </button>
          </div>

          <button
            onClick={() => setShowRedlines((v) => !v)}
            className={cn(
              "flex h-9 min-w-[118px] items-center justify-center gap-2 rounded-lg border px-3 text-sm font-semibold transition-all",
              showRedlines
                ? "border-risk-high/35 bg-risk-high/8 text-risk-high shadow-sm"
                : "border-border bg-surface text-text-secondary shadow-sm hover:border-text-secondary/30 hover:bg-drop-zone/20 hover:text-text-primary",
            )}
          >
            <GitCompare className="h-4 w-4 shrink-0" /> Redlines
          </button>

          {/* Export dropdown */}
          <div ref={exportRef} className="relative">
            <button
              onClick={() => setExportOpen((v) => !v)}
              className={cn(
                "flex h-9 min-w-[118px] items-center justify-center gap-2 rounded-lg border px-3 text-sm font-semibold transition-all",
                exportOpen
                  ? "border-accent/45 bg-accent/10 text-accent shadow-sm"
                  : "border-border bg-surface text-text-secondary shadow-sm hover:border-text-secondary/30 hover:bg-drop-zone/20 hover:text-text-primary",
              )}
            >
              <Download className="h-4 w-4 shrink-0" />
              Export
              <ChevronDown
                className={cn("h-3.5 w-3.5 shrink-0 transition-transform duration-150", exportOpen && "rotate-180")}
              />
            </button>

            {exportOpen && (
              <div className="absolute right-0 top-full z-50 mt-1.5 w-52 overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
                {/* Section: Original */}
                <div className="border-b border-border px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary/50">
                    Original Contract
                  </p>
                </div>
                <a
                  href={fileUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => setExportOpen(false)}
                  className="flex items-center gap-2.5 px-3 py-2.5 text-xs text-text-secondary transition-colors hover:bg-accent/5 hover:text-text-primary"
                >
                  <FileText className="h-3.5 w-3.5 shrink-0 text-red-500" />
                  <div>
                    <div className="font-medium text-text-primary">PDF</div>
                    <div className="text-[10px] text-text-secondary/60">As uploaded</div>
                  </div>
                </a>
                <a
                  href={getDocxExportUrl(runId, true)}
                  download
                  onClick={() => setExportOpen(false)}
                  className="flex items-center gap-2.5 border-b border-border px-3 py-2.5 text-xs text-text-secondary transition-colors hover:bg-accent/5 hover:text-text-primary"
                >
                  <FileText className="h-3.5 w-3.5 shrink-0 text-blue-500" />
                  <div>
                    <div className="font-medium text-text-primary">DOCX</div>
                    <div className="text-[10px] text-text-secondary/60">Original formatting</div>
                  </div>
                </a>

                {/* Section: Modified */}
                <div className="px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary/50">
                    Modified Contract
                  </p>
                </div>
                <a
                  href={getEditedPdfUrl(runId)}
                  download
                  onClick={() => setExportOpen(false)}
                  className="flex items-center gap-2.5 px-3 py-2.5 text-xs text-text-secondary transition-colors hover:bg-accent/5 hover:text-text-primary"
                >
                  <FileText className="h-3.5 w-3.5 shrink-0 text-red-500" />
                  <div>
                    <div className="font-medium text-text-primary">PDF</div>
                    <div className="text-[10px] text-text-secondary/60">With accepted edits</div>
                  </div>
                </a>
                <a
                  href={getDocxExportUrl(runId)}
                  download
                  onClick={() => setExportOpen(false)}
                  className="flex items-center gap-2.5 px-3 py-2.5 text-xs text-text-secondary transition-colors hover:bg-accent/5 hover:text-text-primary"
                >
                  <FileText className="h-3.5 w-3.5 shrink-0 text-blue-500" />
                  <div>
                    <div className="font-medium text-text-primary">DOCX</div>
                    <div className="text-[10px] text-text-secondary/60">With accepted edits</div>
                  </div>
                </a>
              </div>
            )}
          </div>
        </div>
      </div>

      {actionError && (
        <div className="mb-4 rounded-md border border-risk-high/30 bg-risk-high/5 px-3 py-2 text-xs text-risk-high">
          {actionError}
        </div>
      )}

      <div className="grid grid-cols-[220px_minmax(0,1fr)_280px] gap-x-6">
        {/* Left: Comments sidebar */}
        <aside>
          <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-text-secondary/40">
            Comments · {annotations.length}
          </p>
          {selectionDraft && (
            <div
              className="mb-3 rounded-lg p-3"
              style={{ background: COMMENT_BG, border: `1px solid ${COMMENT_BORDER}` }}
            >
              <p
                className="mb-1 text-[10px] font-semibold uppercase tracking-widest"
                style={{ color: COMMENT_COLOR }}
              >
                New comment
              </p>
              <p className="mb-2 line-clamp-2 text-[11px] italic text-text-secondary/70">
                &ldquo;{selectionDraft.selectedText}&rdquo;
              </p>
              <textarea
                value={commentBody}
                onChange={(e) => setCommentBody(e.target.value)}
                rows={2}
                className="mb-2 w-full resize-none rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-text-primary outline-none focus:border-accent/60"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) saveSelectionComment();
                }}
                placeholder="Add a comment... (Ctrl+Enter to save)"
              />
              <div className="flex justify-end gap-1.5">
                <button
                  onClick={() => setSelectionDraft(null)}
                  className="rounded border border-border px-2 py-1 text-[10px] text-text-secondary hover:bg-drop-zone"
                >
                  Cancel
                </button>
                <button
                  onClick={saveSelectionComment}
                  disabled={!commentBody.trim()}
                  className="rounded px-2 py-1 text-[10px] font-semibold text-white disabled:opacity-50"
                  style={{ background: COMMENT_COLOR }}
                >
                  Add
                </button>
              </div>
            </div>
          )}
          <div className="space-y-2">
            {annotations.map((annotation, index) => (
              <AnnotationCard
                key={annotation.id}
                annotation={annotation}
                num={index + 1}
                isActive={activeAnnotationId === annotation.id}
                isHoveredFromDoc={hoveredAnnotationId === annotation.id}
                onActivate={() => setActiveAnnotationId(annotation.id)}
                onDelete={() => removeAnnotation(annotation.id)}
              />
            ))}
          </div>
        </aside>

        {/* Center: Document editor */}
        <main>
          <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-text-secondary/40">
            {viewMode === "comment"
              ? "Document · select text to comment"
              : "Document · click text to edit in place"}
          </p>
          <DocumentEditor
            runId={runId}
            findings={findings}
            annotations={annotations}
            viewMode={viewMode}
            showRedlines={showRedlines}
            activeAnnotationId={activeAnnotationId}
            hoveredAnnotationId={hoveredAnnotationId}
            draftRefreshKey={draftRefreshKey}
            onAnnotationActivate={(id) => setActiveAnnotationId(id)}
            onAnnotationHover={(id) => setHoveredAnnotationId(id)}
            onCommentDraft={(draft) => setSelectionDraft(draft)}
            onFindingAccept={handleAccept}
            onFindingDismiss={handleDismiss}
          />
        </main>

        {/* Right: AI Findings sidebar */}
        <aside>
          <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-text-secondary/40">
            AI Findings · {ordered.length}
          </p>
          <div className="space-y-2">
            {ordered.map(({ finding, index }) => (
              <SuggestionCard
                key={finding.finding_id}
                finding={finding}
                index={index}
                expanded={expandedFindingIds.has(finding.finding_id)}
                onToggle={() =>
                  setExpandedFindingIds((prev) => {
                    const next = new Set(prev);
                    if (next.has(finding.finding_id)) next.delete(finding.finding_id);
                    else next.add(finding.finding_id);
                    return next;
                  })
                }
                onAccept={() => {
                  const replacement = finding.recommended_change?.trim();
                  if (!replacement) {
                    setActionError(
                      "This finding has no concrete replacement text. Use Edit mode to rewrite manually.",
                    );
                    return;
                  }
                  handleAccept(finding.finding_id, replacement);
                }}
                onDismiss={() => handleDismiss(finding.finding_id)}
              />
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}

function SuggestionCard({
  finding,
  index,
  expanded,
  onToggle,
  onAccept,
  onDismiss,
}: {
  finding: Finding;
  index: number;
  expanded: boolean;
  onToggle: () => void;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  const [showFullDiff, setShowFullDiff] = useState(false);
  const color = SEV_COLOR[finding.severity] ?? SEV_COLOR.low;
  const bg = SEV_BG[finding.severity] ?? SEV_BG.low;
  const border = SEV_BORDER[finding.severity] ?? SEV_BORDER.low;
  const replacement = finding.recommended_change?.trim();
  const guidance = !replacement
    ? finding.recommendation_detail?.trim() || finding.recommendation?.trim() || null
    : null;

  const diffChunks = useMemo(() => {
    if (!replacement) return null;
    const evidence = finding.contract_evidence?.[0]?.text || finding.evidence?.[0]?.normalized_text || "";
    if (!evidence) return null;
    return computeWordDiff(evidence, replacement);
  }, [replacement, finding]);

  const hasMeaningfulDiff = diffChunks && diffChunks.some((c) => c.type !== "keep");

  return (
    <div className="rounded-lg p-3" style={{ background: bg, border: `1px solid ${border}` }}>
      <button onClick={onToggle} className="w-full text-left">
        <div className="mb-1.5 flex items-center gap-1.5">
          <span
            className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white"
            style={{ background: color }}
          >
            {index}
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color }}>
            {finding.severity}
          </span>
        </div>
        <p className="line-clamp-3 text-xs leading-snug text-text-primary">{finding.description}</p>
      </button>

      {expanded && (
        <div className="mt-3 space-y-2 border-t border-border/50 pt-3">
          <blockquote
            className="border-l-2 pl-2 text-[11px] italic leading-relaxed text-text-secondary"
            style={{ borderColor: color }}
          >
            {firstFindingQuote(finding)}
          </blockquote>
          {replacement && hasMeaningfulDiff ? (
            <div className="rounded border p-2" style={{ borderColor: `${color}25`, background: `${color}0a` }}>
              <div className="mb-1.5 flex items-center justify-between">
                <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color }}>
                  Proposed change
                </p>
                {diffChunks && diffChunks.length > 20 && (
                  <button
                    onClick={() => setShowFullDiff((v) => !v)}
                    className="text-[9px] font-medium text-text-secondary/60 hover:text-text-secondary"
                  >
                    {showFullDiff ? "Show less" : "Show all"}
                  </button>
                )}
              </div>
              <div className="rounded bg-white/60 px-2 py-1.5" style={{ borderLeft: "2px solid #2563eb" }}>
                {showFullDiff || (diffChunks?.length ?? 0) <= 20 ? (
                  <DiffView chunks={diffChunks!} fontSize={10.5} />
                ) : (
                  <>
                    <DiffView chunks={diffChunks!.slice(0, 20)} fontSize={10.5} />
                    <button
                      onClick={() => setShowFullDiff(true)}
                      className="mt-1 text-[9px] text-text-secondary/50 hover:text-text-secondary"
                    >
                      ... {diffChunks!.length - 20} more words
                    </button>
                  </>
                )}
              </div>
            </div>
          ) : replacement ? (
            <div className="rounded border p-2" style={{ borderColor: `${color}25`, background: `${color}0a` }}>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest" style={{ color }}>
                Replace with
              </p>
              <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-text-primary">{replacement}</p>
            </div>
          ) : guidance ? (
            <div className="rounded border p-2" style={{ borderColor: `${color}20`, background: `${color}08` }}>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest" style={{ color }}>
                Suggested action
              </p>
              <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-text-primary">{guidance}</p>
            </div>
          ) : (
            <p className="text-[11px] italic text-text-secondary/60">
              No specific guidance. Use Edit mode to rewrite this clause manually.
            </p>
          )}
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={onAccept}
              disabled={!replacement}
              className="flex items-center gap-1 rounded border border-risk-low/30 bg-risk-low/5 px-2 py-1 text-[10px] font-semibold text-risk-low transition-colors hover:bg-risk-low/15 disabled:opacity-40"
              title={replacement ? "Apply replacement text" : "No replacement text — use Edit mode"}
            >
              <Check className="h-2.5 w-2.5" /> Accept
            </button>
            <button
              onClick={onDismiss}
              className="flex items-center gap-1 rounded border border-border px-2 py-1 text-[10px] font-semibold text-text-secondary/70 transition-colors hover:border-text-secondary/40"
            >
              <X className="h-2.5 w-2.5" /> Deny
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function AnnotationCard({
  annotation,
  num,
  isActive,
  isHoveredFromDoc,
  onActivate,
  onDelete,
}: {
  annotation: DocumentAnnotation;
  num?: number;
  isActive?: boolean;
  isHoveredFromDoc?: boolean;
  onActivate?: () => void;
  onDelete: () => void;
}) {
  const highlighted = isActive || isHoveredFromDoc;
  return (
    <div
      className="cursor-pointer rounded-lg p-3 transition-all"
      style={{
        background: highlighted ? "rgba(37,99,235,0.12)" : COMMENT_BG,
        border: `1px solid ${highlighted ? COMMENT_COLOR : COMMENT_BORDER}`,
        boxShadow: isActive ? "0 0 0 2px rgba(37,99,235,0.2)" : undefined,
      }}
      onClick={onActivate}
    >
      <div className="mb-1.5 flex items-center gap-2">
        {num != null && (
          <span
            className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white transition-transform"
            style={{
              background: COMMENT_COLOR,
              transform: highlighted ? "scale(1.2)" : "scale(1)",
            }}
          >
            {num}
          </span>
        )}
        <span
          className="text-[10px] font-semibold uppercase tracking-widest"
          style={{ color: COMMENT_COLOR }}
        >
          {annotation.author_name ?? "Comment"}
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="ml-auto text-text-secondary/50 transition-colors hover:text-risk-high"
          title="Delete comment"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
      {annotation.selected_text && (
        <p className="mb-2 line-clamp-2 text-[11px] italic text-text-secondary/70">
          &ldquo;{annotation.selected_text}&rdquo;
        </p>
      )}
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-primary">{annotation.body}</p>
    </div>
  );
}
