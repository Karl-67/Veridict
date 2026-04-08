import { Moon, Sun, User } from "lucide-react";
import { useTheme } from "@/lib/useTheme";
import { cn } from "@/lib/utils";

interface HeaderProps {
  activePage?: string;
}

const NAV_ITEMS = ["Dashboard", "History", "Resources"];

export default function Header({ activePage = "Dashboard" }: HeaderProps) {
  const { dark, toggle } = useTheme();

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-surface/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 lg:px-8 py-4">
        <div className="flex items-center gap-8">
          <span className="font-serif text-xl font-bold italic tracking-tight text-accent">
            Veridict
          </span>
          <nav className="hidden sm:flex items-center gap-6">
            {NAV_ITEMS.map((item) => (
              <a
                key={item}
                href="#"
                className={cn(
                  "text-sm font-medium transition-colors pb-0.5",
                  item === activePage
                    ? "text-text-primary border-b-2 border-accent"
                    : "text-text-secondary hover:text-text-primary"
                )}
              >
                {item}
              </a>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={toggle}
            className="flex h-9 w-9 items-center justify-center rounded-full text-text-secondary transition-colors hover:text-text-primary cursor-pointer"
            aria-label="Toggle theme"
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/15 text-accent">
            <User className="h-4 w-4" />
          </div>
        </div>
      </div>
    </header>
  );
}
