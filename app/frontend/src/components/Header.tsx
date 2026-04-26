import { useEffect, useRef, useState } from "react";
import { Moon, Sun, LogOut, Settings, Bell, CheckCheck, Trash2, AlertTriangle, CheckCircle2, ShieldAlert, Search } from "lucide-react";
import { useTheme } from "@/lib/useTheme";
import { useAuth } from "@/context/AuthContext";
import { useNotifications, type AppNotification } from "@/context/NotificationContext";
import { cn } from "@/lib/utils";

function initials(name: string): string {
  return name.split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase();
}

interface HeaderProps {
  activePage?: "Dashboard" | "History" | "Admin" | "Profile";
  onNavigate?: (page: "Dashboard" | "History") => void;
  onAdmin?: () => void;
  onProfile?: () => void;
  onSearchOpen?: () => void;
  onNotificationClick?: (n: AppNotification) => void;
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

function NotificationIcon({ type }: { type: AppNotification["type"] }) {
  if (type === "awaiting_review")
    return <ShieldAlert className="h-3.5 w-3.5 text-accent shrink-0" />;
  if (type === "run_failed")
    return <AlertTriangle className="h-3.5 w-3.5 text-risk-high shrink-0" />;
  return <CheckCircle2 className="h-3.5 w-3.5 text-risk-low shrink-0" />;
}

const NAV_ITEMS: Array<{ label: string; page: "Dashboard" | "History" }> = [
  { label: "Dashboard", page: "Dashboard" },
  { label: "History",   page: "History" },
];

export default function Header({ activePage = "Dashboard", onNavigate, onAdmin, onProfile, onSearchOpen, onNotificationClick }: HeaderProps) {
  const { dark, toggle } = useTheme();
  const { user, logout } = useAuth();
  const { notifications, unreadCount, markAllRead, remove, clearAll } = useNotifications();
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  function handleOpen() {
    setOpen(v => !v);
    if (!open && unreadCount > 0) markAllRead();
  }

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur-md">
      <div className="mx-auto flex h-[52px] max-w-[1400px] items-center justify-between px-6 sm:px-10 lg:px-[52px]">
        <div className="flex items-center gap-8">
          <button
            onClick={() => onNavigate?.("Dashboard")}
            className="font-serif text-[17px] font-bold tracking-tight text-text-primary cursor-pointer hover:opacity-80 transition-opacity"
          >
            Veridict
          </button>
          <nav className="hidden sm:flex items-center gap-6">
            {NAV_ITEMS.map(({ label, page }) => (
              <button
                key={page}
                onClick={() => onNavigate?.(page)}
              className={cn(
                  "rounded-md px-3 py-1 text-[13px] font-medium transition-colors cursor-pointer",
                  page === activePage
                    ? "bg-drop-zone text-text-primary"
                    : "text-text-secondary hover:text-text-primary hover:bg-drop-zone/60"
                )}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {/* Search */}
          <button
            onClick={onSearchOpen}
            className="hidden sm:flex items-center gap-2 rounded-[7px] border border-border bg-transparent px-3 py-1.5 text-xs text-text-secondary/70 hover:text-text-secondary hover:border-text-secondary/50 transition-colors cursor-pointer"
          >
            <Search className="h-3.5 w-3.5" />
            <span>Search</span>
            <kbd className="rounded border border-border/60 px-1 py-0.5 font-mono text-[9px] text-text-secondary/30">⌘K</kbd>
          </button>

          {/* Bell */}
          <div className="relative" ref={panelRef}>
            <button
              onClick={handleOpen}
            className="relative flex h-[34px] w-[34px] items-center justify-center rounded-[7px] text-text-secondary transition-colors hover:bg-drop-zone hover:text-text-primary cursor-pointer"
              aria-label="Notifications"
            >
              <Bell className="h-4 w-4" />
              {unreadCount > 0 && (
                <span className="absolute top-1 right-1 flex h-4 w-4 items-center justify-center rounded-full bg-accent text-[9px] font-bold text-white leading-none">
                  {unreadCount > 9 ? "9+" : unreadCount}
                </span>
              )}
            </button>

            {open && (
              <div className="absolute right-0 top-full mt-2 w-80 rounded-2xl border border-border bg-surface shadow-xl shadow-black/20 overflow-hidden z-50">
                {/* Panel header */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-border/60">
                  <p className="text-xs font-bold uppercase tracking-widest text-text-secondary/50">
                    Notifications
                  </p>
                  {notifications.length > 0 && (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={markAllRead}
                        title="Mark all read"
                        className="flex h-6 w-6 items-center justify-center rounded-md text-text-secondary/40 hover:text-text-secondary transition-colors cursor-pointer"
                      >
                        <CheckCheck className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={clearAll}
                        title="Clear all"
                        className="flex h-6 w-6 items-center justify-center rounded-md text-text-secondary/40 hover:text-risk-high transition-colors cursor-pointer"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </div>

                {/* Notification list */}
                <div className="max-h-80 overflow-y-auto">
                  {notifications.length === 0 ? (
                    <div className="py-10 text-center">
                      <Bell className="h-5 w-5 text-text-secondary/20 mx-auto mb-2" />
                      <p className="text-xs text-text-secondary/40">No notifications</p>
                    </div>
                  ) : (
                    notifications.map((n) => (
                      <div
                        key={n.id}
                        className={cn(
                          "group flex items-start gap-3 px-4 py-3.5 border-b border-border/40 last:border-0 transition-colors",
                          n.contractId || n.runId ? "cursor-pointer hover:bg-drop-zone/30" : "cursor-default",
                          !n.read && "bg-accent/[0.04]"
                        )}
                        onClick={() => {
                          if (n.contractId || n.runId) {
                            onNotificationClick?.(n);
                            setOpen(false);
                          }
                        }}
                      >
                        <div className="mt-0.5">
                          <NotificationIcon type={n.type} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-semibold text-text-primary leading-snug">{n.title}</p>
                          <p className="text-xs text-text-secondary/60 mt-0.5 leading-relaxed">{n.body}</p>
                          <p className="text-[10px] text-text-secondary/30 mt-1">{timeAgo(n.createdAt)}</p>
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); remove(n.id); }}
                          className="shrink-0 opacity-0 group-hover:opacity-100 text-text-secondary/30 hover:text-text-secondary transition-all cursor-pointer mt-0.5"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          <button
            onClick={toggle}
            className="flex h-[34px] w-[34px] items-center justify-center rounded-[7px] text-text-secondary transition-colors hover:bg-drop-zone hover:text-text-primary cursor-pointer"
            aria-label="Toggle theme"
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>

          {user && (
            <div className="flex items-center gap-2">
              {user.org_role === "org_admin" && (
                <button
                  onClick={onAdmin}
                  title="Admin Panel"
                  className={cn(
                    "flex h-[34px] w-[34px] items-center justify-center rounded-[7px] transition-colors cursor-pointer hover:bg-drop-zone",
                    activePage === "Admin"
                      ? "text-accent"
                      : "text-text-secondary hover:text-text-primary"
                  )}
                >
                  <Settings className="h-4 w-4" />
                </button>
              )}
              {/* User avatar */}
              <button
                onClick={onProfile}
                title="Your profile"
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full text-[10px] font-bold text-white transition-opacity hover:opacity-80 cursor-pointer shrink-0",
                  activePage === "Profile" && "ring-2 ring-accent ring-offset-1 ring-offset-background"
                )}
                style={{ backgroundColor: user?.avatar_color ?? "#6366f1" }}
              >
                {initials(user?.display_name ?? "U")}
              </button>

              <button
                onClick={logout}
                title="Sign out"
                className="flex h-[34px] w-[34px] items-center justify-center rounded-[7px] text-text-secondary transition-colors hover:bg-drop-zone hover:text-risk-high cursor-pointer"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
