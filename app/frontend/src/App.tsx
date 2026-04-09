import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import UploadForm from "@/components/UploadForm";
import RecentActivity from "@/components/RecentActivity";
import QuickTip from "@/components/QuickTip";
import MethodologySection from "@/components/MethodologySection";
import TrustSecurity from "@/components/TrustSecurity";
import PipelineTracker from "@/components/PipelineTracker";
import AIEngineInsights from "@/components/AIEngineInsights";
import PipelineMethodology from "@/components/PipelineMethodology";
import VerdictCard from "@/components/VerdictCard";
import { createRun, pollRunUntilDone, verdictToReviewResult } from "@/lib/api";
import HumanReviewPanel from "@/components/HumanReviewPanel";
import { XCircle, RefreshCw } from "lucide-react";
import type { FinalVerdict, ReviewResult, RunDetail } from "@/types";

type AppState = "upload" | "processing" | "human_review" | "verdict" | "failed";

interface FailureInfo {
  stage: string;
  error: string;
  runId?: string;
}

export default function App() {
  const [state, setState] = useState<AppState>("upload");
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [fileName, setFileName] = useState("");
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [currentRun, setCurrentRun] = useState<RunDetail | null>(null);
  const [failureInfo, setFailureInfo] = useState<FailureInfo | null>(null);

  const handleSubmit = useCallback(async (file: File) => {
    setIsPending(true);
    setFileName(file.name);
    setCurrentRun(null);
    setFailureInfo(null);
    setState("processing");

    try {
      const created = await createRun(file);

      const run = await pollRunUntilDone(
        created.run_id,
        1500,
        5 * 60_000,
        (r) => setCurrentRun(r)       // live stage updates on every poll tick
      );
      setCurrentRun(run);

      if (run.state === "awaiting_human_review") {
        setPendingRunId(created.run_id);
        setState("human_review");
      } else if (run.state === "finalized" && run.verdict) {
        setResult(verdictToReviewResult(run.verdict));
        setState("verdict");
      } else if (run.state === "failed" || run.state === "blocked") {
        const failedStage = run.stages.find((s) => s.state === "failed" || s.state === "blocked");
        setFailureInfo({
          stage: failedStage?.stage_name ?? "unknown",
          error: failedStage?.error_detail ?? run.blocked_reason ?? "Unknown error",
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
      setFailureInfo({
        stage: "unknown",
        error: (err as Error).message,
      });
      setState("failed");
    } finally {
      setIsPending(false);
    }
  }, []);

  const handleHumanApproved = useCallback((verdict: FinalVerdict) => {
    setResult(verdictToReviewResult(verdict));
    setState("verdict");
    setPendingRunId(null);
  }, []);

  const handleHumanRejected = useCallback(() => {
    setState("upload");
    setPendingRunId(null);
    setFileName("");
    setCurrentRun(null);
  }, []);

  const handleReset = useCallback(() => {
    setState("upload");
    setResult(null);
    setFileName("");
    setPendingRunId(null);
    setCurrentRun(null);
    setFailureInfo(null);
  }, []);

  return (
    <div className="min-h-screen bg-background transition-colors duration-300 flex flex-col">
      <Header />

      <main className="flex-1 mx-auto w-full max-w-6xl px-6 lg:px-8 py-16">
        <AnimatePresence mode="wait">

          {/* ── UPLOAD ── */}
          {state === "upload" && (
            <motion.div
              key="upload"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4 }}
              className="space-y-20"
            >
              <div className="text-center">
                <h1 className="font-serif text-4xl lg:text-5xl font-bold tracking-tight text-text-primary">
                  Review your contract
                </h1>
                <p className="mt-4 text-lg text-text-secondary max-w-xl mx-auto">
                  Upload your document for a bespoke legal intelligence
                  analysis. Authoritatively precise, instantly delivered.
                </p>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-8 items-start -mt-10">
                <UploadForm onSubmit={handleSubmit} isPending={isPending} />
                <div className="space-y-4">
                  <RecentActivity />
                  <QuickTip />
                </div>
              </div>

              <MethodologySection />
              <TrustSecurity />
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
              className="space-y-12"
            >
              <div className="text-center">
                <h1 className="font-serif text-4xl lg:text-5xl font-bold text-text-primary">
                  Analyzing your contract
                </h1>
                <p className="mt-4 text-lg text-text-secondary max-w-2xl mx-auto">
                  Our Legal Intelligence engine is scanning for risks,
                  inconsistencies, and high-value clauses across your
                  documentation.
                </p>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-[1fr_2fr] gap-8 items-start">
                <AIEngineInsights fileName={fileName} charCount={42852} />
                <div className="rounded-2xl border border-border bg-surface p-8 space-y-10">
                  <PipelineTracker
                    stages={currentRun?.stages ?? []}
                    runState={currentRun?.state ?? null}
                  />
                  <div className="border-t border-border pt-8">
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
              className="space-y-8"
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

              <div className="max-w-2xl mx-auto space-y-4">
                {/* Error card */}
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

                {/* Stage snapshot (if we have run data) */}
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
                    Try Again
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
              />
            </motion.div>
          )}

        </AnimatePresence>
      </main>

      <Footer />
    </div>
  );
}
