import { useState, useCallback, useRef, useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import Header from "@/components/Header";
import UploadForm from "@/components/UploadForm";
import PipelineTracker from "@/components/PipelineTracker";
import VerdictCard from "@/components/VerdictCard";
import { uploadContract } from "@/lib/api";
import type { ReviewResult } from "@/types";

type AppState = "upload" | "pipeline" | "waiting" | "verdict";

export default function App() {
  const [state, setState] = useState<AppState>("upload");
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [isPending, setIsPending] = useState(false);
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
      apiDoneRef.current = false;
      pipelineDoneRef.current = false;
      resultRef.current = null;

      setState("pipeline");

      try {
        const data = await uploadContract(file);
        resultRef.current = data.result;
        apiDoneRef.current = true;
        tryShowVerdict();
      } catch (err) {
        console.error("Upload failed:", err);
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

  // Poll when waiting for API after pipeline is done
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
    <div className="min-h-screen bg-background">
      <Header />
      <main className="mx-auto max-w-5xl px-6 py-16">
        <AnimatePresence mode="wait">
          {state === "upload" && (
            <div key="upload" className="flex flex-col items-center gap-8">
              <div className="text-center">
                <h1 className="text-4xl font-bold tracking-tight text-text-primary">
                  Contract Intelligence
                </h1>
                <p className="mt-3 text-lg text-text-muted">
                  Upload a contract and get an AI-powered legal review in seconds
                </p>
              </div>
              <UploadForm onSubmit={handleSubmit} isPending={isPending} />
            </div>
          )}

          {(state === "pipeline" || state === "waiting") && (
            <div key="pipeline" className="flex flex-col items-center gap-8">
              <div className="text-center">
                <h2 className="text-2xl font-bold text-text-primary">
                  Analyzing Contract
                </h2>
                <p className="mt-2 text-text-muted">
                  {state === "waiting"
                    ? "Finalizing verdict..."
                    : "Running multi-agent review pipeline..."}
                </p>
              </div>
              <PipelineTracker onComplete={handlePipelineComplete} />
            </div>
          )}

          {state === "verdict" && result && (
            <div key="verdict" className="flex flex-col items-center gap-8">
              <div className="text-center">
                <h2 className="text-2xl font-bold text-text-primary">
                  Analysis Complete
                </h2>
                <p className="mt-2 text-text-muted">
                  Here's your contract verdict
                </p>
              </div>
              <VerdictCard result={result} />
            </div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}
