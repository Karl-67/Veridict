import { useState, useCallback, type DragEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { FileText, X, AlertCircle, Lock } from "lucide-react";
import { cn } from "@/lib/utils";

interface UploadFormProps {
  onSubmit: (file: File) => void;
  isPending: boolean;
}

export default function UploadForm({ onSubmit, isPending }: UploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validateAndSet = useCallback((f: File) => {
    setError(null);
    if (!f.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are accepted");
      return;
    }
    setFile(f);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const dropped = e.dataTransfer.files[0];
      if (dropped) validateAndSet(dropped);
    },
    [validateAndSet]
  );

  const openPicker = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pdf";
    input.onchange = (e) => {
      const f = (e.target as HTMLInputElement).files?.[0];
      if (f) validateAndSet(f);
    };
    input.click();
  };

  const handleSubmit = () => {
    if (file) onSubmit(file);
  };

  return (
    <div className="w-full">
      {/* Drop zone — no dashed box, just a clean centered area */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={openPicker}
        className={cn(
          "relative cursor-pointer px-8 py-24 text-center transition-all duration-300",
          dragOver ? "bg-accent/5" : "hover:bg-drop-zone/40"
        )}
      >
        {/* Bottom indicator line */}
        <div
          className={cn(
            "absolute bottom-0 inset-x-0 h-px transition-colors duration-300",
            dragOver ? "bg-accent" : "bg-border/70"
          )}
        />

        <div className="flex flex-col items-center gap-3 text-text-secondary">
          <div className="flex h-12 w-12 items-center justify-center text-accent">
            <Lock className="h-5 w-5" />
          </div>
          <p className="text-base font-medium text-text-primary">
            Drop your PDF here
          </p>
          <p className="text-sm text-text-secondary">
            or{" "}
            <span className="text-accent font-medium underline underline-offset-2">
              browse files
            </span>
          </p>
          <p className="text-[10px] uppercase tracking-widest text-text-secondary/40 mt-1">
            Supported: PDF, DOCX (Max 25MB)
          </p>
        </div>
      </div>

      {/* File row — inline, not a card */}
      <AnimatePresence>
        {file && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="mt-4 flex items-center gap-3 pt-4 border-t border-border"
          >
            <FileText className="h-4 w-4 text-text-secondary shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-text-primary truncate">
                {file.name}
              </p>
              <p className="text-xs text-text-secondary">
                {(file.size / (1024 * 1024)).toFixed(1)} MB
              </p>
            </div>
            <span className="text-xs font-medium text-risk-low mr-2">
              Ready
            </span>
            <button
              onClick={(e) => { e.stopPropagation(); setFile(null); }}
              className="text-text-secondary/50 hover:text-text-primary transition-colors cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <motion.div
          initial={{ opacity: 0, y: -5 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-3 flex items-center gap-2 text-sm text-risk-high"
        >
          <AlertCircle className="h-4 w-4" />
          {error}
        </motion.div>
      )}

      {/* Action row */}
      <div className="mt-5 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-text-secondary/40">
          <Lock className="h-3 w-3" />
          End-to-end encrypted
        </div>
        <div className="flex items-center gap-4">
          {file && (
            <button
              onClick={() => setFile(null)}
              className="text-sm font-medium text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
            >
              Cancel
            </button>
          )}
          <button
            onClick={handleSubmit}
            disabled={!file || isPending}
            className={cn(
              "rounded-xl px-6 py-2.5 text-sm font-semibold transition-all duration-200",
              file && !isPending
                ? "bg-accent text-white hover:bg-accent-hover cursor-pointer"
                : "bg-border/50 text-text-secondary cursor-not-allowed"
            )}
          >
            {isPending ? "Analyzing..." : "Start Review"}
          </button>
        </div>
      </div>
    </div>
  );
}
