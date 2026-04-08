import { Puzzle, MapPin, Sparkles } from "lucide-react";

const CARDS = [
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
      <h2 className="font-serif text-3xl font-bold text-text-primary mb-10">
        The Veridict Process
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {CARDS.map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.title}
              className="rounded-2xl border border-border bg-surface p-6 text-left"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-accent mb-4">
                <Icon className="h-5 w-5" />
              </div>
              <h3 className="font-serif text-lg font-bold text-text-primary mb-2">
                {card.title}
              </h3>
              <p className="text-sm leading-relaxed text-text-secondary">
                {card.description}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
