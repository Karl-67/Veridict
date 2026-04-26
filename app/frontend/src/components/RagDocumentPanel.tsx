import { useCallback, useEffect, useState } from "react";
import { FileText, Loader2, RefreshCw, Trash2, Upload } from "lucide-react";
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
  return <span className={`rounded border px-2 py-0.5 text-[10px] font-bold uppercase ${color}`}>{state}</span>;
}

export default function RagDocumentPanel() {
  const [documents, setDocuments] = useState<RagDocumentResponse[]>([]);
  const [jobs, setJobs] = useState<RagIngestionStatus[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState<RagDocType>("policy");
  const [policyFamilyId, setPolicyFamilyId] = useState("default");
  const [jurisdiction, setJurisdiction] = useState("US");
  const [versionLabel, setVersionLabel] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        version_label: versionLabel || undefined,
      });
      setJobs((current) => [
        { job_id: result.job_id, document_id: result.document_id, state: "pending", chunks_processed: 0 },
        ...current,
      ]);
      setFile(null);
      setVersionLabel("");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const remove = async (documentId: string) => {
    await deleteRagDocument(documentId);
    await reload();
  };

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="rounded-xl border border-border bg-surface p-5">
        <div className="mb-4 flex items-center gap-2">
          <Upload className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold text-text-primary">RAG Documents</h3>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <input type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm text-text-secondary" />
          <select value={docType} onChange={(e) => setDocType(e.target.value as RagDocType)} className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary">
            {DOC_TYPES.map((type) => <option key={type} value={type}>{type.replace("_", " ")}</option>)}
          </select>
          <input value={policyFamilyId} onChange={(e) => setPolicyFamilyId(e.target.value)} placeholder="Policy family" className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary" />
          <input value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} placeholder="Jurisdiction" className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary" />
          <input value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} placeholder="Version label" className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary" />
        </div>
        {error && <p className="mt-3 text-xs text-risk-high">{error}</p>}
        <button type="submit" disabled={!file || loading} className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />} Upload
        </button>
      </form>

      {jobs.length > 0 && (
        <div className="space-y-2">
          {jobs.map((job) => (
            <div key={job.job_id} className="flex items-center justify-between rounded-lg border border-border px-4 py-3 text-sm">
              <span className="font-mono text-xs text-text-secondary">{job.job_id}</span>
              <StatusPill state={job.state} />
            </div>
          ))}
        </div>
      )}

      <div className="rounded-xl border border-border overflow-hidden">
        <div className="flex items-center justify-between border-b border-border bg-surface/50 px-4 py-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-secondary">Documents</span>
          <button onClick={reload} className="text-text-secondary hover:text-text-primary"><RefreshCw className="h-3.5 w-3.5" /></button>
        </div>
        {documents.map((document) => (
          <div key={document.document_id} className="flex items-center justify-between gap-4 border-b border-border/50 px-4 py-3 last:border-0">
            <div className="flex min-w-0 items-center gap-3">
              <FileText className="h-4 w-4 shrink-0 text-accent" />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-text-primary">{document.source_path.split(/[\\/]/).pop()}</p>
                <p className="text-xs text-text-secondary">{document.doc_type.replace("_", " ")} · {document.version} · {document.chunk_count} chunks</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <StatusPill state={document.active ? "active" : "pending"} />
              <button onClick={() => remove(document.document_id)} className="text-text-secondary/50 hover:text-risk-high"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          </div>
        ))}
        {documents.length === 0 && <p className="px-4 py-8 text-center text-sm text-text-secondary/60">No RAG documents yet.</p>}
      </div>
    </div>
  );
}
