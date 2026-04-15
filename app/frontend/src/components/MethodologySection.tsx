import { Puzzle, MapPin, Sparkles } from "lucide-react";

const STEPS = [
  {
    icon: Puzzle,
    title: "Structural Auditing",
    description:
      "Our engine decomposes complex clauses into actionable risk scores, ensuring no hidden liabilities remain unaddressed.",
  },
  {
    icon: MapPin,
    title: "Contextual Intelligence",
    description:
      "We cross-reference legal precedents and industry standards to provide context that goes beyond the text on the page.",
  },
  {
    icon: Sparkles,
    title: "Bespoke Reporting",
    description:
      "Receive a tailored executive summary highlighting critical negotiation points and suggested redline alternatives.",
  },
];

export default function MethodologySection() {
  return (
    <section className="text-center">
      <p className="text-xs font-semibold uppercase tracking-widest text-accent mb-2">
        Our Methodology
      </p>
      <h2 className="font-serif text-3xl font-bold text-text-primary mb-12">
        The Veridict Process
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-x-16 gap-y-0">
        {STEPS.map((step, i) => {
          const Icon = step.icon;
          return (
            <div
              key={step.title}
              className="text-left pt-6 border-t border-border md:pr-10 md:last:pr-0"
            >
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[10px] font-bold tracking-widest text-text-secondary/40 uppercase">
                  0{i + 1}
                </span>
                <Icon className="h-4 w-4 text-accent" />
              </div>
              <h3 className="font-serif text-lg font-bold text-text-primary mb-2">
                {step.title}
              </h3>
              <p className="text-sm leading-relaxed text-text-secondary">
                {step.description}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
