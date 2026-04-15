export default function Footer() {
  return (
    <footer className="mt-24">
      <div className="mx-auto max-w-[1440px] px-6 sm:px-10 lg:px-14 py-6 border-t border-border/40">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-xs text-text-secondary/50 tracking-wide">
            &copy; 2024 VERIDICT INTELLIGENCE
          </p>
          <div className="flex items-center gap-6 text-xs font-medium uppercase tracking-widest text-text-secondary/50">
            <a href="#" className="hover:text-text-primary transition-colors">
              Terms
            </a>
            <a href="#" className="hover:text-text-primary transition-colors">
              Privacy
            </a>
            <a href="#" className="hover:text-text-primary transition-colors">
              Support
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
