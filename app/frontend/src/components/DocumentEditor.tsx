import React, { useCallback, useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";
import { getDocumentDraft, saveBlockEdit } from "@/lib/api";
import type { CommentAnchor, DocumentAnnotation, DocumentDraft, DraftBlock, Finding } from "@/types";


const SEV_COLOR: Record<string, string> = {
  critical: "#dc2626",
  high: "#dc2626",
  medium: "#d97706",
  low: "#16a34a",
};

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

function renderInlineDiff(chunks: DiffChunk[]): React.ReactNode {
  return chunks.map((chunk, i) => {
    if (chunk.type === "del")
      return (
        <span key={i} data-diff-del="" style={{ textDecoration: "line-through", color: "#dc2626", opacity: 0.85 }}>
          {chunk.text}{" "}
        </span>
      );
    if (chunk.type === "add")
      return (
        <span key={i} data-diff-add="" style={{ color: "#15803d", background: "rgba(21,128,61,0.1)", borderRadius: 2 }}>
          {chunk.text}{" "}
        </span>
      );
    return <span key={i}>{chunk.text} </span>;
  });
}

function renderTextWithAnchors(
  text: string,
  anchors: CommentAnchor[],
  activeAnnotationId: string | null,
  hoveredAnnotationId: string | null,
  onAnnotationActivate: (id: string | null) => void,
  onAnnotationHover: (id: string | null) => void,
): React.ReactNode {
  if (!anchors.length) return text;
  const sorted = [...anchors].sort((a, b) => a.from_pos - b.from_pos);
  const parts: React.ReactNode[] = [];
  let pos = 0;
  for (const anchor of sorted) {
    const from = Math.max(0, Math.min(anchor.from_pos, text.length));
    const to = Math.max(from, Math.min(anchor.to_pos, text.length));
    if (from > pos) parts.push(text.slice(pos, from));
    const isActive = activeAnnotationId === anchor.annotation_id;
    const isHov = hoveredAnnotationId === anchor.annotation_id;
    parts.push(
      <mark
        key={anchor.annotation_id}
        data-annotation-id={anchor.annotation_id}
        style={{
          background: isActive
            ? "rgba(37,99,235,0.28)"
            : isHov
            ? "rgba(37,99,235,0.18)"
            : "rgba(37,99,235,0.10)",
          borderBottom: `2px solid ${isActive || isHov ? "#2563eb" : "rgba(37,99,235,0.35)"}`,
          borderRadius: 1,
          cursor: "pointer",
        }}
        onMouseEnter={() => onAnnotationHover(anchor.annotation_id)}
        onMouseLeave={() => onAnnotationHover(null)}
        onClick={() => onAnnotationActivate(isActive ? null : anchor.annotation_id)}
      >
        {text.slice(from, to)}
      </mark>,
    );
    pos = to;
  }
  if (pos < text.length) parts.push(text.slice(pos));
  return <>{parts}</>;
}

const BLOCK_STYLES: Record<string, React.CSSProperties> = {
  heading1: {
    fontFamily: "Georgia, 'Times New Roman', serif",
    fontSize: 17,
    fontWeight: 700,
    lineHeight: 1.4,
    marginTop: 28,
    marginBottom: 10,
    color: "#111",
    letterSpacing: "-0.01em",
  },
  heading2: {
    fontFamily: "Georgia, 'Times New Roman', serif",
    fontSize: 14,
    fontWeight: 700,
    lineHeight: 1.45,
    marginTop: 20,
    marginBottom: 6,
    color: "#1a1a1a",
  },
  heading3: {
    fontFamily: "Georgia, 'Times New Roman', serif",
    fontSize: 13,
    fontWeight: 600,
    lineHeight: 1.5,
    marginTop: 16,
    marginBottom: 4,
    color: "#222",
  },
  body: {
    fontFamily: "Georgia, 'Times New Roman', serif",
    fontSize: 12,
    lineHeight: 1.85,
    marginTop: 0,
    marginBottom: 10,
    color: "#111",
  },
  list_item: {
    fontFamily: "Georgia, 'Times New Roman', serif",
    fontSize: 12,
    lineHeight: 1.75,
    marginTop: 0,
    marginBottom: 6,
    paddingLeft: 20,
    color: "#111",
  },
};

interface BlockProps {
  block: DraftBlock;
  viewMode: "comment" | "edit";
  showRedlines: boolean;
  activeAnnotationId: string | null;
  hoveredAnnotationId: string | null;
  onAnnotationActivate: (id: string | null) => void;
  onAnnotationHover: (id: string | null) => void;
  onSave: (clauseUid: string, newText: string) => Promise<void>;
  onAccept: (findingId: string, replacementText: string) => void;
  onDismiss: (findingId: string) => void;
}

function DocumentBlock({
  block,
  viewMode,
  showRedlines,
  activeAnnotationId,
  hoveredAnnotationId,
  onAnnotationActivate,
  onAnnotationHover,
  onSave,
  onAccept,
  onDismiss,
}: BlockProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const editRef = useRef<HTMLDivElement>(null);
  const styleKey = block.style || "body";
  const baseStyle = BLOCK_STYLES[styleKey] ?? BLOCK_STYLES.body;

  const hasPending = Boolean(block.pending_suggestion);
  const hasAcceptedEdit = block.text !== block.original_text;

  function startEdit() {
    setIsEditing(true);
    setTimeout(() => {
      if (editRef.current) {
        editRef.current.focus();
        const range = document.createRange();
        range.selectNodeContents(editRef.current);
        range.collapse(false);
        const sel = window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
    }, 0);
  }

  async function commitEdit() {
    if (!editRef.current) return;
    const newText = editRef.current.innerText.trim();
    if (newText === block.text) {
      setIsEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(block.clause_uid, newText);
    } finally {
      setSaving(false);
      setIsEditing(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      commitEdit();
    }
    if (e.key === "Escape") {
      if (editRef.current) editRef.current.innerText = block.text;
      setIsEditing(false);
    }
  }

  const renderContent = () => {
    if (isEditing) return null;

    if (showRedlines && hasPending && !hasAcceptedEdit) {
      const chunks = computeWordDiff(block.original_text, block.pending_suggestion!.replacement_text);
      return <>{renderInlineDiff(chunks)}</>;
    }

    const displayText = block.text;
    if (block.comment_anchors.length > 0) {
      return renderTextWithAnchors(
        displayText,
        block.comment_anchors,
        activeAnnotationId,
        hoveredAnnotationId,
        onAnnotationActivate,
        onAnnotationHover,
      );
    }
    return displayText;
  };

  const hasHighlightedAnchor = block.comment_anchors.some(
    (a) => a.annotation_id === activeAnnotationId || a.annotation_id === hoveredAnnotationId,
  );

  return (
    <div
      className="group relative"
      data-block-id={block.block_id}
      data-clause-uid={block.clause_uid}
    >
      {/* Edit-mode click target */}
      {viewMode === "edit" && !isEditing && (
        <div
          className="absolute inset-0 -mx-2 cursor-text rounded hover:bg-blue-50/50"
          style={{ zIndex: 1 }}
          onClick={startEdit}
          title="Click to edit"
        />
      )}

      {/* Accepted-edit indicator */}
      {hasAcceptedEdit && !hasPending && (
        <div
          className="absolute -left-3 top-0 bottom-0 w-[3px] rounded-full"
          style={{ background: "#2563eb" }}
        />
      )}

      {/* The paragraph */}
      <div
        ref={isEditing ? editRef : undefined}
        contentEditable={isEditing}
        suppressContentEditableWarning
        onBlur={isEditing ? commitEdit : undefined}
        onKeyDown={isEditing ? handleKeyDown : undefined}
        style={{
          ...baseStyle,
          outline: isEditing ? "2px solid rgba(37,99,235,0.4)" : "none",
          borderRadius: isEditing ? 3 : 0,
          padding: isEditing ? "4px 6px" : undefined,
          background: hasHighlightedAnchor ? "rgba(37,99,235,0.03)" : undefined,
          position: "relative",
          zIndex: isEditing ? 2 : undefined,
        }}
      >
        {isEditing ? block.text : renderContent()}
      </div>

      {/* Saving indicator */}
      {saving && (
        <span className="absolute right-0 top-0 text-[9px] text-blue-400">Saving...</span>
      )}

      {/* Pending suggestion actions — shown inline below the block when redlines visible */}
      {showRedlines && hasPending && !hasAcceptedEdit && block.pending_suggestion && (
        <div
          className="doc-suggestion-bar mt-1 mb-2 flex items-center gap-2 rounded px-2 py-1.5"
          style={{ background: "rgba(37,99,235,0.04)", border: "1px solid rgba(37,99,235,0.12)" }}
        >
          <span
            className="flex-shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white"
            style={{ background: SEV_COLOR[block.pending_suggestion.severity] ?? "#6b7280" }}
          >
            {block.pending_suggestion.severity}
          </span>
          <span className="line-clamp-1 flex-1 text-[10px] text-text-secondary/70">
            {block.pending_suggestion.description}
          </span>
          <button
            onClick={() =>
              onAccept(
                block.pending_suggestion!.finding_id,
                block.pending_suggestion!.replacement_text,
              )
            }
            className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold text-green-700 hover:bg-green-50"
            title="Accept this suggestion"
          >
            <Check className="h-3 w-3" /> Accept
          </button>
          <button
            onClick={() => onDismiss(block.pending_suggestion!.finding_id)}
            className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary/60 hover:bg-gray-100"
            title="Dismiss this suggestion"
          >
            <X className="h-3 w-3" /> Dismiss
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

export interface CommentDraft {
  clauseUid: string;
  pageNumber: number;
  selectedText: string;
  fromPos: number;
  toPos: number;
}

export interface DocumentEditorProps {
  runId: string;
  findings: Finding[];
  annotations: DocumentAnnotation[];
  viewMode: "comment" | "edit";
  showRedlines: boolean;
  activeAnnotationId: string | null;
  hoveredAnnotationId: string | null;
  draftRefreshKey: number;
  onAnnotationActivate: (id: string | null) => void;
  onAnnotationHover: (id: string | null) => void;
  onCommentDraft: (draft: CommentDraft | null) => void;
  onFindingAccept: (findingId: string, replacementText: string) => void;
  onFindingDismiss: (findingId: string) => void;
}

const PRINT_STYLE = `
@media print {
  .doc-suggestion-bar { display: none !important; }
  .doc-accepted-bar   { display: none !important; }
  span[data-diff-del]  { display: none !important; }
  span[data-diff-add]  { color: inherit !important; background: none !important; text-decoration: none !important; }
  mark { background: none !important; border: none !important; }
}
`;

export default function DocumentEditor({
  runId,
  findings: _findings,
  annotations: _annotations,
  viewMode,
  showRedlines,
  activeAnnotationId,
  hoveredAnnotationId,
  draftRefreshKey,
  onAnnotationActivate,
  onAnnotationHover,
  onCommentDraft,
  onFindingAccept,
  onFindingDismiss,
}: DocumentEditorProps) {
  const [draft, setDraft] = useState<DocumentDraft | null>(null);
  const [loadErr, setLoadErr] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const captureRef = useRef<() => void>(() => {});

  useEffect(() => {
    let cancelled = false;
    setLoadErr(false);
    getDocumentDraft(runId)
      .then((d) => { if (!cancelled) setDraft(d); })
      .catch(() => { if (!cancelled) setLoadErr(true); });
    return () => { cancelled = true; };
  }, [runId, draftRefreshKey]);

  // Poll every 15 s so teammates' accepted changes appear without a manual reload.
  useEffect(() => {
    const id = setInterval(() => {
      getDocumentDraft(runId)
        .then((d) => setDraft(d))
        .catch(() => {});
    }, 15_000);
    return () => clearInterval(id);
  }, [runId]);

  // Selection capture for comment mode
  const captureSelection = useCallback(() => {
    if (viewMode !== "comment") return;
    const sel = window.getSelection();
    const text = sel?.toString().trim();
    if (!text || !sel) return;

    const container = containerRef.current;
    if (!container) return;
    const anchor = sel.anchorNode;
    if (!anchor || !container.contains(anchor)) return;

    // Find the nearest block element
    let el: Element | null = anchor instanceof Element ? anchor : anchor.parentElement;
    while (el && !el.getAttribute("data-clause-uid")) el = el.parentElement;
    if (!el) return;

    const clauseUid = el.getAttribute("data-clause-uid");
    if (!clauseUid || !draft) return;
    const block = draft.blocks.find((b) => b.clause_uid === clauseUid);
    if (!block) return;

    const blockText = block.text;
    const norm = (s: string) => s.replace(/\s+/g, " ").toLowerCase().trim();
    const normText = norm(text);
    const normBlock = norm(blockText);
    const idx = normBlock.indexOf(normText);

    sel.removeAllRanges();

    onCommentDraft({
      clauseUid,
      pageNumber: block.page_number,
      selectedText: text.replace(/\s+/g, " ").trim(),
      fromPos: Math.max(0, idx),
      toPos: Math.max(0, idx) + normText.length,
    });
  }, [viewMode, draft, onCommentDraft]);

  captureRef.current = captureSelection;

  useEffect(() => {
    if (viewMode !== "comment") return;
    function onUp() { setTimeout(() => captureRef.current(), 0); }
    document.addEventListener("mouseup", onUp);
    return () => document.removeEventListener("mouseup", onUp);
  }, [viewMode]);

  const handleSave = useCallback(
    async (clauseUid: string, newText: string) => {
      await saveBlockEdit(runId, clauseUid, newText);
      setDraft((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          blocks: prev.blocks.map((b) =>
            b.clause_uid === clauseUid ? { ...b, text: newText } : b,
          ),
        };
      });
    },
    [runId],
  );

  function handleAccept(findingId: string, replacementText: string) {
    // Optimistically remove the pending suggestion from the relevant block
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        blocks: prev.blocks.map((b) =>
          b.pending_suggestion?.finding_id === findingId
            ? { ...b, text: replacementText, pending_suggestion: null }
            : b,
        ),
      };
    });
    onFindingAccept(findingId, replacementText);
  }

  function handleDismiss(findingId: string) {
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        blocks: prev.blocks.map((b) =>
          b.pending_suggestion?.finding_id === findingId
            ? { ...b, pending_suggestion: null }
            : b,
        ),
      };
    });
    onFindingDismiss(findingId);
  }

  if (loadErr) {
    return (
      <div className="py-10 text-center text-sm text-red-500">
        Failed to load document draft. Check that the backend is running.
      </div>
    );
  }
  if (!draft) {
    return <div className="py-10 text-center text-sm text-text-secondary/50">Loading document...</div>;
  }

  // Group blocks by page
  const pages: number[] = [];
  const blocksByPage: Record<number, DraftBlock[]> = {};
  for (const block of draft.blocks) {
    if (!blocksByPage[block.page_number]) {
      blocksByPage[block.page_number] = [];
      pages.push(block.page_number);
    }
    blocksByPage[block.page_number].push(block);
  }
  const sortedPages = pages.sort((a, b) => a - b);

  return (
    <div ref={containerRef} className="select-text">
      <style>{PRINT_STYLE}</style>
      <div className="space-y-6">
        {sortedPages.map((pageNum) => (
          <div
            key={pageNum}
            className="mx-auto"
            style={{
              width: 760,
              background: "#fff",
              boxShadow: "0 2px 12px rgba(0,0,0,0.10), 0 0 0 1px rgba(0,0,0,0.06)",
              borderRadius: 2,
            }}
          >
            {/* Page header */}
            <div
              style={{
                borderBottom: "1px solid #f0f0f0",
                padding: "7px 80px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span style={{ fontSize: 9, color: "#aaa", letterSpacing: "0.08em", textTransform: "uppercase" }}>
                Page {pageNum}
              </span>
            </div>

            {/* Page content with margins */}
            <div style={{ padding: "60px 80px 72px" }}>
              {(blocksByPage[pageNum] || []).map((block) => (
                <DocumentBlock
                  key={block.block_id}
                  block={block}
                  viewMode={viewMode}
                  showRedlines={showRedlines}
                  activeAnnotationId={activeAnnotationId}
                  hoveredAnnotationId={hoveredAnnotationId}
                  onAnnotationActivate={onAnnotationActivate}
                  onAnnotationHover={onAnnotationHover}
                  onSave={handleSave}
                  onAccept={handleAccept}
                  onDismiss={handleDismiss}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
