import React, { useState, useMemo, useEffect, useRef } from "react";
import {
  AlertCircle,
  Check,
  X,
  Trash2,
  ExternalLink,
  Edit3,
  MessageSquare,
} from "lucide-react";
import {
  acceptFinding,
  createAnnotation,
  deleteAnnotation,
  dismissFinding,
  getContractEdits,
  getRunFileUrl,
  listAnnotations,
  listRunClauses,
  saveClauseEdit,
} from "@/lib/api";
import type { ClauseData, ContractEdit, DocumentAnnotation, Finding } from "@/types";
import { cn } from "@/lib/utils";

// ── Color palette ──────────────────────────────────────────────────────────────

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
const COMMENT_HIGHLIGHT = "rgba(37,99,235,0.22)";

// ── Types ──────────────────────────────────────────────────────────────────────

type ViewMode = "comment" | "edit";

interface OrderedFinding {
  finding: Finding;
  index: number;
}

interface SelectionDraft {
  clauseUid: string;
  selectedText: string;
  spanStart: number;
  spanEnd: number;
  pageNumber: number;
  body: string;
}

interface ContractReaderProps {
  runId: string;
  findings: Finding[];
  jumpToIndex?: number | null;
  onJumpHandled?: () => void;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function orderFindings(findings: Finding[]): OrderedFinding[] {
  return findings.map((f, i) => ({ finding: f, index: i + 1 }));
}

function currentClauseText(clause: ClauseData, edits: Record<string, ContractEdit>): string {
  return edits[clause.clause_uid]?.text ?? clause.normalized_text;
}

function isHtmlContent(text: string): boolean {
  return /<[a-z][\s\S]*>/i.test(text);
}

function plainToHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}

// Highlights all occurrences of each needle in text with the given background color.
function renderHighlighted(
  text: string,
  highlights: Array<{ needle: string; color: string }>
): React.ReactNode {
  if (!highlights.length) return text;

  type Range = { start: number; end: number; color: string };
  const ranges: Range[] = [];

  const textLower = text.toLowerCase();
  for (const { needle, color } of highlights) {
    if (!needle) continue;
    const needleLower = needle.toLowerCase();
    let idx = 0;
    while (idx < text.length) {
      const pos = textLower.indexOf(needleLower, idx);
      if (pos === -1) break;
      ranges.push({ start: pos, end: pos + needle.length, color });
      idx = pos + needle.length;
    }
  }

  if (!ranges.length) return text;

  ranges.sort((a, b) => a.start - b.start);
  const merged: Range[] = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r.start < last.end) continue;
    merged.push(r);
  }

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  for (const r of merged) {
    if (r.start > cursor) parts.push(text.slice(cursor, r.start));
    parts.push(
      <mark
        key={`${r.start}-${r.end}`}
        style={{ background: r.color, color: "inherit", borderRadius: 2, padding: "0 1px" }}
      >
        {text.slice(r.start, r.end)}
      </mark>
    );
    cursor = r.end;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function ContractReader({ runId, findings, jumpToIndex, onJumpHandled }: ContractReaderProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("comment");
  const [clauses, setClauses] = useState<ClauseData[]>([]);
  const [contractEdits, setContractEdits] = useState<Record<string, ContractEdit>>({});
  const [annotations, setAnnotations] = useState<DocumentAnnotation[]>([]);
  const [hiddenFindingIds, setHiddenFindingIds] = useState<Set<string>>(new Set());
  const [expandedFindingIds, setExpandedFindingIds] = useState<Set<string>>(new Set());
  const [clauseLoadErr, setClauseLoadErr] = useState(false);
  const [actionError, setActionError] = useState("");
  const [selectionDraft, setSelectionDraft] = useState<SelectionDraft | null>(null);

  const clauseRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const fileUrl = getRunFileUrl(runId);

  // ── Derived data ──

  const ordered = useMemo(
    () => orderFindings(findings.filter((f) => !hiddenFindingIds.has(f.finding_id))),
    [findings, hiddenFindingIds]
  );

  const findingsByClause = useMemo(() => {
    const map = new Map<string, OrderedFinding[]>();
    for (const item of ordered) {
      const uid = item.finding.clause_uid;
      if (!map.has(uid)) map.set(uid, []);
      map.get(uid)!.push(item);
    }
    return map;
  }, [ordered]);

  const annotationsByClause = useMemo(() => {
    const map = new Map<string, DocumentAnnotation[]>();
    for (const a of annotations) {
      if (!map.has(a.clause_uid)) map.set(a.clause_uid, []);
      map.get(a.clause_uid)!.push(a);
    }
    return map;
  }, [annotations]);

  const annotationNumMap = useMemo(() => {
    const map = new Map<string, number>();
    let n = 1;
    for (const clause of clauses) {
      for (const ann of annotationsByClause.get(clause.clause_uid) ?? []) {
        map.set(ann.id, n++);
      }
    }
    return map;
  }, [clauses, annotationsByClause]);

  // ── Data loading ──

  useEffect(() => {
    if (!runId) return;
    setClauseLoadErr(false);
    Promise.all([listRunClauses(runId), getContractEdits(runId), listAnnotations(runId)])
      .then(([clauseData, edits, annData]) => {
        setClauses(clauseData);
        setContractEdits(edits);
        setAnnotations(annData);
      })
      .catch(() => setClauseLoadErr(true));
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    const id = setInterval(() => {
      listAnnotations(runId).then(setAnnotations).catch(() => {});
    }, 5000);
    return () => clearInterval(id);
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    const id = setInterval(() => {
      getContractEdits(runId).then(setContractEdits).catch(() => {});
    }, 8000);
    return () => clearInterval(id);
  }, [runId]);

  // Jump to finding
  useEffect(() => {
    if (jumpToIndex == null) return;
    const target = ordered.find((item) => item.index === jumpToIndex);
    if (target) {
      clauseRefs.current[target.finding.clause_uid]?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    onJumpHandled?.();
  }, [jumpToIndex, ordered, onJumpHandled]);

  // ── Actions ──

  async function handleAccept(finding: Finding) {
    const replacement = finding.recommended_change?.trim();
    if (!replacement) {
      setActionError("This finding does not include concrete replacement text.");
      return;
    }
    setActionError("");
    try {
      await acceptFinding(runId, finding.finding_id, replacement);
      setContractEdits((prev) => ({
        ...prev,
        [finding.clause_uid]: { text: replacement, edited_at: new Date().toISOString() },
      }));
      setHiddenFindingIds((prev) => new Set(prev).add(finding.finding_id));
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

  async function handleSaveClause(clauseUid: string, text: string) {
    await saveClauseEdit(runId, clauseUid, text);
    setContractEdits((prev) => ({
      ...prev,
      [clauseUid]: { text, edited_at: new Date().toISOString() },
    }));
  }

  function captureViewSelection(clause: ClauseData) {
    if (viewMode !== "comment") return;
    const sel = window.getSelection();
    const selectedText = sel?.toString().trim();
    if (!selectedText) return;
    setSelectionDraft({
      clauseUid: clause.clause_uid,
      selectedText,
      spanStart: 0,
      spanEnd: selectedText.length,
      pageNumber: clause.page_number,
      body: "",
    });
  }

  async function saveSelectionComment() {
    if (!selectionDraft?.body.trim()) return;
    const annotation = await createAnnotation(runId, {
      clause_uid: selectionDraft.clauseUid,
      annotation_type: "comment",
      body: selectionDraft.body.trim(),
      selected_text: selectionDraft.selectedText,
      span_start: selectionDraft.spanStart,
      span_end: selectionDraft.spanEnd,
      page_number: selectionDraft.pageNumber,
    });
    setAnnotations((prev) => [...prev, annotation]);
    setSelectionDraft(null);
  }

  async function removeAnnotation(annotationId: string) {
    await deleteAnnotation(runId, annotationId);
    setAnnotations((prev) => prev.filter((a) => a.id !== annotationId));
  }

  function toggleFinding(findingId: string) {
    setExpandedFindingIds((prev) => {
      const next = new Set(prev);
      if (next.has(findingId)) next.delete(findingId);
      else next.add(findingId);
      return next;
    });
  }

  const hasData = clauses.length > 0;

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="w-full">
      {/* Toolbar */}
      <div className="mb-5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 text-xs text-text-secondary/60">
          {ordered.length > 0 && (
            <span>{ordered.length} AI finding{ordered.length !== 1 ? "s" : ""}</span>
          )}
          {annotations.length > 0 && (
            <span style={{ color: COMMENT_COLOR }}>
              {annotations.length} comment{annotations.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <a
            href={fileUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-text-secondary transition-colors hover:border-text-secondary/40 hover:text-text-primary"
          >
            <ExternalLink className="h-3 w-3" /> Original PDF
          </a>
          <div className="flex overflow-hidden rounded-lg border border-border text-xs font-medium">
            <button
              onClick={() => setViewMode("comment")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 transition-colors",
                viewMode === "comment"
                  ? "bg-accent/10 text-accent"
                  : "text-text-secondary hover:text-text-primary"
              )}
            >
              <MessageSquare className="h-3 w-3" /> Comment
            </button>
            <button
              onClick={() => setViewMode("edit")}
              className={cn(
                "flex items-center gap-1.5 border-l border-border px-3 py-1.5 transition-colors",
                viewMode === "edit"
                  ? "bg-accent/10 text-accent"
                  : "text-text-secondary hover:text-text-primary"
              )}
            >
              <Edit3 className="h-3 w-3" /> Edit
            </button>
          </div>
        </div>
      </div>

      {actionError && (
        <div className="mb-4 rounded-md border border-risk-high/30 bg-risk-high/5 px-3 py-2 text-xs text-risk-high">
          {actionError}
        </div>
      )}

      {clauseLoadErr && (
        <div className="flex items-center gap-2 py-4 text-sm text-risk-high">
          <AlertCircle className="h-4 w-4" /> Failed to load clause data.
        </div>
      )}

      {!hasData && !clauseLoadErr && (
        <div className="py-10 text-center text-sm text-text-secondary/60">
          No extracted clauses found for this document.
        </div>
      )}

      {hasData && (
        <>
          {/* Column headers */}
          <div className="mb-2 grid grid-cols-[220px_minmax(0,1fr)_260px] gap-x-6">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary/40">
              Comments · {annotations.length}
            </p>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary/40">
              {viewMode === "comment" ? "Document · select text to comment" : "Document · click to edit inline"}
            </p>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary/40">
              AI Findings · {ordered.length}
            </p>
          </div>

          {/* Clause rows — each clause gets its own 3-column row for clear visual separation */}
          <div className="divide-y divide-border/60">
            {clauses.map((clause) => {
              const text = currentClauseText(clause, contractEdits);
              const clauseFindings = findingsByClause.get(clause.clause_uid) ?? [];
              const clauseAnnotations = annotationsByClause.get(clause.clause_uid) ?? [];
              const isDraftHere = selectionDraft?.clauseUid === clause.clause_uid;

              // Highlight only the specific evidence text from each finding, not the whole clause
              const findingHighlights = clauseFindings.flatMap(({ finding }) => {
                const needle = (
                  finding.contract_evidence?.[0]?.text ||
                  finding.evidence?.[0]?.normalized_text ||
                  ""
                ).trim();
                if (!needle || needle.length > 250) return [];
                const baseColor = SEV_COLOR[finding.severity] ?? SEV_COLOR.low;
                return [{ needle, color: `${baseColor}28` }];
              });

              const commentHighlights = clauseAnnotations
                .filter((a) => a.selected_text)
                .map((a) => ({ needle: a.selected_text!, color: COMMENT_HIGHLIGHT }));

              const allHighlights = [...findingHighlights, ...commentHighlights];

              return (
                <div
                  key={clause.clause_uid}
                  className="grid grid-cols-[220px_minmax(0,1fr)_260px] gap-x-6 py-6"
                  ref={(el) => { clauseRefs.current[clause.clause_uid] = el as HTMLDivElement | null; }}
                >
                  {/* LEFT — comments */}
                  <div className="space-y-2 min-h-[56px]">
                    {isDraftHere && (
                      <div
                        className="rounded-lg p-3"
                        style={{ background: COMMENT_BG, border: `1px solid ${COMMENT_BORDER}` }}
                      >
                        <p
                          className="mb-1 text-[10px] font-semibold uppercase tracking-widest"
                          style={{ color: COMMENT_COLOR }}
                        >
                          Comment on selection
                        </p>
                        <p className="mb-2 line-clamp-2 text-[11px] italic text-text-secondary">
                          &ldquo;{selectionDraft!.selectedText}&rdquo;
                        </p>
                        <textarea
                          value={selectionDraft!.body}
                          onChange={(e) => setSelectionDraft({ ...selectionDraft!, body: e.target.value })}
                          rows={2}
                          className="mb-2 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-text-primary outline-none focus:border-accent/60 resize-none"
                          autoFocus
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) saveSelectionComment();
                          }}
                          placeholder="Add a comment…"
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
                            disabled={!selectionDraft!.body.trim()}
                            className="rounded px-2 py-1 text-[10px] font-semibold text-white disabled:opacity-50"
                            style={{ background: COMMENT_COLOR }}
                          >
                            Add
                          </button>
                        </div>
                      </div>
                    )}
                    {clauseAnnotations.map((annotation) => (
                      <AnnotationCard
                        key={annotation.id}
                        annotation={annotation}
                        num={annotationNumMap.get(annotation.id)}
                        onDelete={() => removeAnnotation(annotation.id)}
                      />
                    ))}
                  </div>

                  {/* CENTER — document text */}
                  <div>
                    <div className="mb-2 flex items-center gap-2 flex-wrap">
                      <span className="text-[10px] font-semibold uppercase tracking-widest text-text-secondary/40">
                        {clause.clause_uid} · Page {clause.page_number}
                      </span>
                      {contractEdits[clause.clause_uid] && (
                        <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-semibold text-accent">
                          Edited
                        </span>
                      )}
                      {clauseFindings.map(({ finding }) => (
                        <span
                          key={finding.finding_id}
                          style={{
                            fontSize: 9,
                            fontWeight: 700,
                            textTransform: "uppercase",
                            letterSpacing: "0.06em",
                            color: SEV_COLOR[finding.severity] ?? SEV_COLOR.low,
                            background: SEV_BG[finding.severity] ?? SEV_BG.low,
                            border: `1px solid ${SEV_BORDER[finding.severity] ?? SEV_BORDER.low}`,
                            padding: "1px 6px",
                            borderRadius: 3,
                          }}
                        >
                          {finding.severity}
                        </span>
                      ))}
                    </div>
                    <div
                      className="rounded-lg"
                      style={{
                        border: "1px solid var(--border-light)",
                        background: "var(--bg)",
                      }}
                    >
                      {viewMode === "comment" ? (
                        isHtmlContent(text) ? (
                          <div
                            className="px-4 py-3 text-sm leading-relaxed text-text-primary select-text cursor-text"
                            style={{ fontFamily: "Georgia, 'Times New Roman', serif", lineHeight: 1.8 }}
                            dangerouslySetInnerHTML={{ __html: text }}
                            onMouseUp={() => captureViewSelection(clause)}
                          />
                        ) : (
                          <p
                            className="px-4 py-3 text-sm leading-relaxed text-text-primary select-text cursor-text whitespace-pre-wrap"
                            style={{ fontFamily: "Georgia, 'Times New Roman', serif", lineHeight: 1.8 }}
                            onMouseUp={() => captureViewSelection(clause)}
                          >
                            {renderHighlighted(text, allHighlights)}
                          </p>
                        )
                      ) : (
                        <RichTextEditor
                          initialText={text}
                          onSave={(html) => handleSaveClause(clause.clause_uid, html)}
                        />
                      )}
                    </div>
                  </div>

                  {/* RIGHT — AI findings */}
                  <div className="space-y-2 min-h-[56px]">
                    {clauseFindings.map(({ finding, index }) => (
                      <SuggestionCard
                        key={finding.finding_id}
                        finding={finding}
                        index={index}
                        expanded={expandedFindingIds.has(finding.finding_id)}
                        onToggle={() => toggleFinding(finding.finding_id)}
                        onAccept={() => handleAccept(finding)}
                        onDismiss={() => handleDismiss(finding.finding_id)}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {clauses.length > 0 && (
            <div className="mt-6 py-4 text-center text-xs text-text-secondary/40 border-t border-border/40">
              End of document · {clauses.length} clause{clauses.length !== 1 ? "s" : ""}
              {ordered.length > 0 && ` · ${ordered.length} finding${ordered.length !== 1 ? "s" : ""}`}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function RichTextEditor({
  initialText,
  onSave,
}: {
  initialText: string;
  onSave: (html: string) => Promise<void>;
}) {
  const editorRef = useRef<HTMLDivElement>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const lastSavedRef = useRef<string>("");

  useEffect(() => {
    if (!editorRef.current) return;
    const html = isHtmlContent(initialText) ? initialText : plainToHtml(initialText);
    editorRef.current.innerHTML = html;
    lastSavedRef.current = html;
  }, [initialText]);

  function execFmt(cmd: string, value?: string) {
    document.execCommand(cmd, false, value ?? undefined);
    editorRef.current?.focus();
  }

  async function handleBlur() {
    const html = editorRef.current?.innerHTML ?? "";
    if (html === lastSavedRef.current) return;
    setSaving(true);
    try {
      await onSave(html);
      lastSavedRef.current = html;
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  const toolbarBtn = (label: string, title: string, onClick: () => void, extraStyle?: React.CSSProperties) => (
    <button
      key={label}
      onMouseDown={(e) => { e.preventDefault(); onClick(); }}
      title={title}
      style={{
        padding: "2px 8px",
        fontSize: 12,
        border: "1px solid var(--border)",
        borderRadius: 4,
        background: "transparent",
        color: "var(--text)",
        cursor: "pointer",
        lineHeight: 1.6,
        ...extraStyle,
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ padding: "10px 16px 12px" }}>
      {/* Formatting toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 3,
          marginBottom: 8,
          padding: "4px 6px",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 5,
          flexWrap: "wrap",
        }}
      >
        {toolbarBtn("B", "Bold", () => execFmt("bold"), { fontWeight: 700 })}
        {toolbarBtn("I", "Italic", () => execFmt("italic"), { fontStyle: "italic" })}
        {toolbarBtn("U", "Underline", () => execFmt("underline"), { textDecoration: "underline" })}
        <div style={{ width: 1, height: 16, background: "var(--border)", margin: "0 3px" }} />
        {toolbarBtn("A−", "Smaller text", () => execFmt("fontSize", "1"), { fontSize: 10 })}
        {toolbarBtn("A", "Normal text", () => execFmt("fontSize", "3"), { fontSize: 12 })}
        {toolbarBtn("A+", "Larger text", () => execFmt("fontSize", "5"), { fontSize: 15 })}
      </div>

      {/* Editable document body */}
      <div
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        onBlur={handleBlur}
        style={{
          minHeight: "5rem",
          outline: "none",
          fontSize: 14,
          lineHeight: 1.8,
          color: "var(--text)",
          fontFamily: "Georgia, 'Times New Roman', serif",
          wordBreak: "break-word",
        }}
      />

      {(saving || saved) && (
        <div style={{ textAlign: "right", fontSize: 10, color: "var(--text-3)", marginTop: 4 }}>
          {saving ? "Saving…" : "Saved ✓"}
        </div>
      )}
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
  const color = SEV_COLOR[finding.severity] ?? SEV_COLOR.low;
  const bg = SEV_BG[finding.severity] ?? SEV_BG.low;
  const border = SEV_BORDER[finding.severity] ?? SEV_BORDER.low;
  const replacement = finding.recommended_change?.trim();

  return (
    <div className="rounded-lg p-3" style={{ background: bg, border: `1px solid ${border}` }}>
      <button onClick={onToggle} className="w-full text-left">
        <div className="mb-1.5 flex items-center gap-1.5">
          <span
            className="w-5 h-5 rounded-full text-white text-[9px] font-bold flex items-center justify-center flex-shrink-0"
            style={{ background: color }}
          >
            {index}
          </span>
          <span
            className="text-[10px] font-semibold uppercase tracking-widest capitalize"
            style={{ color }}
          >
            {finding.severity}
          </span>
        </div>
        <p className="line-clamp-3 text-xs leading-snug text-text-primary">{finding.description}</p>
      </button>

      {expanded && (
        <div className="mt-3 space-y-2 border-t border-border/50 pt-3">
          {finding.recommendation_detail && (
            <p className="text-[11px] leading-relaxed text-text-secondary">
              {finding.recommendation_detail}
            </p>
          )}
          {replacement ? (
            <div
              className="rounded border p-2"
              style={{ borderColor: `${color}25`, background: `${color}0a` }}
            >
              <p
                className="mb-1 text-[10px] font-semibold uppercase tracking-widest"
                style={{ color }}
              >
                Replace with
              </p>
              <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-text-primary">
                {replacement}
              </p>
            </div>
          ) : (
            <p className="text-[11px] text-risk-high">No concrete replacement text was supplied.</p>
          )}
          <div className="flex gap-1.5">
            <button
              onClick={onAccept}
              disabled={!replacement}
              className="flex items-center gap-1 rounded border border-risk-low/30 bg-risk-low/5 px-2 py-1 text-[10px] font-semibold text-risk-low transition-colors hover:bg-risk-low/15 disabled:opacity-40"
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
  onDelete,
}: {
  annotation: DocumentAnnotation;
  num?: number;
  onDelete: () => void;
}) {
  return (
    <div
      className="rounded-lg p-3"
      style={{ background: COMMENT_BG, border: `1px solid ${COMMENT_BORDER}` }}
    >
      <div className="mb-1.5 flex items-center gap-2">
        {num != null && (
          <span
            className="w-4 h-4 rounded-full text-white text-[9px] font-bold flex items-center justify-center flex-shrink-0"
            style={{ background: COMMENT_COLOR }}
          >
            {num}
          </span>
        )}
        <MessageSquare className="h-3.5 w-3.5" style={{ color: COMMENT_COLOR }} />
        <span
          className="text-[10px] font-semibold uppercase tracking-widest"
          style={{ color: COMMENT_COLOR }}
        >
          {annotation.author_name ?? "Comment"}
        </span>
        <button
          onClick={onDelete}
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
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-primary">
        {annotation.body}
      </p>
    </div>
  );
}
