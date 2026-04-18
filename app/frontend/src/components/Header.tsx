import { Moon, Sun, Plus, LogOut, Settings } from "lucide-react";
import { useTheme } from "@/lib/useTheme";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

interface HeaderProps {
  activePage?: "Dashboard" | "History" | "Admin";
  onNavigate?: (page: "Dashboard" | "History") => void;
  onNewContract?: () => void;
  onAdmin?: () => void;
}

export default function Header({ activePage = "Dashboard", onNavigate, onNewContract, onAdmin }: HeaderProps) {
  const { dark, toggle } = useTheme();
  const { user, logout } = useAuth();

  const NAV_ITEMS: Array<{ label: string; page: "Dashboard" | "History" }> = [
    { label: "Dashboard", page: "Dashboard" },
    { label: "History", page: "History" },
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-surface/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1440px] items-center justify-between px-6 sm:px-10 lg:px-14 py-4">
        <div className="flex items-center gap-8">
          <button
            onClick={() => onNavigate?.("Dashboard")}
            className="font-serif text-xl font-bold italic tracking-tight text-accent cursor-pointer hover:opacity-80 transition-opacity"
          >
            Veridict
          </button>
          <nav className="hidden sm:flex items-center gap-6">
            {NAV_ITEMS.map(({ label, page }) => (
              <button
                key={page}
                onClick={() => onNavigate?.(page)}
                className={cn(
                  "text-sm font-medium transition-colors pb-0.5 cursor-pointer",
                  page === activePage
                    ? "text-text-primary border-b-2 border-accent"
                    : "text-text-secondary hover:text-text-primary"
                )}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {onNewContract && (
            <button
              onClick={onNewContract}
              className="hidden sm:flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-white hover:bg-accent-hover transition-colors cursor-pointer"
            >
              <Plus className="h-3.5 w-3.5" />
              New Contract
            </button>
          )}
          <button
            onClick={toggle}
            className="flex h-9 w-9 items-center justify-center rounded-full text-text-secondary transition-colors hover:text-text-primary cursor-pointer"
            aria-label="Toggle theme"
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          {user && (
            <div className="flex items-center gap-2">
              <span className="hidden sm:block text-xs font-medium text-text-secondary">
                {user.display_name}
              </span>
              {user.org_role === "org_admin" && (
                <button
                  onClick={onAdmin}
                  title="Admin Panel"
                  className={cn(
                    "flex h-9 w-9 items-center justify-center rounded-full transition-colors cursor-pointer",
                    activePage === "Admin"
                      ? "text-accent"
                      : "text-text-secondary hover:text-text-primary"
                  )}
                >
                  <Settings className="h-4 w-4" />
                </button>
              )}
              <button
                onClick={logout}
                title="Sign out"
                className="flex h-9 w-9 items-center justify-center rounded-full text-text-secondary transition-colors hover:text-risk-high cursor-pointer"
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
