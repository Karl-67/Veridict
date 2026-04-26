import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Loader2, RefreshCw, Trash2, Upload, X } from "lucide-react";
import {
  deleteRagDocument,
  getRagIngestionStatus,
  listRagDocuments,
  uploadRagDocument,
} from "@/lib/api";
import type { RagDocType, RagDocumentResponse, RagIngestionStatus } from "@/types";

const DOC_TYPES: RagDocType[] = ["policy", "reference_contract", "playbook"];

function StatusPill({ state }: { state: string }) {
  const color =
    state === "done" || state === "active"
      ? "text-risk-low border-risk-low/30 bg-risk-low/10"
      : state === "failed"
        ? "text-risk-high border-risk-high/30 bg-risk-high/10"
        : "text-text-secondary border-border bg-surface";
  return (
    <span className={`rounded border px-2 py-0.5 text-[10px] font-bold uppercase ${color}`}>
      {state}
    </span>
  );
}

function ShortId({ id }: { id: string }) {
  return (
    <span title={id} className="font-mono text-[10px] text-text-secondary/50 select-all">
      {id.slice(0, 8)}…
    </span>
  );
}

export default function RagDocumentPanel() {
  const [documents, setDocuments] = useState<RagDocumentResponse[]>([]);
  const [jobs, setJobs] = useState<RagIngestionStatus[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState<RagDocType>("policy");
  const [policyFamilyId, setPolicyFamilyId] = useState("default");
  const [jurisdiction, setJurisdiction] = useState("US");
  const [label, setLabel] = useState("");
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    setDocuments(await listRagDocuments());
  }, []);

  useEffect(() => {
    reload().catch((err) => setError(err.message));
  }, [reload]);

  useEffect(() => {
    if (jobs.length === 0) return;
    const id = window.setInterval(async () => {
      const next = await Promise.all(jobs.map((job) => getRagIngestionStatus(job.job_id)));
      setJobs(next);
      if (next.every((job) => job.state === "done" || job.state === "failed")) reload();
    }, 1500);
    return () => window.clearInterval(id);
  }, [jobs, reload]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped && dropped.type === "application/pdf") setFile(dropped);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const result = await uploadRagDocument({
        file,
        doc_type: docType,
        policy_family_id: policyFamilyId,
        jurisdiction,
        version_label: label || undefined,
      });
      setJobs((current) => [
        { job_id: result.job_id, document_id: result.document_id, state: "pending", chunks_processed: 0 },
        ...current,
      ]);
      setFile(null);
      setLabel("");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const remove = async (documentId: string) => {
    if (!confirm("Delete this RAG document and all its chunks? This cannot be undone.")) return;
    try {
      await deleteRagDocument(documentId);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="rounded-xl border border-border bg-surface p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Upload className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold text-text-primary">Upload RAG Document</h3>
        </div>

        {/* Drop zone */}
        <div
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={`relative flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-8 cursor-pointer transition-colors ${
            dragging
              ? "border-accent bg-accent/5"
              : file
                ? "border-risk-low/50 bg-risk-low/5"
                : "border-border hover:border-accent/50 hover:bg-surface/80"
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          {file ? (
            <>
              <FileText className="h-6 w-6 text-risk-low" />
              <div className="text-center">
                <p className="text-sm font-medium text-text-primary">{file.name}</p>
                <p className="text-xs text-text-secondary/60">{(file.size / 1024).toFixed(0)} KB</p>
              </div>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setFile(null); }}
                className="absolute top-2 right-2 text-text-secondary/40 hover:text-risk-high transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <Upload className="h-6 w-6 text-text-secondary/40" />
              <p className="text-sm text-text-secondary">
                <span className="font-medium text-accent">Click to browse</span> or drag & drop a PDF
              </p>
            </>
          )}
        </div>

        {/* Metadata fields */}
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Label (e.g. GDPR Policy v2.1)"
            className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary/40 focus:border-accent focus:outline-none"
          />
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value as RagDocType)}
            className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
          >
            {DOC_TYPES.map((type) => (
              <option key={type} value={type}>{type.replace("_", " ")}</option>
            ))}
          </select>
          <input
            value={policyFamilyId}
            onChange={(e) => setPolicyFamilyId(e.target.value)}
            placeholder="Policy family"
            className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary/40 focus:border-accent focus:outline-none"
          />
          <input
            value={jurisdiction}
            onChange={(e) => setJurisdiction(e.target.value)}
            placeholder="Jurisdiction"
            className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary/40 focus:border-accent focus:outline-none"
          />
        </div>

        {error && <p className="text-xs text-risk-high">{error}</p>}

        <button
          type="submit"
          disabled={!file || loading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          Upload
        </button>
      </form>

      {/* In-progress jobs */}
      {jobs.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-secondary">Processing</p>
          {jobs.map((job) => (
            <div key={job.job_id} className="flex items-center justify-between rounded-lg border border-border px-4 py-3 text-sm">
              <div>
                <p className="text-xs font-medium text-text-primary">Job</p>
                <ShortId id={job.job_id} />
              </div>
              <StatusPill state={job.state} />
            </div>
          ))}
        </div>
      )}

      {/* Document list */}
      <div className="rounded-xl border border-border overflow-hidden">
        <div className="flex items-center justify-between border-b border-border bg-surface/50 px-4 py-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
            Documents ({documents.length})
          </span>
          <button onClick={reload} className="text-text-secondary hover:text-text-primary transition-colors">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>

        {documents.map((doc) => {
          const name = doc.original_filename ?? doc.source_path.split(/[\\/]/).pop() ?? doc.document_id;
          const displayLabel = doc.label || doc.version;
          return (
            <div
              key={doc.document_id}
              className="flex items-center justify-between gap-4 border-b border-border/50 px-4 py-3 last:border-0"
            >
              <div className="flex min-w-0 items-center gap-3">
                <FileText className="h-4 w-4 shrink-0 text-accent" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-text-primary" title={name}>{name}</p>
                  <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                    <ShortId id={doc.document_id} />
                    <span className="text-text-secondary/30">·</span>
                    <span className="text-xs text-text-secondary">{doc.doc_type.replace("_", " ")}</span>
                    {displayLabel && displayLabel !== "pending" && (
                      <>
                        <span className="text-text-secondary/30">·</span>
                        <span className="text-xs font-medium text-accent/80">{displayLabel}</span>
                      </>
                    )}
                    <span className="text-text-secondary/30">·</span>
                    <span className="text-xs text-text-secondary/60">{doc.chunk_count} chunks</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <StatusPill state={doc.active ? "active" : "pending"} />
                <button
                  onClick={() => remove(doc.document_id)}
                  title="Delete document"
                  className="text-text-secondary/40 hover:text-risk-high transition-colors cursor-pointer"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          );
        })}

        {documents.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-text-secondary/60">No RAG documents yet.</p>
        )}
      </div>
    </div>
  );
}
