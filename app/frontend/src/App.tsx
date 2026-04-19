import { useState, useCallback, useEffect, useRef } from "react";
import { useAuth } from "@/context/AuthContext";
import AuthPage from "@/components/AuthPage";
import { motion, AnimatePresence } from "framer-motion";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import UploadForm from "@/components/UploadForm";
import RecentActivity from "@/components/RecentActivity";
import QuickTip from "@/components/QuickTip";
import PipelineTracker from "@/components/PipelineTracker";
import AIEngineInsights from "@/components/AIEngineInsights";
import PipelineMethodology from "@/components/PipelineMethodology";
import VerdictCard from "@/components/VerdictCard";
import AdminPage from "@/components/AdminPage";
import ContractsDashboard from "@/components/ContractsDashboard";
import ContractDetail from "@/components/ContractDetail";
import {
  pollRunUntilDone,
  type PollSignal,
  verdictToReviewResult,
  createContract,
  addContractVersion,
  getRun,
  getRunFindings,
  startRunReview,
  listWorkspaces,
  retryRun,
  submitHumanReview,
} from "@/lib/api";
import type { Workspace } from "@/types";
import HumanReviewPanel from "@/components/HumanReviewPanel";
import { XCircle, RefreshCw, ArrowLeft } from "lucide-react";
import type { FinalVerdict, ReviewResult, RunDetail, ContractSummary } from "@/types";

type AppState =
  | "dashboard"
  | "contract_detail"
  | "new_contract"
  | "processing"
  | "human_review"
  | "verdict"
  | "failed"
  | "admin";

interface FailureInfo {
  stage: string;
  error: string;
  runId?: string;
}

export default function App() {
  const { user } = useAuth();
  const hasInvite = new URLSearchParams(window.location.search).has("invite");
  if (!user || hasInvite) return <AuthPage />;

  return <AppInner />;
}

function AppInner() {
  const [state, setState] = useState<AppState>("dashboard");
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [fileName, setFileName] = useState("");
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [currentRun, setCurrentRun] = useState<RunDetail | null>(null);
  const [failureInfo, setFailureInfo] = useState<FailureInfo | null>(null);

  // Workspace context
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);

  // Contract context
  const [selectedContractId, setSelectedContractId] = useState<number | null>(null);
  const [newContractName, setNewContractName] = useState("");
  const [rawVerdict, setRawVerdict] = useState<FinalVerdict | null>(null);
  const [isAwaitingReview, setIsAwaitingReview] = useState(false);
  const [reviewFindings, setReviewFindings] = useState<import("@/types").Finding[]>([]);
  const pollSignalRef = useRef<PollSignal | null>(null);

  useEffect(() => {
    listWorkspaces().then((ws) => {
      setWorkspaces(ws);
      if (ws.length > 0) setActiveWorkspaceId(ws[0].workspace_id);
    }).catch(console.error);
  }, []);

  // ── Browser history (pushState so Chrome back button works) ──────────────
  useEffect(() => {
    window.history.replaceState({ appState: "dashboard", selectedContractId: null }, "");
    const onPop = (e: PopStateEvent) => {
      const s = e.state as { appState?: AppState; selectedContractId?: number | null } | null;
      // If no state or unrecognised state, fall back to dashboard
      const SAFE_STATES: AppState[] = ["dashboard", "contract_detail", "new_contract", "admin"];
      const target = s?.appState && SAFE_STATES.includes(s.appState) ? s.appState : "dashboard";
      // contract_detail without a contractId is meaningless — fall back to dashboard
      const contractId = target === "contract_detail" ? (s?.selectedContractId ?? null) : null;
      if (target === "contract_detail" && !contractId) {
        setState("dashboard");
        setSelectedContractId(null);
      } else {
        setState(target);
        setSelectedContractId(contractId);
      }
      setResult(null);
      setRawVerdict(null);
      setFileName("");
      setCurrentRun(null);
      setFailureInfo(null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // ── History-aware navigation (only for stable pages, not transient states) ─
  const HISTORY_STATES: AppState[] = ["dashboard", "contract_detail", "new_contract", "admin"];
  const navigate = useCallback((newState: AppState, contractId?: number | null) => {
    if (HISTORY_STATES.includes(newState)) {
      window.history.pushState({ appState: newState, selectedContractId: contractId ?? null }, "");
    }
    setState(newState);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Shared polling logic ─────────────────────────────────────────────────

  const cancelPoll = useCallback(() => {
    if (pollSignalRef.current) pollSignalRef.current.cancelled = true;
  }, []);

  const processRun = useCallback(
    async (runId: string, contractId: number | null) => {
      const signal: PollSignal = { cancelled: false };
      pollSignalRef.current = signal;
      try {
        const run = await pollRunUntilDone(runId, 1500, 30 * 60_000, (r) =>
          setCurrentRun(r), signal
        );
        setCurrentRun(run);

        if (run.state === "awaiting_human_review") {
          setPendingRunId(runId);
          if (run.verdict) {
            setResult(verdictToReviewResult(run.verdict));
            setRawVerdict(run.verdict);
          }
          setState("human_review");
        } else if (run.state === "finalized" && run.verdict) {
          setResult(verdictToReviewResult(run.verdict));
          setRawVerdict(run.verdict);
          setState("verdict");
        } else if (run.state === "failed" || run.state === "blocked") {
          const failedStage = run.stages.find(
            (s) => s.state === "failed" || s.state === "blocked"
          );
          setFailureInfo({
            stage: failedStage?.stage_name ?? "unknown",
            error: failedStage?.error_detail ?? run.blocked_reason ?? "Unknown error",
            runId: run.run_id,
          });
          setState("failed");
        } else if (run.state === "processing" || run.state === "created") {
          // Polling window expired but backend is still running — go back to dashboard
          if (contractId) {
            navigate("contract_detail", contractId);
          } else {
            navigate("dashboard");
          }
        }
      } catch (err) {
        if ((err as DOMException)?.name === "AbortError") return;
        setFailureInfo({ stage: "unknown", error: (err as Error).message });
        setState("failed");
      } finally {
        setIsPending(false);
      }
    },
    [navigate]
  );

  // ── New contract creation ────────────────────────────────────────────────

  const handleNewContractSubmit = useCallback(
    async (file: File) => {
      if (!newContractName.trim() || !activeWorkspaceId) return;
      setIsPending(true);
      setFileName(file.name);
      setCurrentRun(null);
      setFailureInfo(null);
      setState("processing");

      try {
        const contract = await createContract(newContractName.trim(), activeWorkspaceId);
        setSelectedContractId(contract.id);
        const versionResp = await addContractVersion(contract.id, file);
        await processRun(versionResp.run_id, contract.id);
      } catch (err) {
        setFailureInfo({ stage: "unknown", error: (err as Error).message });
        setState("failed");
        setIsPending(false);
      }
    },
    [newContractName, activeWorkspaceId, processRun]
  );

  // ── Add version to existing contract ────────────────────────────────────

  const handleAddVersion = useCallback(
    async (
      contractId: number,
      file: File,
      opts?: { branchFrom?: number }
    ) => {
      setIsPending(true);
      setFileName(file.name);
      setCurrentRun(null);
      setFailureInfo(null);
      setSelectedContractId(contractId);
      setState("processing");

      try {
        const versionResp = await addContractVersion(contractId, file, opts);
        await processRun(versionResp.run_id, contractId);
      } catch (err) {
        setFailureInfo({ stage: "unknown", error: (err as Error).message });
        setState("failed");
        setIsPending(false);
      }
    },
    [processRun]
  );

  // ── View an existing run's verdict ───────────────────────────────────────

  const handleViewRun = useCallback(async (runId: string) => {
    try {
      const run = await getRun(runId);
      setFileName(run.filename ?? "");
      setCurrentRun(run);
      if (run.state === "awaiting_human_review" || run.state === "under_review") {
        setPendingRunId(runId);
        if (run.verdict) {
          setResult(verdictToReviewResult(run.verdict));
          setRawVerdict(run.verdict);
        }
        if (run.state === "under_review") {
          await handleStartReview();
          return;
        }
        setState("human_review");
      } else if (run.state === "finalized" && run.verdict) {
        setResult(verdictToReviewResult(run.verdict));
        setRawVerdict(run.verdict);
        setState("verdict");
      } else if (run.state === "processing" || run.state === "created") {
        setIsPending(true);
        setState("processing");
        await processRun(runId, selectedContractId);
      } else if (run.state === "failed" || run.state === "blocked") {
        const failedStage = run.stages.find((s) => s.state === "failed" || s.state === "blocked");
        setFailureInfo({
          stage: failedStage?.stage_name ?? "unknown",
          error: failedStage?.error_detail ?? run.blocked_reason ?? "Unknown error",
          runId: run.run_id,
        });
        setState("failed");
      }
    } catch (err) {
      console.error("Failed to fetch run:", err);
    }
  }, [processRun, selectedContractId]);

  // ── Human review callbacks ───────────────────────────────────────────────


  const handleStartReview = useCallback(async () => {
    cancelPoll();
    if (!pendingRunId) { setIsAwaitingReview(true); setState("verdict"); return; }
    try {
      await startRunReview(pendingRunId);
    } catch { /* state may already be under_review */ }
    try {
      const findings = await getRunFindings(pendingRunId);
      setReviewFindings(findings);
      if (!result) {
        const risk = findings.some((f) => f.severity === "critical" || f.severity === "high")
          ? "high" : findings.some((f) => f.severity === "medium") ? "medium" : "low";
        setResult({
          risk_level: risk,
          summary: `${findings.length} findings identified.`,
          recommendations: findings.map((f) => f.recommendation).filter(Boolean),
          clause_flags: findings.map((f) => ({
            clause: f.description.split(/[.\n]/)[0]?.slice(0, 80) || f.clause_uid,
            issue: f.recommendation_detail || f.description,
            severity: (f.severity === "critical" ? "high" : f.severity) as "low" | "medium" | "high",
          })),
        });
      }
    } catch { /* proceed */ }
    setIsAwaitingReview(true);
    setState("verdict");
  }, [cancelPoll, result, pendingRunId]);

  const handleApproveVerdict = useCallback(async () => {
    if (!pendingRunId) return;
    await submitHumanReview(pendingRunId, {
      run_action: "approved",
      reviewer_id: "verdict-user",
      finding_actions: [],
    });
    setIsAwaitingReview(false);
    setPendingRunId(null);
    if (selectedContractId) navigate("contract_detail", selectedContractId);
    else navigate("dashboard");
  }, [pendingRunId, selectedContractId, navigate]);

  const handleRejectVerdict = useCallback(async (reason: string) => {
    if (!pendingRunId) return;
    await submitHumanReview(pendingRunId, {
      run_action: "rejected",
      reviewer_id: "verdict-user",
      rejection_reason: reason,
    });
    setIsAwaitingReview(false);
    setPendingRunId(null);
    if (selectedContractId) navigate("contract_detail", selectedContractId);
    else navigate("dashboard");
  }, [pendingRunId, selectedContractId, navigate]);

  const handleRetry = useCallback(async () => {
    if (!failureInfo?.runId) return;
    try {
      await retryRun(failureInfo.runId);
      setFailureInfo(null);
      setCurrentRun(null);
      setIsPending(true);
      setState("processing");
      await processRun(failureInfo.runId, selectedContractId);
    } catch (err) {
      setFailureInfo((prev) => prev ? { ...prev, error: (err as Error).message } : prev);
    }
  }, [failureInfo, processRun, selectedContractId]);

  const handleHumanRejected = useCallback(() => {
    if (selectedContractId) {
      navigate("contract_detail", selectedContractId);
    } else {
      navigate("dashboard");
    }
    setPendingRunId(null);
    setFileName("");
    setCurrentRun(null);
  }, [selectedContractId, navigate]);

  // ── Reset / back navigation ──────────────────────────────────────────────

  const handleReset = useCallback(() => {
    if (selectedContractId) {
      navigate("contract_detail", selectedContractId);
    } else {
      navigate("dashboard");
    }
    setResult(null);
    setRawVerdict(null);
    setFileName("");
    setPendingRunId(null);
    setCurrentRun(null);
    setFailureInfo(null);
  }, [selectedContractId, navigate]);

  const handleBackToDashboard = useCallback(() => {
    navigate("dashboard");
    setSelectedContractId(null);
    setNewContractName("");
  }, [navigate]);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-background transition-colors duration-300 flex flex-col">
      <Header
        activePage={state === "admin" ? "Admin" : "Dashboard"}
        onNavigate={(page) => {
          if (page === "Dashboard" || page === "History") {
            navigate("dashboard");
            setSelectedContractId(null);
            setNewContractName("");
            setResult(null);
            setFileName("");
            setPendingRunId(null);
            setCurrentRun(null);
            setFailureInfo(null);
          }
        }}
        onAdmin={() => navigate("admin")}
      />

      <main className="flex-1 mx-auto w-full max-w-[1440px] px-6 sm:px-10 lg:px-14 py-20">
        <AnimatePresence mode="wait">

          {/* ── DASHBOARD ── */}
          {state === "dashboard" && (
            <motion.div key="dashboard" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }}>
              <ContractsDashboard
                workspaces={workspaces}
                activeWorkspaceId={activeWorkspaceId}
                onWorkspaceChange={setActiveWorkspaceId}
                onNewContract={() => {
                  if (!activeWorkspaceId && workspaces.length > 0) setActiveWorkspaceId(workspaces[0].workspace_id);
                  setSelectedContractId(null);
                  setNewContractName("");
                  navigate("new_contract");
                }}
                onOpenContract={(contract: ContractSummary) => {
                  setSelectedContractId(contract.id);
                  navigate("contract_detail", contract.id);
                }}
              />
            </motion.div>
          )}

          {/* ── CONTRACT DETAIL ── */}
          {state === "contract_detail" && selectedContractId !== null && (
            <motion.div key="contract_detail" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }}>
              <ContractDetail
                contractId={selectedContractId}
                onBack={handleBackToDashboard}
                onViewRun={handleViewRun}
                onAddVersion={handleAddVersion}
              />
            </motion.div>
          )}

          {/* ── NEW CONTRACT ── */}
          {state === "new_contract" && (
            <motion.div
              key="new_contract"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4 }}
              className="space-y-16"
            >
              {/* Back */}
              <button
                onClick={handleBackToDashboard}
                className="flex items-center gap-2 text-sm font-medium text-text-secondary hover:text-text-primary transition-colors cursor-pointer -ml-1"
              >
                <ArrowLeft className="h-4 w-4" />
                All Contracts
              </button>

              <div className="space-y-3">
                <h1 className="font-serif text-4xl lg:text-5xl font-bold tracking-tight text-text-primary">
                  New Contract
                </h1>
                <p className="text-lg text-text-secondary max-w-2xl">
                  Name your contract and upload the first version for analysis.
                </p>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-12 items-start">
                <div className="space-y-6">
                  {/* Contract name */}
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-widest text-text-secondary/60 mb-2">
                      Contract Name
                    </label>
                    <input
                      type="text"
                      value={newContractName}
                      onChange={(e) => setNewContractName(e.target.value)}
                      placeholder="e.g. NDA Agreement, Vendor SLA, Employment Contract"
                      className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-sm text-text-primary placeholder:text-text-secondary/40 focus:border-accent focus:outline-none transition-colors"
                    />
                  </div>
                  {/* Workspace selector */}
                  {workspaces.length > 1 && (
                    <div>
                      <label className="block text-xs font-semibold uppercase tracking-widest text-text-secondary/60 mb-2">
                        Workspace
                      </label>
                      <select
                        value={activeWorkspaceId ?? ""}
                        onChange={(e) => setActiveWorkspaceId(e.target.value)}
                        className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-sm text-text-primary focus:border-accent focus:outline-none transition-colors"
                      >
                        {workspaces.map((ws) => (
                          <option key={ws.workspace_id} value={ws.workspace_id}>{ws.name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  {workspaces.length === 1 && activeWorkspaceId && (
                    <p className="text-xs text-text-secondary/60">
                      Workspace: <span className="font-medium text-text-primary">{workspaces[0].name}</span>
                    </p>
                  )}
                  {workspaces.length === 0 && (
                    <p className="text-xs text-risk-high">You are not a member of any workspace. Ask an admin to add you.</p>
                  )}
                  {/* Upload form */}
                  <UploadForm
                    onSubmit={handleNewContractSubmit}
                    isPending={isPending}
                    disabled={!newContractName.trim() || !activeWorkspaceId}
                  />
                </div>
                <div className="space-y-6">
                  <RecentActivity
                    onViewAll={() => navigate("dashboard")}
                    onOpen={(contract) => {
                      setSelectedContractId(contract.id);
                      navigate("contract_detail", contract.id);
                    }}
                  />
                  <QuickTip />
                </div>
              </div>
            </motion.div>
          )}

          {/* ── PROCESSING ── */}
          {state === "processing" && (
            <motion.div
              key="processing"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4 }}
              className="space-y-16"
            >
              <div className="text-center">
                <h1 className="font-serif text-4xl lg:text-5xl font-bold text-text-primary">
                  Analyzing your contract
                </h1>
                <p className="mt-5 text-lg text-text-secondary max-w-3xl mx-auto">
                  Our Legal Intelligence engine is scanning for risks,
                  inconsistencies, and high-value clauses across your
                  documentation.
                </p>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-[2fr_3fr] gap-14 items-start">
                <AIEngineInsights fileName={fileName} charCount={42852} />
                <div className="space-y-10 pt-2">
                  <PipelineTracker
                    stages={currentRun?.stages ?? []}
                    runState={currentRun?.state ?? null}
                  />
                  <div className="border-t border-border/60 pt-8">
                    <PipelineMethodology />
                  </div>
                </div>
              </div>

              <div className="text-center">
                <div className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-5 py-2.5">
                  <span className="h-2 w-2 rounded-full bg-risk-low animate-pulse" />
                  <span className="text-sm font-medium text-text-primary">
                    AI Engine running at peak performance
                  </span>
                </div>
                <p className="mt-2 text-sm italic text-text-secondary">
                  This can take a few minutes depending on contract length.
                </p>
                <button
                  onClick={() => {
                    cancelPoll();
                    setIsPending(false);
                    if (selectedContractId) navigate("contract_detail", selectedContractId);
                    else navigate("dashboard");
                  }}
                  className="mt-4 text-sm text-text-secondary/50 hover:text-text-secondary transition-colors cursor-pointer underline underline-offset-2"
                >
                  Run in background — go to dashboard
                </button>
              </div>
            </motion.div>
          )}

          {/* ── FAILED ── */}
          {state === "failed" && (
            <motion.div
              key="failed"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4 }}
              className="space-y-12"
            >
              <div className="text-center">
                <h1 className="font-serif text-4xl lg:text-5xl font-bold text-text-primary mb-3">
                  Analysis Failed
                </h1>
                <p className="text-lg text-text-secondary max-w-xl mx-auto">
                  Something went wrong while processing{" "}
                  <span className="italic text-text-primary">{fileName}</span>.
                </p>
              </div>

              <div className="max-w-3xl mx-auto space-y-6">
                <div className="rounded-2xl border border-risk-high/30 bg-risk-high/5 p-6 space-y-4">
                  <div className="flex items-start gap-3">
                    <XCircle className="h-5 w-5 text-risk-high shrink-0 mt-0.5" />
                    <div className="space-y-1">
                      <p className="text-sm font-semibold text-risk-high uppercase tracking-wide">
                        {failureInfo?.stage && failureInfo.stage !== "unknown"
                          ? `Stage Failed: ${failureInfo.stage.replace(/_/g, " ")}`
                          : "Pipeline Error"}
                      </p>
                      <p className="text-sm text-text-secondary leading-relaxed">
                        {failureInfo?.error ?? "An unexpected error occurred."}
                      </p>
                    </div>
                  </div>

                  {failureInfo?.runId && (
                    <div className="border-t border-risk-high/15 pt-3">
                      <p className="text-[11px] text-text-secondary/50 font-mono">
                        Run ID: {failureInfo.runId}
                      </p>
                      <p className="text-[11px] text-text-secondary/50 mt-0.5">
                        Full error details logged to{" "}
                        <span className="font-mono">logs/failures.jsonl</span>
                      </p>
                    </div>
                  )}
                </div>

                {currentRun && currentRun.stages.length > 0 && (
                  <div className="rounded-2xl border border-border bg-surface p-6">
                    <p className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">
                      Pipeline Snapshot
                    </p>
                    <PipelineTracker
                      stages={currentRun.stages}
                      runState={currentRun.state}
                    />
                  </div>
                )}

                <div className="flex gap-3">
                  <button
                    onClick={handleReset}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-border px-6 py-3 text-sm font-semibold text-text-secondary hover:bg-drop-zone transition-colors cursor-pointer"
                  >
                    <ArrowLeft className="h-4 w-4" />
                    {selectedContractId ? "Back to Contract" : "Back to Dashboard"}
                  </button>
                  {failureInfo?.runId && (
                    <button
                      onClick={handleRetry}
                      className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-text-primary px-6 py-3 text-sm font-semibold text-background hover:opacity-80 transition-opacity cursor-pointer"
                    >
                      <RefreshCw className="h-4 w-4" />
                      Retry Analysis
                    </button>
                  )}
                </div>
              </div>
            </motion.div>
          )}

          {/* ── HUMAN REVIEW ── */}
          {state === "human_review" && pendingRunId && (
            <motion.div
              key="human_review"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4 }}
            >
              <HumanReviewPanel
                runId={pendingRunId}
                fileName={fileName}
                contractId={selectedContractId}
                onStartReview={handleStartReview}
                onRejected={handleHumanRejected}
              />
            </motion.div>
          )}

          {/* ── VERDICT ── */}
          {state === "verdict" && result && (
            <motion.div
              key="verdict"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4 }}
            >
              <VerdictCard
                result={result}
                fileName={fileName}
                onReset={handleReset}
                resetLabel={selectedContractId ? "Back to Contract" : "Back to Dashboard"}
                runId={rawVerdict?.run_id ?? (isAwaitingReview && pendingRunId ? pendingRunId : undefined)}
                findings={rawVerdict?.findings ?? (isAwaitingReview ? reviewFindings : undefined)}
                isAwaitingReview={isAwaitingReview}
                humanAction={!isAwaitingReview ? rawVerdict?.human_action : null}
                onApprove={handleApproveVerdict}
                onReject={handleRejectVerdict}
              />
            </motion.div>
          )}

          {/* ── ADMIN ── */}
          {state === "admin" && (
            <motion.div key="admin" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }}>
              <AdminPage onBack={() => setState("dashboard")} />
            </motion.div>
          )}

        </AnimatePresence>
      </main>

      <Footer />
    </div>
  );
}
