import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { Loader2, AlertCircle, MessageSquare, X, Pencil, Trash2, Check, FileEdit } from "lucide-react";
import { createContractComment, deleteContractComment, updateContractComment, getRunFileUrl, listContractComments } from "@/lib/api";
import type { Comment, CommentAnchor, DocumentComment, Finding, FindingAnchor } from "@/types";
import { cn } from "@/lib/utils";
import ContractEditor from "@/components/ContractEditor";

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
  firstPage: number | null;   // earliest page this finding appears on
  anchors: FindingAnchor[];
}

function evidenceFor(finding: Finding) {
  return Array.isArray(finding.evidence) ? finding.evidence : [];
}

function normalizeForMatch(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function usableEvidenceText(value: string): string {
  const normalized = normalizeForMatch(value);
  // Very long spans are usually whole-page/whole-document extraction artifacts.
  // Using them for highlighting paints unrelated text, so keep them for page
  // placement only and require a focused quote for marks.
  return normalized.length <= 900 ? normalized : "";
}

function wordsForMatch(value: string): string[] {
  return normalizeForMatch(value).match(/\b[\w'-]{4,}\b/g) ?? [];
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function uniqueAnchors(anchors: FindingAnchor[]): FindingAnchor[] {
  const seen = new Set<string>();
  return anchors.filter((anchor) => {
    const key = `${anchor.pageNumber}:${normalizeForMatch(anchor.selectedText)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function anchorsFor(finding: Finding): FindingAnchor[] {
  const anchors: FindingAnchor[] = [];

  for (const evidence of finding.contract_evidence ?? []) {
    const selectedText = usableEvidenceText(evidence.text ?? "");
    const pageNumber = Number(evidence.page);
    if (!selectedText || !Number.isFinite(pageNumber) || pageNumber < 1) continue;
    anchors.push({
      findingId: finding.finding_id,
      pageNumber,
      selectedText,
      source: "contract_evidence",
      confidence: evidence.confidence,
    });
  }

  for (const evidence of evidenceFor(finding)) {
    const selectedText = usableEvidenceText(evidence.normalized_text ?? "");
    const pageNumber = Number(evidence.page);
    if (!selectedText || !Number.isFinite(pageNumber) || pageNumber < 1) continue;
    anchors.push({
      findingId: finding.finding_id,
      pageNumber,
      selectedText,
      bbox: evidence.bbox,
      source: "legacy_evidence",
      confidence: evidence.extraction_confidence,
    });
  }

  return uniqueAnchors(anchors);
}

function anchorMatchesText(anchor: FindingAnchor | CommentAnchor, normalizedItem: string): boolean {
  const quote = usableEvidenceText(anchor.selectedText);
  if (!quote) return false;
  if (quote.includes(normalizedItem) && normalizedItem.length >= 10) return true;
  if (normalizedItem.includes(quote) && quote.length >= 18) return true;

  const itemWords = wordsForMatch(normalizedItem);
  const quoteWords = new Set(wordsForMatch(quote));
  if (itemWords.length === 0 || quoteWords.size === 0) return false;

  const overlap = itemWords.filter((w) => quoteWords.has(w));
  const coverage = overlap.length / itemWords.length;
  return itemWords.length >= 3 && coverage >= 0.72 && overlap.some((w) => w.length >= 7);
}

function orderFindings(findings: Finding[]): OrderedFinding[] {
  return findings
    .map((f) => {
      const anchors = anchorsFor(f);
      return {
        finding: f,
        anchors,
        firstPage: anchors.length > 0 ? Math.min(...anchors.map((a) => a.pageNumber)) : null,
      };
    })
    .sort((a, b) => (a.firstPage ?? 999) - (b.firstPage ?? 999))
    .map((item, i) => ({ ...item, index: i + 1 }));
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface ContractReaderProps {
  runId: string;
  findings: Finding[];
  workspaceId?: string | null;
  contractId?: string | number | null;
  filename?: string;
  currentUserName?: string;
}

interface SelectionTarget {
  anchor: CommentAnchor;
  top: number;
  left: number;
}

function mapApiComment(comment: Comment, runId: string): DocumentComment | null {
  if (!comment.anchor || !comment.page_number || !comment.selected_text) return null;
  return {
    id: comment.id,
    runId,
    workspaceId: comment.workspace_id ?? comment.anchor.workspaceId,
    contractId: comment.contract_id ?? comment.anchor.contractId,
    pageNumber: comment.page_number,
    selectedText: comment.selected_text,
    anchor: comment.anchor,
    userId: comment.author_id,
    username: comment.author_name,
    note: comment.body,
    createdAt: comment.created_at,
    updatedAt: comment.updated_at,
  };
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function ContractReader({ runId, findings, workspaceId = null, contractId = null, filename = "contract.pdf", currentUserName }: ContractReaderProps) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [activePage, setActivePage] = useState(1);
  const [editorMode, setEditorMode] = useState(false);   // tracks which page is in view (for sidebar chips)
  const [loadError, setLoadError] = useState(false);
  const [viewerWidth, setViewerWidth] = useState(800);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [comments, setComments] = useState<DocumentComment[]>([]);
  const [selectedCommentId, setSelectedCommentId] = useState<string | null>(null);
  const [selectionTarget, setSelectionTarget] = useState<SelectionTarget | null>(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);
  const [postingComment, setPostingComment] = useState(false);
  const [editingCommentId, setEditingCommentId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const viewerRef = useRef<HTMLDivElement | null>(null);
  // per-page shell refs so we can locate which page a selection is on
  const pageShellRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  const ordered = useMemo(() => orderFindings(findings), [findings]);
  const fileUrl = getRunFileUrl(runId);

  // measure PDF column width
  useEffect(() => {
    const el = viewerRef.current;
    if (!el) return;
    const update = () => setViewerWidth(Math.max(320, Math.min(900, Math.floor(el.getBoundingClientRect().width))));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // load comments
  useEffect(() => {
    let active = true;
    setCommentError(null);
    listContractComments(runId)
      .then((items) => {
        if (!active) return;
        setComments(items.map((item) => mapApiComment(item, runId)).filter(Boolean) as DocumentComment[]);
      })
      .catch(() => { if (active) setCommentError("Comments could not be loaded."); });
    return () => { active = false; };
  }, [runId]);

  // track which page is currently visible via IntersectionObserver
  useEffect(() => {
    if (!viewerRef.current) return;
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible.length > 0) {
          const pageNum = Number((visible[0].target as HTMLElement).dataset.pageNumber);
          if (pageNum > 0) setActivePage(pageNum);
        }
      },
      { threshold: 0.3 }
    );
    // observe all page shells once they mount
    const shellEls = viewerRef.current.querySelectorAll<HTMLElement>("[data-page-number]");
    shellEls.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [numPages]); // re-run when pages load

  // Build a lookup: page → list of OrderedFinding on that page
  const findingsByPage = useMemo(() => {
    const map = new Map<number, OrderedFinding[]>();
    for (const of_ of ordered) {
      const pages = of_.anchors
        .map((anchor) => anchor.pageNumber)
        .filter((p) => Number.isFinite(p) && p > 0);
      const uniquePages = [...new Set(pages)];
      for (const p of uniquePages) {
        if (!map.has(p)) map.set(p, []);
        map.get(p)!.push(of_);
      }
    }
    return map;
  }, [ordered]);

  const commentsByPage = useMemo(() => {
    const map = new Map<number, DocumentComment[]>();
    for (const comment of comments) {
      if (!map.has(comment.pageNumber)) map.set(comment.pageNumber, []);
      map.get(comment.pageNumber)!.push(comment);
    }
    return map;
  }, [comments]);

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setLoadError(false);
  }, []);

  const onDocumentLoadError = useCallback(() => setLoadError(true), []);

  const scrollIntoViewIfNeeded = useCallback((el: Element) => {
    const rect = el.getBoundingClientRect();
    const fullyVisible = rect.top >= 80 && rect.bottom <= window.innerHeight - 40;
    if (!fullyVisible) el.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
  }, []);

  const scrollToSelector = useCallback((selector: string, fallbackPageNum?: number) => {
    window.setTimeout(() => {
      const el = viewerRef.current?.querySelector(selector);
      if (el) {
        scrollIntoViewIfNeeded(el);
      } else if (fallbackPageNum) {
        // mark not in DOM (no text anchor) — scroll to the page shell instead
        const shell = pageShellRefs.current.get(fallbackPageNum);
        if (shell) scrollIntoViewIfNeeded(shell);
      }
    }, 80);
  }, [scrollIntoViewIfNeeded]);

  const goToFinding = useCallback((item: OrderedFinding) => {
    setSelectedCommentId(null);
    setSelectedFindingId(item.finding.finding_id);
    scrollToSelector(
      `[data-finding-id="${CSS.escape(item.finding.finding_id)}"]`,
      item.firstPage ?? undefined
    );
  }, [scrollToSelector]);

  const goToComment = useCallback((comment: DocumentComment) => {
    setSelectedFindingId(null);
    setSelectedCommentId(comment.id);
    scrollToSelector(
      `[data-comment-id="${CSS.escape(comment.id)}"]`,
      comment.pageNumber
    );
  }, [scrollToSelector]);

  const handleViewerClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const findingMark = target.closest<HTMLElement>("[data-finding-id]");
    if (findingMark?.dataset.findingId) {
      setSelectedCommentId(null);
      setSelectedFindingId(findingMark.dataset.findingId);
      return;
    }
    const commentMark = target.closest<HTMLElement>("[data-comment-id]");
    if (commentMark?.dataset.commentId) {
      setSelectedFindingId(null);
      setSelectedCommentId(commentMark.dataset.commentId);
    }
  }, []);

  const captureSelection = useCallback(() => {
    const selection = window.getSelection();
    const text = selection?.toString().replace(/\s+/g, " ").trim() ?? "";
    if (!selection || selection.rangeCount === 0 || text.length < 2) {
      setSelectionTarget(null);
      return;
    }

    const range = selection.getRangeAt(0);

    // detect which page this selection is on
    let detectedPageNum: number | null = null;
    let detectedPageEl: HTMLElement | null = null;
    for (const [pageNum, shell] of pageShellRefs.current) {
      const pageEl = shell.querySelector<HTMLElement>(".react-pdf__Page");
      if (pageEl && pageEl.contains(range.commonAncestorContainer)) {
        detectedPageNum = pageNum;
        detectedPageEl = pageEl;
        break;
      }
    }
    if (!detectedPageEl || !detectedPageNum) {
      setSelectionTarget(null);
      return;
    }

    const pageRect = detectedPageEl.getBoundingClientRect();
    const rects = Array.from(range.getClientRects())
      .filter((rect) => rect.width > 2 && rect.height > 2)
      .map((rect) => ({
        x: ((rect.left - pageRect.left) / pageRect.width) * 100,
        y: ((rect.top - pageRect.top) / pageRect.height) * 100,
        width: (rect.width / pageRect.width) * 100,
        height: (rect.height / pageRect.height) * 100,
      }));
    if (rects.length === 0) return;

    const lastRect = range.getBoundingClientRect();
    const viewerRect = viewerRef.current?.getBoundingClientRect();
    setSelectionTarget({
      anchor: {
        workspaceId,
        contractId,
        runId,
        pageNumber: detectedPageNum,
        selectedText: text,
        rects,
      },
      top: viewerRect ? lastRect.bottom - viewerRect.top + 8 : lastRect.bottom + 8,
      left: viewerRect ? Math.min(lastRect.left - viewerRect.left, viewerRect.width - 180) : lastRect.left,
    });
  }, [contractId, runId, workspaceId]);

  const addComment = useCallback(async () => {
    const note = commentDraft.trim();
    if (!selectionTarget || !note || postingComment) return;
    setPostingComment(true);
    setCommentError(null);
    try {
      const saved = await createContractComment(runId, {
        runId,
        workspaceId,
        contractId,
        pageNumber: selectionTarget.anchor.pageNumber,
        selectedText: selectionTarget.anchor.selectedText,
        anchor: selectionTarget.anchor,
        note,
      });
      const mapped = mapApiComment(saved, runId);
      if (mapped) setComments((items) => [...items, mapped]);
      setSelectedCommentId(saved.id);
      setCommentDraft("");
      setSelectionTarget(null);
      window.getSelection()?.removeAllRanges();
    } catch {
      setCommentError("Comment could not be saved.");
    } finally {
      setPostingComment(false);
    }
  }, [commentDraft, contractId, postingComment, runId, selectionTarget, workspaceId]);

  const deleteComment = useCallback(async (commentId: string) => {
    try {
      await deleteContractComment(runId, commentId);
      setComments((items) => items.filter((c) => c.id !== commentId));
      if (selectedCommentId === commentId) setSelectedCommentId(null);
    } catch {
      setCommentError("Could not delete comment.");
    }
  }, [runId, selectedCommentId]);

  const saveEditComment = useCallback(async (commentId: string) => {
    const note = editDraft.trim();
    if (!note) return;
    try {
      const saved = await updateContractComment(runId, commentId, note);
      setComments((items) => items.map((c) =>
        c.id === commentId ? { ...c, note: saved.body } : c
      ));
      setEditingCommentId(null);
      setEditDraft("");
    } catch {
      setCommentError("Could not update comment.");
    }
  }, [runId, editDraft]);

  const makeTextRenderer = useCallback(
    (pageNum: number) => {
      const pagefindings = findingsByPage.get(pageNum) ?? [];
      return (textItem: { str: string }) => {
        const str = textItem.str;
        const trimmed = str.trim();
        if (trimmed.length < 8) return str;
        const normalizedItem = normalizeForMatch(trimmed);
        if (normalizedItem.length < 8) return str;
        const match = pagefindings.find((of_) =>
          of_.anchors
            .filter((anchor) => anchor.pageNumber === pageNum)
            .some((anchor) => anchorMatchesText(anchor, normalizedItem))
        );
        if (match) {
          const cls = SEVERITY_CLASSES[match.finding.severity] ?? "cr-low";
          const selected = selectedFindingId === match.finding.finding_id ? "cr-selected" : "";
          const rawTip = `#${match.index} · ${match.finding.description.slice(0, 120)}${match.finding.description.length > 120 ? "..." : ""}`;
          return `<mark class="cr-mark ${cls} ${selected}" data-finding-id="${escapeHtml(match.finding.finding_id)}" data-num="#${match.index}" data-tip="${escapeHtml(rawTip)}">${str}</mark>`;
        }
        return str;
      };
    },
    [findingsByPage, selectedFindingId]
  );

  const pagefindings = findingsByPage.get(activePage) ?? [];

  // All anchored comments for the left rail, sorted chronologically
  const railComments = useMemo(() => {
    const anchored = comments.filter((c) => c.anchor && c.pageNumber);
    return [...anchored]
      .sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())
      .map((comment, i) => ({ comment, number: i + 1 }));
  }, [comments]);

  const commentNumbers = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of railComments) map.set(item.comment.id, item.number);
    return map;
  }, [railComments]);

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
          box-shadow: 0 0 0 1px rgba(0,0,0,0.02);
        }
        .cr-mark.cr-high   { background: rgba(239,68,68,0.38);  }
        .cr-mark.cr-medium { background: rgba(234,179,8,0.42);  }
        .cr-mark.cr-low    { background: rgba(34,197,94,0.36);  }
        .cr-mark::before {
          content: attr(data-num);
          position: absolute;
          top: -0.95em;
          left: 0;
          min-width: 1.5em;
          height: 1.35em;
          padding: 0 0.32em;
          border-radius: 4px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          font-size: 0.62em;
          font-weight: 800;
          line-height: 1;
          color: #fff;
          z-index: 20;
          pointer-events: none;
          opacity: 0;
          transition: opacity 0.12s;
        }
        .cr-mark.cr-high::before   { background: rgb(220,38,38);  }
        .cr-mark.cr-medium::before { background: rgb(202,138,4);  }
        .cr-mark.cr-low::before    { background: rgb(22,163,74);  }
        .cr-mark.cr-selected::before { opacity: 1; }
        .cr-mark:hover { opacity: 0.78; }
        .cr-mark.cr-selected {
          opacity: 0.98;
          box-shadow: 0 0 0 2px rgba(37,99,235,0.75), 0 0 0 4px rgba(37,99,235,0.14);
        }
        .cr-mark::after {
          content: attr(data-tip);
          position: absolute;
          bottom: calc(100% + 10px);
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
        .cr-comment-rect {
          position: absolute;
          z-index: 25;
          border-radius: 2px;
          cursor: pointer;
          background: rgba(99,102,241,0.14);
          border-bottom: 2px solid rgba(99,102,241,0.62);
          transition: background 0.12s, box-shadow 0.12s;
        }
        .cr-comment-rect:hover,
        .cr-comment-rect.cr-comment-selected {
          background: rgba(99,102,241,0.24);
          box-shadow: 0 0 0 2px rgba(99,102,241,0.42);
        }
        .cr-comment-num {
          position: absolute;
          top: -0.9rem;
          left: 0;
          min-width: 1.35rem;
          height: 1.2rem;
          padding: 0 0.25rem;
          border-radius: 4px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: rgb(79,70,229);
          color: #fff;
          font-size: 0.58rem;
          font-weight: 800;
          line-height: 1;
          pointer-events: none;
          opacity: 0;
          transition: opacity 0.12s;
        }
        .cr-comment-rect.cr-comment-selected .cr-comment-num { opacity: 1; }
        .cr-comment-rect:hover .cr-comment-num { opacity: 1; }
        /* Allow badges/tooltips to escape the pdf.js text layer container */
        .react-pdf__Page__textContent { overflow: visible !important; }
        .react-pdf__Page { overflow: visible !important; }
      `}</style>

      {/* ── 3-column grid: Notes | PDF | Findings ── */}
      <div className="grid items-start" style={{ gridTemplateColumns: "256px 1fr 272px", gap: "24px" }}>

        {/* ── LEFT: Notes / anchored comments ── */}
        <div className="sticky top-24 min-h-0">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary/40 mb-3">
            Notes
          </p>
          {commentError && (
            <p className="mb-2 text-[10px] leading-snug text-risk-high/70">{commentError}</p>
          )}
          {comments.filter(c => c.anchor).length === 0 && !commentError && (
            <p className="text-[10px] text-text-secondary/35 leading-snug">
              Select text in the document to add a note.
            </p>
          )}
          <div className="space-y-2">
            {railComments.map(({ comment, number }) => {
              const active = selectedCommentId === comment.id;
              const isCurrentPage = comment.pageNumber === activePage;
              const isEditing = editingCommentId === comment.id;
              return (
                <div
                  key={comment.id}
                  className={cn(
                    "rounded-md border px-2.5 py-2 shadow-sm transition-all",
                    active
                      ? "border-indigo-400 bg-indigo-50"
                      : isCurrentPage
                        ? "border-indigo-200/60 bg-surface hover:border-indigo-300"
                        : "border-border bg-surface hover:border-indigo-200"
                  )}
                >
                  <div className="mb-1 flex min-w-0 items-center gap-1">
                    <span className={cn(
                      "inline-flex h-5 shrink-0 items-center justify-center rounded border px-1 text-[10px] font-bold",
                      active ? "border-indigo-400 bg-indigo-100 text-indigo-700" : "border-indigo-200 bg-indigo-50 text-indigo-600"
                    )}>
                      #{number}
                    </span>
                    <MessageSquare className={cn("h-3 w-3 shrink-0 ml-0.5", active ? "text-indigo-600" : "text-text-secondary/50")} />
                    <button
                      onClick={() => goToComment(comment)}
                      className="min-w-0 flex-1 truncate text-left text-[11px] font-semibold text-text-primary ml-1"
                    >
                      {comment.username}
                    </button>
                    <span className="shrink-0 text-[10px] text-text-secondary/40 mr-1">p.{comment.pageNumber}</span>
                    <button
                      onClick={() => { setEditingCommentId(comment.id); setEditDraft(comment.note); }}
                      className="shrink-0 rounded p-0.5 text-text-secondary/30 hover:text-indigo-500 transition-colors"
                      title="Edit note"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                    <button
                      onClick={() => deleteComment(comment.id)}
                      className="shrink-0 rounded p-0.5 text-text-secondary/30 hover:text-risk-high transition-colors"
                      title="Delete note"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                  {isEditing ? (
                    <>
                      <textarea
                        value={editDraft}
                        onChange={(e) => setEditDraft(e.target.value)}
                        className="w-full resize-none rounded border border-indigo-200 bg-background px-2 py-1 text-[11px] text-text-primary outline-none focus:border-indigo-400 min-h-12"
                        autoFocus
                      />
                      <div className="mt-1.5 flex justify-end gap-1.5">
                        <button
                          onClick={() => { setEditingCommentId(null); setEditDraft(""); }}
                          className="rounded px-2 py-0.5 text-[10px] text-text-secondary/60 hover:text-text-primary border border-border"
                        >Cancel</button>
                        <button
                          onClick={() => saveEditComment(comment.id)}
                          className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-semibold text-white bg-indigo-500 hover:bg-indigo-600"
                        >
                          <Check className="h-3 w-3" /> Save
                        </button>
                      </div>
                    </>
                  ) : (
                    <button
                      onClick={() => goToComment(comment)}
                      className="w-full text-left"
                      title={comment.note}
                    >
                      <span className="block break-words text-[11px] leading-snug text-text-secondary/75">
                        {comment.note}
                      </span>
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── CENTER: PDF viewer (all pages scrollable) or Editor ── */}
        <div className="min-w-0 flex flex-col gap-4">
          {/* Editor toggle */}
          <div className="flex items-center justify-end">
            <button
              onClick={() => setEditorMode((m) => !m)}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold transition-all",
                editorMode
                  ? "bg-text-primary text-background border-text-primary"
                  : "border-border text-text-secondary hover:border-text-primary hover:text-text-primary"
              )}
            >
              <FileEdit className="h-3.5 w-3.5" />
              {editorMode ? "✓ Done" : "Edit Document"}
            </button>
          </div>

          {editorMode ? (
            <ContractEditor runId={runId} filename={filename} currentUserName={currentUserName} />
          ) : (
        <div
          ref={viewerRef}
          className="relative min-w-0"
          onClick={handleViewerClick}
          onMouseUp={captureSelection}
        >
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
                <div className="flex flex-col gap-4">
                  {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => {
                    const pageComments = commentsByPage.get(pageNum) ?? [];
                    return (
                      <div
                        key={pageNum}
                        data-page-number={pageNum}
                        ref={(el) => {
                          if (el) pageShellRefs.current.set(pageNum, el);
                          else pageShellRefs.current.delete(pageNum);
                        }}
                        className="relative rounded-xl overflow-hidden border border-border shadow-sm"
                      >
                        <Page
                          pageNumber={pageNum}
                          width={viewerWidth}
                          renderAnnotationLayer={false}
                          customTextRenderer={makeTextRenderer(pageNum)}
                        />
                        {/* Comment overlay rects */}
                        <div className="pointer-events-none absolute inset-0">
                          {pageComments.flatMap((comment) =>
                            comment.anchor.rects.map((rect, index) => (
                              <button
                                key={`${comment.id}-${index}`}
                                type="button"
                                data-comment-id={comment.id}
                                aria-label={`Comment by ${comment.username}: ${comment.note}`}
                                title={`${comment.username}: ${comment.note}`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  goToComment(comment);
                                }}
                                className={cn(
                                  "pointer-events-auto cr-comment-rect",
                                  selectedCommentId === comment.id && "cr-comment-selected"
                                )}
                                style={{
                                  left: `${rect.x}%`,
                                  top: `${rect.y}%`,
                                  width: `${rect.width}%`,
                                  height: `${rect.height}%`,
                                }}
                              >
                                {index === 0 && (
                                  <span className="cr-comment-num">
                                    #{commentNumbers.get(comment.id) ?? "?"}
                                  </span>
                                )}
                              </button>
                            ))
                          )}
                        </div>
                        {/* Page label */}
                        <div className="absolute bottom-2 right-3 text-[10px] text-text-secondary/30 pointer-events-none select-none">
                          {pageNum} / {numPages}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Document>
          )}

          {/* Selection → add note popover */}
          {selectionTarget && (
            <div
              className="absolute z-50 w-64 rounded-lg border border-border bg-surface p-2 shadow-lg"
              style={{ top: selectionTarget.top, left: Math.max(0, selectionTarget.left) }}
              onClick={(event) => event.stopPropagation()}
              onMouseDown={(event) => event.stopPropagation()}
              onMouseUp={(event) => event.stopPropagation()}
            >
              <div className="flex items-center gap-2 mb-2">
                <MessageSquare className="h-3.5 w-3.5 text-indigo-500" />
                <span className="text-[11px] font-semibold text-text-primary">Add note</span>
                <button
                  onClick={() => setSelectionTarget(null)}
                  className="ml-auto rounded p-0.5 text-text-secondary hover:text-text-primary"
                  type="button"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <textarea
                value={commentDraft}
                onChange={(event) => setCommentDraft(event.target.value)}
                placeholder="Write a note…"
                className="min-h-16 w-full resize-none rounded-md border border-border bg-background px-2 py-1.5 text-xs text-text-primary outline-none focus:border-indigo-300"
                autoFocus
              />
              <div className="mt-2 flex items-center justify-between gap-2">
                <span className="truncate text-[10px] text-text-secondary/60">
                  p.{selectionTarget.anchor.pageNumber}
                </span>
                <button
                  onClick={addComment}
                  disabled={!commentDraft.trim() || postingComment}
                  className="rounded-md bg-text-primary px-2 py-1 text-[11px] font-semibold text-background disabled:opacity-40"
                  type="button"
                >
                  {postingComment ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          )}
        </div>
          )}
        </div>

        {/* ── RIGHT: Findings sidebar ── */}
        <div className="sticky top-24 space-y-2">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary/50 mb-3">
            Findings · {ordered.length} total
          </p>

          {ordered.map((item) => {
            const { finding, index, firstPage, anchors } = item;
            const isOnPage = (findingsByPage.get(activePage) ?? []).some((f) => f.index === index);
            const isSelected = selectedFindingId === finding.finding_id;
            const chipCls = SEVERITY_CHIP[finding.severity] ?? SEVERITY_CHIP.low;
            const targetPage = firstPage && numPages ? Math.min(firstPage, numPages) : null;
            return (
              <button
                key={finding.finding_id}
                onClick={() => targetPage && goToFinding(item)}
                disabled={!targetPage}
                className={cn(
                  "w-full text-left rounded-lg border px-3 py-3 transition-all cursor-pointer",
                  isSelected
                    ? "border-blue-500 bg-blue-50/40 shadow-sm"
                    : isOnPage
                      ? "border-accent/40 bg-accent/5"
                      : "border-border hover:border-border/80 hover:bg-drop-zone/20",
                  !targetPage && "cursor-default opacity-70"
                )}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded border", chipCls)}>
                    #{index}
                  </span>
                  <span className={cn("text-[10px] font-semibold uppercase", chipCls.split(" ")[1])}>
                    {finding.severity === "critical" ? "CRITICAL" : finding.severity.toUpperCase()}
                  </span>
                  <span className="ml-auto text-[10px] text-text-secondary/40">
                    {firstPage ? `p.${firstPage}` : "location unavailable"}
                  </span>
                </div>
                <p className="text-xs font-medium text-text-primary leading-snug line-clamp-2 mb-1">
                  {finding.description}
                </p>
                {anchors.length === 0 && (
                  <p className="text-[10px] text-text-secondary/50 leading-snug mb-1">
                    No reliable document anchor was returned for this finding.
                  </p>
                )}
                {finding.recommendation_detail && (
                  <p className="text-[10px] text-text-secondary/70 leading-snug line-clamp-2 italic">
                    → {finding.recommendation_detail}
                  </p>
                )}
              </button>
            );
          })}

          {pagefindings.length > 0 && (
            <div className="pt-3 border-t border-border/60">
              <p className="text-[10px] text-text-secondary/50 mb-2">On this page:</p>
              <div className="flex flex-wrap gap-1.5">
                {pagefindings.map(({ index, finding }) => {
                  const chipCls = SEVERITY_CHIP[finding.severity] ?? SEVERITY_CHIP.low;
                  return (
                    <span key={index} className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded border", chipCls)}>
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
