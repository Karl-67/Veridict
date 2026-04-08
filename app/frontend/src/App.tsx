import { useState, useCallback, useRef, useEffect } from "react";
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
import type { ReviewResult } from "@/types";

type AppState = "upload" | "pipeline" | "waiting" | "verdict";

export default function App() {
  const [state, setState] = useState<AppState>("upload");
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [fileName, setFileName] = useState("");
  const apiDoneRef = useRef(false);
  const resultRef = useRef<ReviewResult | null>(null);
  const pipelineDoneRef = useRef(false);

  const tryShowVerdict = useCallback(() => {
    if (apiDoneRef.current && pipelineDoneRef.current && resultRef.current) {
      setResult(resultRef.current);
      setState("verdict");
    }
  }, []);

  const handleSubmit = useCallback(
    async (file: File) => {
      setIsPending(true);
      setFileName(file.name);
      apiDoneRef.current = false;
      pipelineDoneRef.current = false;
      resultRef.current = null;

      setState("pipeline");

      try {
        const created = await createRun(file);
        const run = await pollRunUntilDone(created.run_id);
        if (run.state === "finalized" && run.verdict) {
          resultRef.current = verdictToReviewResult(run.verdict);
        } else if (run.state === "awaiting_human_review") {
          throw new Error(
            "Run is awaiting human review — human review UI not implemented yet."
          );
        } else if (run.state === "blocked") {
          throw new Error(`Run blocked: ${run.blocked_reason ?? "unknown reason"}`);
        } else if (run.state === "failed" || run.state === "rejected") {
          throw new Error(`Run ${run.state}`);
        } else if (!run.verdict) {
          throw new Error("Run finished without a verdict");
        }
        apiDoneRef.current = true;
        tryShowVerdict();
      } catch (err) {
        console.error("Upload failed:", err);
        alert(`Upload failed: ${(err as Error).message}`);
        setState("upload");
        apiDoneRef.current = false;
        pipelineDoneRef.current = false;
        resultRef.current = null;
      } finally {
        setIsPending(false);
      }
    },
    [tryShowVerdict]
  );

  const handlePipelineComplete = useCallback(() => {
    pipelineDoneRef.current = true;
    if (apiDoneRef.current) {
      tryShowVerdict();
    } else {
      setState("waiting");
    }
  }, [tryShowVerdict]);

  const handleReset = useCallback(() => {
    setState("upload");
    setResult(null);
    setFileName("");
    apiDoneRef.current = false;
    pipelineDoneRef.current = false;
    resultRef.current = null;
  }, []);

  useEffect(() => {
    if (state !== "waiting") return;
    const interval = setInterval(() => {
      if (apiDoneRef.current && resultRef.current) {
        setResult(resultRef.current);
        setState("verdict");
        clearInterval(interval);
      }
    }, 300);
    return () => clearInterval(interval);
  }, [state]);

  return (
    <div className="min-h-screen bg-background transition-colors duration-300 flex flex-col">
      <Header />

      <main className="flex-1 mx-auto w-full max-w-6xl px-6 lg:px-8 py-16">
        <AnimatePresence mode="wait">
          {/* ============ UPLOAD PAGE ============ */}
          {state === "upload" && (
            <motion.div
              key="upload"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4 }}
              className="space-y-20"
            >
              {/* Hero header */}
              <div className="text-center">
                <h1 className="font-serif text-4xl lg:text-5xl font-bold tracking-tight text-text-primary">
                  Review your contract
                </h1>
                <p className="mt-4 text-lg text-text-secondary max-w-xl mx-auto">
                  Upload your document for a bespoke legal intelligence
                  analysis. Authoritatively precise, instantly delivered.
                </p>
              </div>

              {/* Two-column hero grid */}
              <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-8 items-start -mt-10">
                <UploadForm onSubmit={handleSubmit} isPending={isPending} />
                <div className="space-y-4">
                  <RecentActivity />
                  <QuickTip />
                </div>
              </div>

              {/* Methodology */}
              <MethodologySection />

              {/* Trust & Security */}
              <TrustSecurity />
            </motion.div>
          )}

          {/* ============ ANALYZING PAGE ============ */}
          {(state === "pipeline" || state === "waiting") && (
            <motion.div
              key="pipeline"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.4 }}
              className="space-y-12"
            >
              {/* Header */}
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

              {/* Two-column: insights left, pipeline right */}
              <div className="grid grid-cols-1 lg:grid-cols-[1fr_2fr] gap-8 items-start">
                <AIEngineInsights
                  fileName={fileName}
                  charCount={42852}
                />
                <div className="rounded-2xl border border-border bg-surface p-8 space-y-10">
                  <PipelineTracker onComplete={handlePipelineComplete} />
                  <div className="border-t border-border pt-8">
                    <PipelineMethodology />
                  </div>
                </div>
              </div>

              {/* Status pill */}
              <div className="text-center space-y-3">
                <div className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-5 py-2.5">
                  <span className="h-2 w-2 rounded-full bg-risk-low animate-pulse" />
                  <span className="text-sm font-medium text-text-primary">
                    AI Engine running at peak performance
                  </span>
                </div>
                <p className="text-sm italic text-text-secondary">
                  {state === "waiting"
                    ? "Finalizing verdict..."
                    : "This usually takes 15-30 seconds. Do not refresh this page."}
                </p>
              </div>
            </motion.div>
          )}

          {/* ============ VERDICT PAGE ============ */}
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
