import { useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, XCircle, Loader2, ShieldCheck } from "lucide-react";
import { submitHumanReview } from "@/lib/api";
import type { FinalVerdict } from "@/types";

interface HumanReviewPanelProps {
  runId: string;
  fileName: string;
  onApproved: (verdict: FinalVerdict) => void;
  onRejected: () => void;
}

type PanelState = "idle" | "confirming_reject" | "submitting";

export default function HumanReviewPanel({
  runId,
  fileName,
  onApproved,
  onRejected,
}: HumanReviewPanelProps) {
  const [panelState, setPanelState] = useState<PanelState>("idle");
  const [rejectionReason, setRejectionReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleApprove = async () => {
    setPanelState("submitting");
    setError(null);
    try {
      const result = await submitHumanReview(runId, {
        run_action: "approved",
        reviewer_id: "verdict-user",
        finding_actions: [],
      });
      if (result.verdict) {
        onApproved(result.verdict);
      } else {
        setError("Approval succeeded but no verdict was returned.");
        setPanelState("idle");
      }
    } catch (err) {
      setError((err as Error).message);
      setPanelState("idle");
    }
  };

  const handleReject = async () => {
    if (!rejectionReason.trim()) {
      setError("Please enter a rejection reason.");
      return;
    }
    setPanelState("submitting");
    setError(null);
    try {
      await submitHumanReview(runId, {
        run_action: "rejected",
        reviewer_id: "verdict-user",
        rejection_reason: rejectionReason,
      });
      onRejected();
    } catch (err) {
      setError((err as Error).message);
      setPanelState("idle");
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.4 }}
      className="max-w-2xl mx-auto space-y-8"
    >
      {/* Header */}
      <div className="text-center">
        <h1 className="font-serif text-4xl lg:text-5xl font-bold text-text-primary">
          Review Ready
        </h1>
        <p className="mt-4 text-lg text-text-secondary max-w-xl mx-auto">
          The AI analysis for{" "}
          <span className="italic text-text-primary">{fileName}</span> is
          complete and awaiting your approval.
        </p>
      </div>

      {/* Status card */}
      <div className="rounded-2xl border border-border bg-surface p-8 space-y-6">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-risk-low/10 border border-risk-low/30">
            <ShieldCheck className="h-6 w-6 text-risk-low" />
          </div>
          <div>
            <p className="text-sm font-semibold text-text-primary uppercase tracking-widest">
              Analysis Complete
            </p>
            <p className="text-sm text-text-secondary mt-0.5">
              All AI reviewer stages have finished. Human sign-off required to
              generate the final verdict.
            </p>
          </div>
        </div>

        <div className="border-t border-border pt-6 space-y-3 text-sm text-text-secondary">
          <div className="flex justify-between">
            <span>Harvey branch (internal policy)</span>
            <span className="text-risk-low font-medium">Complete</span>
          </div>
          <div className="flex justify-between">
            <span>Kira branch (compliance)</span>
            <span className="text-risk-low font-medium">Complete</span>
          </div>
          <div className="flex justify-between">
            <span>Final reviewer consensus</span>
            <span className="text-risk-low font-medium">Complete</span>
          </div>
        </div>
      </div>

      {/* Reject confirmation panel */}
      {panelState === "confirming_reject" && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="rounded-2xl border border-risk-high/30 bg-risk-high/5 p-6 space-y-4"
        >
          <p className="text-sm font-semibold text-risk-high">
            Provide a reason for rejection
          </p>
          <textarea
            value={rejectionReason}
            onChange={(e) => setRejectionReason(e.target.value)}
            rows={3}
            placeholder="e.g. Insufficient evidence for flagged clauses..."
            className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-sm text-text-primary placeholder:text-text-secondary/50 resize-none focus:outline-none focus:border-risk-high/50"
          />
          <div className="flex gap-3">
            <button
              onClick={() => { setPanelState("idle"); setError(null); }}
              className="flex-1 rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-text-secondary hover:bg-drop-zone transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={handleReject}
              className="flex-1 rounded-xl bg-risk-high px-4 py-2.5 text-sm font-semibold text-white hover:bg-risk-high/80 transition-colors cursor-pointer"
            >
              Confirm Rejection
            </button>
          </div>
        </motion.div>
      )}

      {/* Error */}
      {error && (
        <p className="text-sm text-risk-high text-center">{error}</p>
      )}

      {/* Action buttons */}
      {panelState !== "confirming_reject" && (
        <div className="flex gap-4">
          <button
            disabled={panelState === "submitting"}
            onClick={() => { setPanelState("confirming_reject"); setError(null); }}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-border px-6 py-3.5 text-sm font-semibold text-text-secondary hover:bg-drop-zone hover:text-text-primary transition-colors disabled:opacity-40 cursor-pointer"
          >
            <XCircle className="h-4 w-4" />
            Reject
          </button>
          <button
            disabled={panelState === "submitting"}
            onClick={handleApprove}
            className="flex flex-2 flex-1 items-center justify-center gap-2 rounded-xl bg-accent px-8 py-3.5 text-sm font-semibold text-white hover:bg-accent-hover transition-colors disabled:opacity-40 cursor-pointer"
          >
            {panelState === "submitting" ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Submitting...
              </>
            ) : (
              <>
                <CheckCircle2 className="h-4 w-4" />
                Approve & Generate Verdict
              </>
            )}
          </button>
        </div>
      )}
    </motion.div>
  );
}
