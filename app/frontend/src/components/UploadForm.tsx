import { useState, useCallback, type DragEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, FileCheck, ArrowRight, AlertCircle } from "lucide-react";
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

  const handleSubmit = () => {
    if (file) onSubmit(file);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="w-full max-w-xl mx-auto"
    >
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => {
          if (!file) {
            const input = document.createElement("input");
            input.type = "file";
            input.accept = ".pdf";
            input.onchange = (e) => {
              const f = (e.target as HTMLInputElement).files?.[0];
              if (f) validateAndSet(f);
            };
            input.click();
          }
        }}
        className={cn(
          "relative cursor-pointer rounded-xl border-2 border-dashed p-12 text-center transition-all duration-300",
          dragOver
            ? "border-primary bg-primary/10 shadow-lg shadow-primary/20"
            : file
              ? "border-risk-low/50 bg-risk-low/5"
              : "border-border bg-surface hover:border-text-muted"
        )}
      >
        <AnimatePresence mode="wait">
          {file ? (
            <motion.div
              key="file"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="flex flex-col items-center gap-3"
            >
              <FileCheck className="h-10 w-10 text-risk-low" />
              <p className="text-lg font-medium text-text-primary">{file.name}</p>
              <p className="text-sm text-text-muted">
                {(file.size / 1024).toFixed(1)} KB
              </p>
            </motion.div>
          ) : (
            <motion.div
              key="upload"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="flex flex-col items-center gap-3"
            >
              <Upload className="h-10 w-10 text-text-muted" />
              <p className="text-lg font-medium text-text-primary">
                Drop your contract PDF here
              </p>
              <p className="text-sm text-text-muted">or click to browse</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

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

      <button
        onClick={handleSubmit}
        disabled={!file || isPending}
        className={cn(
          "mt-6 flex w-full items-center justify-center gap-2 rounded-lg px-6 py-3.5 text-base font-semibold transition-all",
          file && !isPending
            ? "bg-primary text-white hover:bg-primary-hover cursor-pointer"
            : "bg-surface text-text-muted cursor-not-allowed border border-border"
        )}
      >
        {isPending ? (
          <>Analyzing...</>
        ) : (
          <>
            Analyze Contract
            <ArrowRight className="h-4 w-4" />
          </>
        )}
      </button>
    </motion.div>
  );
}
