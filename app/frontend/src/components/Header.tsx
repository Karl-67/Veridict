import { Scale } from "lucide-react";

export default function Header() {
  return (
    <header className="sticky top-0 z-50 border-b border-border backdrop-blur-xl bg-surface/80">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <div className="flex items-center gap-2.5">
          <Scale className="h-6 w-6 text-primary" />
          <span className="text-xl font-bold tracking-tight text-text-primary">
            Veridict
          </span>
        </div>
        <span className="text-sm text-text-muted">AI Contract Review</span>
      </div>
    </header>
  );
}
