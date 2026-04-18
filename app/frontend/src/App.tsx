import { useState, useCallback } from "react";
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
import ContractsDashboard from "@/components/ContractsDashboard";
import ContractDetail from "@/components/ContractDetail";
import {
  pollRunUntilDone,
  verdictToReviewResult,
  createContract,
  addContractVersion,
  getRun,
} from "@/lib/api";
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
  | "failed";

interface FailureInfo {
  stage: string;
  error: string;
  runId?: string;
}

export default function App() {
  const [state, setState] = useState<AppState>("dashboard");
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [fileName, setFileName] = useState("");
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [currentRun, setCurrentRun] = useState<RunDetail | null>(null);
  const [failureInfo, setFailureInfo] = useState<FailureInfo | null>(null);

  // Contract context
  const [selectedContractId, setSelectedContractId] = useState<number | null>(null);
  const [newContractName, setNewContractName] = useState("");
  const [rawVerdict, setRawVerdict] = useState<FinalVerdict | null>(null);

  // ── Shared polling logic ─────────────────────────────────────────────────

  const processRun = useCallback(
    async (runId: string, _contractId: number | null) => {
      try {
        const run = await pollRunUntilDone(runId, 1500, 5 * 60_000, (r) =>
          setCurrentRun(r)
        );
        setCurrentRun(run);

        if (run.state === "awaiting_human_review") {
          setPendingRunId(runId);
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
            error:
              failedStage?.error_detail ?? run.blocked_reason ?? "Unknown error",
            runId: run.run_id,
          });
          setState("failed");
        } else {
          setFailureInfo({
            stage: "unknown",
            error: `Run ended in unexpected state: ${run.state}`,
            runId: run.run_id,
          });
          setState("failed");
        }
      } catch (err) {
        setFailureInfo({ stage: "unknown", error: (err as Error).message });
        setState("failed");
      } finally {
        setIsPending(false);
      }
    },
    []
  );

  // ── New contract creation ────────────────────────────────────────────────

  const handleNewContractSubmit = useCallback(
    async (file: File) => {
      if (!newContractName.trim()) return;
      setIsPending(true);
      setFileName(file.name);
      setCurrentRun(null);
      setFailureInfo(null);
      setState("processing");

      try {
        const contract = await createContract(newContractName.trim());
        setSelectedContractId(contract.id);
        const versionResp = await addContractVersion(contract.id, file);
        await processRun(versionResp.run_id, contract.id);
      } catch (err) {
        setFailureInfo({ stage: "unknown", error: (err as Error).message });
        setState("failed");
        setIsPending(false);
      }
    },
    [newContractName, processRun]
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
      if (run.state === "awaiting_human_review") {
        setPendingRunId(runId);
        setFileName(run.filename ?? "");
        setCurrentRun(run);
        setState("human_review");
      } else if (run.verdict) {
        setResult(verdictToReviewResult(run.verdict));
        setRawVerdict(run.verdict);
        setFileName(run.filename ?? "");
        setState("verdict");
      }
    } catch (err) {
      console.error("Failed to fetch run:", err);
    }
  }, []);

  // ── Human review callbacks ───────────────────────────────────────────────

  const handleHumanApproved = useCallback((verdict: FinalVerdict) => {
    setResult(verdictToReviewResult(verdict));
    setRawVerdict(verdict);
    setState("verdict");
    setPendingRunId(null);
  }, []);

  const handleHumanRejected = useCallback(() => {
    if (selectedContractId) {
      setState("contract_detail");
    } else {
      setState("dashboard");
    }
    setPendingRunId(null);
    setFileName("");
    setCurrentRun(null);
  }, [selectedContractId]);

  // ── Reset / back navigation ──────────────────────────────────────────────

  const handleReset = useCallback(() => {
    if (selectedContractId) {
      setState("contract_detail");
    } else {
      setState("dashboard");
    }
    setResult(null);
    setRawVerdict(null);
    setFileName("");
    setPendingRunId(null);
    setCurrentRun(null);
    setFailureInfo(null);
  }, [selectedContractId]);

  const handleBackToDashboard = useCallback(() => {
    setState("dashboard");
    setSelectedContractId(null);
    setNewContractName("");
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-background transition-colors duration-300 flex flex-col">
      <Header
        activePage={state === "dashboard" || state === "contract_detail" ? "Dashboard" : state === "new_contract" ? "Dashboard" : "Dashboard"}
        onNavigate={(page) => {
          if (page === "Dashboard" || page === "History") {
            setState("dashboard");
            setSelectedContractId(null);
            setNewContractName("");
            setResult(null);
            setFileName("");
            setPendingRunId(null);
            setCurrentRun(null);
            setFailureInfo(null);
          }
        }}
        onNewContract={() => {
          setSelectedContractId(null);
          setNewContractName("");
          setState("new_contract");
        }}
      />

      <main className="flex-1 mx-auto w-full max-w-[1440px] px-6 sm:px-10 lg:px-14 py-20">
        <AnimatePresence mode="wait">

          {/* ── DASHBOARD ── */}
          {state === "dashboard" && (
            <motion.div key="dashboard" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }}>
              <ContractsDashboard
                onNewContract={() => {
                  setSelectedContractId(null);
                  setNewContractName("");
                  setState("new_contract");
                }}
                onOpenContract={(contract: ContractSummary) => {
                  setSelectedContractId(contract.id);
                  setState("contract_detail");
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
                  {/* Upload form */}
                  <UploadForm
                    onSubmit={handleNewContractSubmit}
                    isPending={isPending}
                    disabled={!newContractName.trim()}
                  />
                </div>
                <div className="space-y-6">
                  <RecentActivity
                    onViewAll={() => setState("dashboard")}
                    onOpen={(contract) => {
                      setSelectedContractId(contract.id);
                      setState("contract_detail");
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
                  This usually takes 15–30 seconds. Do not refresh this page.
                </p>
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
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-accent px-6 py-3 text-sm font-semibold text-white hover:bg-accent-hover transition-colors cursor-pointer"
                  >
                    <RefreshCw className="h-4 w-4" />
                    {selectedContractId ? "Back to Contract" : "Back to Dashboard"}
                  </button>
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
                onApproved={handleHumanApproved}
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
                runId={rawVerdict?.run_id}
                findings={rawVerdict?.findings}
              />
            </motion.div>
          )}

        </AnimatePresence>
      </main>

      <Footer />
    </div>
  );
}
