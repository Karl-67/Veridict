import { useState, useEffect, useRef, useCallback } from "react";
import { Download, Users, Bold, Italic, Underline, Loader2 } from "lucide-react";
import { getEditorContent, saveEditorContent } from "@/lib/api";

interface ContractEditorProps {
  runId: string;
  filename?: string;
  currentUserName?: string;
}

function timeAgoStr(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// Isolated content-editable body — remounts when key changes (poll update)
function EditorBody({
  initHtml,
  onInput,
  editorRef,
}: {
  initHtml: string;
  onInput: () => void;
  editorRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div
      ref={editorRef}
      contentEditable
      suppressContentEditableWarning
      spellCheck
      onInput={onInput}
      // dangerouslySetInnerHTML sets initial DOM; React won't touch children after mount
      dangerouslySetInnerHTML={{ __html: initHtml }}
      className="min-h-[900px] rounded-xl border border-indigo-200 bg-white px-14 py-14 shadow-sm text-[13.5px] leading-[1.9] text-gray-800 font-serif outline-none cursor-text ring-1 ring-indigo-300/40"
    />
  );
}

export default function ContractEditor({ runId, filename = "contract", currentUserName }: ContractEditorProps) {
  const [initHtml, setInitHtml] = useState<string | null>(null);
  const [editorKey, setEditorKey] = useState(0);
  const [lastEditedBy, setLastEditedBy] = useState<string | null>(null);
  const [lastEditedAt, setLastEditedAt] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const versionRef = useRef(0);
  const editingRef = useRef(false);

  useEffect(() => { versionRef.current = version; }, [version]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getEditorContent(runId)
      .then((data) => {
        if (!active) return;
        setInitHtml(data.content || "<p>No contract text available yet.</p>");
        setLastEditedBy(data.last_edited_by ?? null);
        setLastEditedAt(data.last_edited_at ?? null);
        setVersion(data.version ?? 0);
      })
      .catch(() => setError("Could not load editor content."))
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [runId]);

  // Poll for other users' changes
  useEffect(() => {
    const id = setInterval(async () => {
      if (editingRef.current) return;
      try {
        const data = await getEditorContent(runId);
        if ((data.version ?? 0) > versionRef.current) {
          setInitHtml(data.content || "");
          setLastEditedBy(data.last_edited_by ?? null);
          setLastEditedAt(data.last_edited_at ?? null);
          setVersion(data.version ?? 0);
          setEditorKey((k) => k + 1); // remount EditorBody with new content
        }
      } catch {}
    }, 8000);
    return () => clearInterval(id);
  }, [runId]);

  const scheduleSave = useCallback(() => {
    editingRef.current = true;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      const html = editorRef.current?.innerHTML ?? "";
      setSaving(true);
      try {
        const data = await saveEditorContent(runId, html, currentUserName);
        setLastEditedBy(data.last_edited_by);
        setLastEditedAt(data.last_edited_at);
        setVersion(data.version);
      } catch {}
      finally {
        setSaving(false);
        editingRef.current = false;
      }
    }, 1500);
  }, [runId, currentUserName]);

  const execCmd = useCallback((cmd: string) => {
    document.execCommand(cmd, false);
    editorRef.current?.focus();
    scheduleSave();
  }, [scheduleSave]);

  const markSelection = useCallback((tag: "ins" | "del") => {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return;
    const range = sel.getRangeAt(0);
    const el = document.createElement(tag);
    el.setAttribute("data-user", currentUserName || "You");
    el.title = `${tag === "ins" ? "Added" : "Removed"} by ${currentUserName || "You"}`;
    if (tag === "ins") {
      el.style.cssText = "background:rgba(34,197,94,0.18);text-decoration:none;border-bottom:2px solid rgb(22,163,74);";
    } else {
      el.style.cssText = "background:rgba(239,68,68,0.1);color:rgb(220,38,38);text-decoration:line-through;";
    }
    try { range.surroundContents(el); } catch { return; }
    sel.removeAllRanges();
    scheduleSave();
  }, [currentUserName, scheduleSave]);

  const handleDownload = useCallback(() => {
    const clone = (editorRef.current?.cloneNode(true) ?? document.createElement("div")) as HTMLElement;
    clone.querySelectorAll("del, [data-op='delete']").forEach((el) => el.remove());
    clone.querySelectorAll("ins, [data-op='insert']").forEach((el) => {
      while (el.firstChild) el.parentNode?.insertBefore(el.firstChild, el);
      el.remove();
    });
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${filename.replace(/\.pdf$/, "")}</title><style>body{font-family:Georgia,serif;font-size:12pt;line-height:1.85;margin:2.5cm 3cm;color:#111}p{margin-bottom:.9em}</style></head><body>${clone.innerHTML}</body></html>`;
    const a = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(new Blob([html], { type: "text/html" })),
      download: filename.replace(/\.pdf$/, "") + "_edited.html",
    });
    a.click();
    URL.revokeObjectURL(a.href);
  }, [filename]);

  if (loading) return (
    <div className="flex items-center justify-center gap-2 py-20 text-sm text-text-secondary/50">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading contract text…
    </div>
  );
  if (error) return <div className="py-16 text-center text-sm text-risk-high/70">{error}</div>;
  if (initHtml === null) return null;

  return (
    <div className="flex flex-col gap-4">
      {/* Info banner */}
      <div className="flex items-center gap-2 rounded-lg border border-indigo-200/60 bg-indigo-50/40 px-3 py-2 text-[11px] text-indigo-700/70">
        You are editing a text copy of the contract. Changes are auto-saved and shared with your team. Click <strong>Download</strong> to export the final clean version.
      </div>
      {/* Formatting toolbar */}
      <div className="flex items-center gap-2 flex-wrap rounded-lg border border-border bg-surface px-3 py-2 shadow-sm">
        <button onMouseDown={(e) => { e.preventDefault(); execCmd("bold"); }} className="rounded px-2 py-1 hover:bg-drop-zone/30 transition-colors" title="Bold"><Bold className="h-3.5 w-3.5" /></button>
        <button onMouseDown={(e) => { e.preventDefault(); execCmd("italic"); }} className="rounded px-2 py-1 hover:bg-drop-zone/30 transition-colors" title="Italic"><Italic className="h-3.5 w-3.5" /></button>
        <button onMouseDown={(e) => { e.preventDefault(); execCmd("underline"); }} className="rounded px-2 py-1 hover:bg-drop-zone/30 transition-colors" title="Underline"><Underline className="h-3.5 w-3.5" /></button>
        <div className="h-4 w-px bg-border/60 mx-1" />
        <button
          onMouseDown={(e) => { e.preventDefault(); markSelection("ins"); }}
          className="rounded px-2 py-1 text-[11px] font-semibold text-risk-low border border-risk-low/30 hover:bg-drop-zone/30 transition-colors"
          title="Mark selected text as added"
        >+ Add</button>
        <button
          onMouseDown={(e) => { e.preventDefault(); markSelection("del"); }}
          className="rounded px-2 py-1 text-[11px] font-semibold text-risk-high border border-risk-high/30 hover:bg-drop-zone/30 transition-colors"
          title="Mark selected text as deleted"
        >− Delete</button>
        <div className="ml-auto flex items-center gap-3">
          {saving && <span className="text-[11px] text-text-secondary/50">Saving…</span>}
          {lastEditedBy && !saving && (
            <span className="flex items-center gap-1.5 text-[11px] text-text-secondary/50">
              <Users className="h-3 w-3 shrink-0" />
              {lastEditedBy}{lastEditedAt ? ` · ${timeAgoStr(lastEditedAt)}` : ""}
            </span>
          )}
          <button onClick={handleDownload} className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium hover:bg-drop-zone/30 transition-colors">
            <Download className="h-3.5 w-3.5" /> Download
          </button>
        </div>
      </div>

      {/* Change legend */}
      <div className="flex items-center gap-4 px-1 text-[11px] text-text-secondary/50">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-risk-low/30 border border-risk-low/50" />Added</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-risk-high/20 border border-risk-high/30" />Deleted</span>
        <span className="text-text-secondary/35">Select text then click Add or Delete to mark changes</span>
      </div>

      <EditorBody key={editorKey} initHtml={initHtml} onInput={scheduleSave} editorRef={editorRef} />
    </div>
  );
}
