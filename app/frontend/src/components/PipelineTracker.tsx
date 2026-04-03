import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Shield,
  FileSearch,
  UserCheck,
  CheckCircle2,
  Scale,
  Circle,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface PipelineTrackerProps {
  onComplete: () => void;
}

const STAGES = [
  { name: "Harvey", icon: Shield, delay: 800 },
  { name: "Kira", icon: FileSearch, delay: 600 },
  { name: "Reviewer 1", icon: UserCheck, delay: 1200 },
  { name: "Reviewer 2", icon: UserCheck, delay: 1200 },
  { name: "Reviewer 3", icon: UserCheck, delay: 1200 },
  { name: "Validators", icon: CheckCircle2, delay: 900 },
  { name: "Verdict", icon: Scale, delay: 0 },
];

export default function PipelineTracker({ onComplete }: PipelineTrackerProps) {
  const [currentStage, setCurrentStage] = useState(0);

  useEffect(() => {
    if (currentStage >= STAGES.length - 1) {
      onComplete();
      return;
    }

    const timeout = setTimeout(() => {
      setCurrentStage((prev) => prev + 1);
    }, STAGES[currentStage].delay);

    return () => clearTimeout(timeout);
  }, [currentStage, onComplete]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="w-full max-w-md mx-auto"
    >
      <div className="rounded-xl border border-border bg-surface p-6 shadow-xl shadow-black/30">
        <h3 className="mb-6 text-lg font-semibold text-text-primary">
          Analysis Pipeline
        </h3>
        <div className="space-y-1">
          {STAGES.map((stage, index) => {
            const Icon = stage.icon;
            const status =
              index < currentStage
                ? "done"
                : index === currentStage
                  ? "running"
                  : "pending";

            return (
              <motion.div
                key={stage.name}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.08, duration: 0.3 }}
                className="flex items-center gap-4 rounded-lg px-3 py-2.5"
              >
                <div className="relative flex h-8 w-8 items-center justify-center">
                  {status === "done" ? (
                    <CheckCircle2 className="h-5 w-5 text-risk-low" />
                  ) : status === "running" ? (
                    <motion.div
                      animate={{ scale: [1, 1.3, 1] }}
                      transition={{
                        duration: 1,
                        repeat: Infinity,
                        ease: "easeInOut",
                      }}
                    >
                      <Circle className="h-4 w-4 fill-primary text-primary" />
                    </motion.div>
                  ) : (
                    <Circle className="h-3.5 w-3.5 text-text-muted/40" />
                  )}
                </div>

                <Icon
                  className={cn(
                    "h-4.5 w-4.5",
                    status === "done"
                      ? "text-text-primary"
                      : status === "running"
                        ? "text-primary"
                        : "text-text-muted/50"
                  )}
                />

                <span
                  className={cn(
                    "text-sm font-medium",
                    status === "done"
                      ? "text-text-primary"
                      : status === "running"
                        ? "text-primary"
                        : "text-text-muted/50"
                  )}
                >
                  {stage.name}
                </span>

                <span
                  className={cn(
                    "ml-auto text-xs font-medium rounded-full px-2 py-0.5",
                    status === "done"
                      ? "bg-risk-low/15 text-risk-low"
                      : status === "running"
                        ? "bg-primary/15 text-primary"
                        : "text-text-muted/40"
                  )}
                >
                  {status === "done"
                    ? "Complete"
                    : status === "running"
                      ? "Running"
                      : "Pending"}
                </span>
              </motion.div>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}
