import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Shield,
  FileSearch,
  UserCheck,
  CheckCircle2,
  Scale,
  Loader2,
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
    <div className="space-y-0">
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
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.06, duration: 0.3 }}
            className="flex items-start gap-4"
          >
            {/* Vertical line + circle */}
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  "flex h-10 w-10 items-center justify-center rounded-full border-2 shrink-0",
                  status === "done"
                    ? "border-risk-low bg-risk-low/10"
                    : status === "running"
                      ? "border-accent bg-accent/10"
                      : "border-border bg-background"
                )}
              >
                {status === "done" ? (
                  <CheckCircle2 className="h-5 w-5 text-risk-low" />
                ) : status === "running" ? (
                  <Loader2 className="h-5 w-5 text-accent animate-spin" />
                ) : (
                  <Circle className="h-4 w-4 text-border" />
                )}
              </div>
              {index < STAGES.length - 1 && (
                <div
                  className={cn(
                    "w-0.5 h-8",
                    index < currentStage ? "bg-risk-low/30" : "bg-border"
                  )}
                />
              )}
            </div>

            {/* Label + status */}
            <div className="flex items-center justify-between flex-1 pt-2">
              <div className="flex items-center gap-3">
                <Icon
                  className={cn(
                    "h-4 w-4",
                    status === "done"
                      ? "text-text-primary"
                      : status === "running"
                        ? "text-accent"
                        : "text-text-secondary/40"
                  )}
                />
                <span
                  className={cn(
                    "text-sm font-medium",
                    status === "done"
                      ? "text-text-primary"
                      : status === "running"
                        ? "text-text-primary font-semibold"
                        : "text-text-secondary/50"
                  )}
                >
                  {stage.name}
                </span>
              </div>
              <span
                className={cn(
                  "text-xs font-medium italic",
                  status === "done"
                    ? "text-risk-low"
                    : status === "running"
                      ? "text-accent"
                      : "text-text-secondary/40"
                )}
              >
                {status === "done"
                  ? "Complete"
                  : status === "running"
                    ? "Analyzing..."
                    : "Pending"}
              </span>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
