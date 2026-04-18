import { useState, useEffect, useRef, useCallback } from "react";
import { Send, Trash2, Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import type { Comment } from "@/types";
import { cn } from "@/lib/utils";

interface CommentThreadProps {
  comments: Comment[];
  loading: boolean;
  onPost: (body: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  placeholder?: string;
  compact?: boolean;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function CommentThread({
  comments,
  loading,
  onPost,
  onDelete,
  placeholder = "Add a comment...",
  compact = false,
}: CommentThreadProps) {
  const { user } = useAuth();
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [comments.length]);

  const submit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft.trim() || posting) return;
    setPosting(true);
    try {
      await onPost(draft.trim());
      setDraft("");
    } finally {
      setPosting(false);
    }
  }, [draft, posting, onPost]);

  const handleDelete = useCallback(async (id: string) => {
    setDeletingId(id);
    try { await onDelete(id); } finally { setDeletingId(null); }
  }, [onDelete]);

  return (
    <div className="flex flex-col gap-0">
      {/* Thread */}
      {loading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-text-secondary/40" />
        </div>
      ) : comments.length === 0 ? (
        <p className="text-xs text-text-secondary/40 py-2">No comments yet.</p>
      ) : (
        <div className={cn("space-y-0", compact && "max-h-48 overflow-y-auto")}>
          {comments.map((c) => (
            <div key={c.id} className="py-3 border-b border-border/50 last:border-0 group">
              <div className="flex items-start gap-2.5">
                {/* Avatar */}
                <div
                  className="h-7 w-7 shrink-0 rounded-full flex items-center justify-center text-[10px] font-bold text-white mt-0.5"
                  style={{ backgroundColor: (c as unknown as { avatar_color?: string }).avatar_color ?? "#6366f1" }}
                >
                  {c.author_name.split(" ").map(p => p[0]).slice(0, 2).join("").toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-0.5">
                    <div className="flex items-baseline gap-1.5 flex-wrap">
                      <span className="text-xs font-semibold text-text-primary">{c.author_name}</span>
                      {(c as unknown as { job_title?: string }).job_title && (
                        <span className="text-[10px] text-text-secondary/50">{(c as unknown as { job_title?: string }).job_title}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[10px] text-text-secondary/40">{timeAgo(c.created_at)}</span>
                      {user?.user_id === c.author_id && (
                        <button
                          onClick={() => handleDelete(c.id)}
                          disabled={deletingId === c.id}
                          className="opacity-0 group-hover:opacity-100 transition-opacity text-text-secondary/40 hover:text-risk-high cursor-pointer"
                        >
                          {deletingId === c.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                        </button>
                      )}
                    </div>
                  </div>
                  <p className="text-sm leading-relaxed text-text-secondary">{c.body}</p>
                </div>
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}

      {/* Input */}
      {user ? (
        <form onSubmit={submit} className="mt-3 relative">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(e as unknown as React.FormEvent); } }}
            placeholder={placeholder}
            rows={compact ? 1 : 2}
            className="w-full border-b border-border bg-transparent px-0 py-2 text-sm text-text-primary placeholder:text-text-secondary/40 resize-none focus:outline-none focus:border-accent/50 transition-colors pr-8"
          />
          <button
            type="submit"
            disabled={!draft.trim() || posting}
            className="absolute bottom-3 right-0 text-accent hover:text-accent-hover disabled:opacity-30 transition-colors cursor-pointer disabled:cursor-not-allowed"
          >
            {posting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </form>
      ) : (
        <p className="mt-3 text-xs text-text-secondary/50 italic">Sign in to post comments.</p>
      )}
    </div>
  );
}
