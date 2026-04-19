import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  FileText,
  GitBranch,
  Plus,
  Clock,
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Loader2,
  Eye,
  X,
  Upload,
} from "lucide-react";
import { getContract } from "@/lib/api";
import type { ContractDetail as ContractDetailType, ContractVersion } from "@/types";
import { cn } from "@/lib/utils";

// ── Helpers ──────────────────────────────────────────────────────────────────

const riskIcon = (risk: string | null, cls = "h-3.5 w-3.5") => {
  if (risk === "high" || risk === "critical") return <ShieldAlert className={cn(cls, "text-risk-high")} />;
  if (risk === "medium") return <AlertTriangle className={cn(cls, "text-risk-medium")} />;
  if (risk === "low") return <ShieldCheck className={cn(cls, "text-risk-low")} />;
  return null;
};

const riskLabel = (risk: string | null) => {
  if (!risk) return null;
  const map: Record<string, string> = { low: "Low", medium: "Medium", high: "High", critical: "High" };
  return map[risk] ?? risk;
};

const riskColor = (risk: string | null) => {
  if (risk === "high" || risk === "critical") return "text-risk-high";
  if (risk === "medium") return "text-risk-medium";
  if (risk === "low") return "text-risk-low";
  return "text-text-secondary/40";
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function stateLabel(state: string | null): { text: string; color: string } {
  if (!state) return { text: "No analysis", color: "text-text-secondary/40" };
  const map: Record<string, { text: string; color: string }> = {
    finalized: { text: "Finalized", color: "text-risk-low" },
    awaiting_human_review: { text: "Awaiting Review", color: "text-accent" },
    under_review: { text: "Under Review", color: "text-risk-medium" },
    processing: { text: "Processing", color: "text-accent" },
    pending: { text: "Queued", color: "text-text-secondary/60" },
    failed: { text: "Failed", color: "text-risk-high" },
    blocked: { text: "Blocked", color: "text-risk-high" },
  };
  return map[state] ?? { text: state, color: "text-text-secondary/60" };
}

/** Parse "v2" → {main: 2, branch: null}, "v1a" → {main: 1, branch: "a"} */
function parseLabel(label: string): { main: number; branch: string | null } {
  const m = label.match(/^v(\d+)([a-z]*)$/);
  if (!m) return { main: 0, branch: null };
  return { main: parseInt(m[1]), branch: m[2] || null };
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface VersionGroup {
  mainVersion: number;
  main: ContractVersion | null;
  branches: ContractVersion[];
}

type AddMode =
  | null
  | { type: "version" }
  | { type: "branch"; mainVersion: number; parentLabel: string };

interface ContractDetailProps {
  contractId: number;
  onBack: () => void;
  onViewRun: (runId: string) => void;
  onAddVersion: (contractId: number, file: File, opts?: { branchFrom?: number }) => void;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function VersionRow({
  version,
  isMain,
  isLast,
  onView,
  onBranch,
}: {
  version: ContractVersion;
  isMain: boolean;
  isLast: boolean;
  onView: () => void;
  onBranch?: () => void;
}) {
  const status = stateLabel(version.run_state);
  const canView = !!version.run_id && !!version.run_state;

  return (
    <div className="flex items-stretch gap-0 group">
      {/* Timeline column */}
      <div className="flex flex-col items-center shrink-0 w-10">
        {/* Dot */}
        <div
          className={cn(
            "mt-3 rounded-full border-2 shrink-0 z-10 transition-colors",
            isMain
              ? "h-4 w-4 border-accent bg-background group-hover:bg-accent/10"
              : "h-2.5 w-2.5 border-border bg-surface mt-[18px]"
          )}
        />
        {/* Vertical line below dot */}
        {!isLast && (
          <div className="flex-1 w-px bg-border/60 mt-1" />
        )}
      </div>

      {/* Content */}
      <div
        className={cn(
          "flex-1 flex items-center justify-between gap-4 pb-6 min-w-0",
          isMain ? "pt-1.5" : "pt-[14px]"
        )}
      >
        {/* Left: badge + file info */}
        <div className="flex items-center gap-3 min-w-0">
          <span
            className={cn(
              "font-mono font-bold shrink-0 rounded px-2 py-0.5",
              isMain
                ? "text-sm bg-accent/10 text-accent"
                : "text-xs bg-border/40 text-text-secondary"
            )}
          >
            {version.label}
          </span>
          {version.branch_name && (
            <span className="text-xs text-text-secondary/60 flex items-center gap-1 shrink-0">
              <GitBranch className="h-3 w-3" />
              {version.branch_name}
            </span>
          )}
          <div className="min-w-0">
            <p className="text-sm text-text-primary truncate">
              {version.filename ?? "—"}
            </p>
          </div>
        </div>

        {/* Right: status + date + actions */}
        <div className="flex items-center gap-5 shrink-0">
          {/* Risk / state */}
          <div className="flex items-center gap-1.5">
            {version.risk_level ? (
              <>
                {riskIcon(version.risk_level)}
                <span className={cn("text-xs font-medium", riskColor(version.risk_level))}>
                  {riskLabel(version.risk_level)}
                </span>
              </>
            ) : (
              <span className={cn("text-xs font-medium", status.color)}>
                {status.text}
              </span>
            )}
          </div>

          {/* Date */}
          <div className="flex items-center gap-1 text-xs text-text-secondary/50 w-20">
            <Clock className="h-3 w-3 shrink-0" />
            <span>{timeAgo(version.created_at)}</span>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            {canView && (
              <button
                onClick={onView}
                className="flex items-center gap-1.5 text-xs font-medium text-accent hover:text-accent-hover transition-colors cursor-pointer"
              >
                <Eye className="h-3.5 w-3.5" />
                View
              </button>
            )}
            {isMain && onBranch && (
              <button
                onClick={onBranch}
                className="flex items-center gap-1.5 text-xs font-medium text-text-secondary/50 hover:text-text-primary transition-colors cursor-pointer"
              >
                <GitBranch className="h-3.5 w-3.5" />
                Branch
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function InlineUploadForm({
  mode,
  onSubmit,
  onCancel,
}: {
  mode: AddMode;
  onSubmit: (file: File) => void;
  onCancel: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handlePick = () => fileInputRef.current?.click();

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="ml-10 mb-6 rounded-xl border border-border bg-surface p-5"
    >
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm font-semibold text-text-primary">
          {mode?.type === "branch"
            ? `New branch from ${mode.parentLabel}`
            : "Add new version"}
        </p>
        <button onClick={onCancel} className="text-text-secondary/50 hover:text-text-primary transition-colors cursor-pointer">
          <X className="h-4 w-4" />
        </button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        onChange={handleChange}
        className="hidden"
      />

      {!file ? (
        <button
          onClick={handlePick}
          className="w-full flex items-center justify-center gap-2 rounded-lg border border-dashed border-border hover:border-accent/50 hover:bg-accent/5 transition-all py-6 text-sm text-text-secondary cursor-pointer"
        >
          <Upload className="h-4 w-4" />
          Choose PDF file
        </button>
      ) : (
        <div className="flex items-center gap-3 rounded-lg border border-border bg-background px-4 py-3">
          <FileText className="h-4 w-4 text-text-secondary shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-text-primary truncate">{file.name}</p>
            <p className="text-xs text-text-secondary">{(file.size / (1024 * 1024)).toFixed(1)} MB</p>
          </div>
          <button
            onClick={() => setFile(null)}
            className="text-text-secondary/50 hover:text-text-primary transition-colors cursor-pointer"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <div className="flex items-center justify-end gap-3 mt-4">
        <button
          onClick={onCancel}
          className="text-sm font-medium text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
        >
          Cancel
        </button>
        <button
          onClick={() => file && onSubmit(file)}
          disabled={!file}
          className={cn(
            "flex items-center gap-2 rounded-xl px-5 py-2 text-sm font-semibold transition-colors",
            file
              ? "bg-accent text-white hover:bg-accent-hover cursor-pointer"
              : "bg-border/50 text-text-secondary cursor-not-allowed"
          )}
        >
          Upload & Analyze
        </button>
      </div>
    </motion.div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function ContractDetail({
  contractId,
  onBack,
  onViewRun,
  onAddVersion,
}: ContractDetailProps) {
  const [detail, setDetail] = useState<ContractDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [addMode, setAddMode] = useState<AddMode>(null);

  const load = useCallback(() => {
    setLoading(true);
    getContract(contractId)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [contractId]);

  useEffect(() => { load(); }, [load]);

  const versionTree = useMemo<VersionGroup[]>(() => {
    if (!detail) return [];
    const tree = new Map<number, VersionGroup>();
    for (const v of detail.versions) {
      const { main, branch } = parseLabel(v.label);
      if (!tree.has(main)) tree.set(main, { mainVersion: main, main: null, branches: [] });
      if (!branch) {
        tree.get(main)!.main = v;
      } else {
        tree.get(main)!.branches.push(v);
      }
    }
    return Array.from(tree.values()).sort((a, b) => a.mainVersion - b.mainVersion);
  }, [detail]);

  const handleUpload = (file: File) => {
    if (!detail) return;
    const opts =
      addMode?.type === "branch" ? { branchFrom: addMode.mainVersion } : undefined;
    setAddMode(null);
    onAddVersion(detail.id, file, opts);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.4 }}
      className="space-y-12"
    >
      {/* Back link */}
      <button
        onClick={onBack}
        className="flex items-center gap-2 text-sm font-medium text-text-secondary hover:text-text-primary transition-colors cursor-pointer -ml-1"
      >
        <ArrowLeft className="h-4 w-4" />
        All Contracts
      </button>

      {/* Header */}
      {loading ? (
        <div className="h-14 flex items-center">
          <Loader2 className="h-5 w-5 animate-spin text-text-secondary/40" />
        </div>
      ) : detail ? (
        <div className="flex items-end justify-between">
          <div>
            <h1 className="font-serif text-4xl lg:text-5xl font-bold tracking-tight text-text-primary">
              {detail.name}
            </h1>
            <p className="mt-3 text-sm text-text-secondary">
              Created {timeAgo(detail.created_at)} · {detail.versions.length} version{detail.versions.length !== 1 ? "s" : ""}
              <span className="ml-3 font-mono text-[11px] text-text-secondary/40">#{detail.id}</span>
            </p>
          </div>
          <button
            onClick={() => setAddMode({ type: "version" })}
            className="flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-accent-hover transition-colors cursor-pointer"
          >
            <Plus className="h-4 w-4" />
            Add Version
          </button>
        </div>
      ) : null}

      {/* Version tree */}
      {!loading && detail && (
        <div>
          {/* Add version form at top */}
          <AnimatePresence>
            {addMode?.type === "version" && (
              <InlineUploadForm
                mode={addMode}
                onSubmit={handleUpload}
                onCancel={() => setAddMode(null)}
              />
            )}
          </AnimatePresence>

          {versionTree.length === 0 ? (
            <div className="py-16 text-center">
              <p className="text-text-secondary text-sm">No versions yet.</p>
            </div>
          ) : (
            <div>
              {versionTree.map(({ mainVersion, main, branches }, groupIdx) => {
                const isLastGroup = groupIdx === versionTree.length - 1;

                return (
                  <div key={mainVersion}>
                    {/* Main version row */}
                    {main && (
                      <>
                        <VersionRow
                          version={main}
                          isMain
                          isLast={isLastGroup && branches.length === 0}
                          onView={() => main.run_id && onViewRun(main.run_id)}
                          onBranch={() =>
                            setAddMode({
                              type: "branch",
                              mainVersion,
                              parentLabel: main.label,
                            })
                          }
                        />

                        {/* Inline branch form */}
                        <AnimatePresence>
                          {addMode?.type === "branch" && addMode.mainVersion === mainVersion && (
                            <InlineUploadForm
                              mode={addMode}
                              onSubmit={handleUpload}
                              onCancel={() => setAddMode(null)}
                            />
                          )}
                        </AnimatePresence>
                      </>
                    )}

                    {/* Branch rows */}
                    {branches.map((branch, bi) => {
                      const isLastBranch = bi === branches.length - 1 && isLastGroup;
                      return (
                        <div key={branch.id} className="pl-6">
                          <VersionRow
                            version={branch}
                            isMain={false}
                            isLast={isLastBranch}
                            onView={() => branch.run_id && onViewRun(branch.run_id)}
                          />
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </motion.div>
  );
}
