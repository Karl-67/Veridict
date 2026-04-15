export default function Footer() {
  return (
    <footer className="border-t border-border bg-surface/50 mt-24">
      <div className="mx-auto max-w-6xl px-6 lg:px-8 py-8">
        <div className="flex flex-col items-center gap-4">
          <div className="flex items-center gap-6 text-xs font-medium uppercase tracking-widest text-text-secondary">
            <a href="#" className="hover:text-text-primary transition-colors">
              Terms of Service
            </a>
            <a href="#" className="hover:text-text-primary transition-colors">
              Privacy Policy
            </a>
            <a href="#" className="hover:text-text-primary transition-colors">
              Contact Support
            </a>
          </div>
          <p className="text-xs text-text-secondary/60 tracking-wide">
            &copy; 2024 VERIDICT INTELLIGENCE. AUTHORITATIVELY BESPOKE.
          </p>
        </div>
      </div>
    </footer>
  );
}
