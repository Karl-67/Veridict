const METHODS = [
  {
    step: 1,
    title: "Document Ingestion",
    description:
      "OCR and structural mapping. Our engine converts the PDF into a searchable semantic map, identifying headers and hierarchy.",
  },
  {
    step: 2,
    title: "Clause Extraction",
    description:
      "Named Entity Recognition (NER) identifies 80+ standard clause types from Limitation of Liability to Non-Compete sections.",
  },
  {
    step: 3,
    title: "Risk Assessment",
    description:
      "Large Language Model comparison against 50k+ legal precedents to flag deviation from market-standard terms and risky phrasing.",
  },
  {
    step: 4,
    title: "Finalizing Verdict",
    description:
      "Executive summary generation. We synthesize findings into a prioritized action list of green, yellow, and red flags.",
  },
];

export default function PipelineMethodology() {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-widest text-text-secondary text-center mb-6">
        Pipeline Methodology
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-6">
        {METHODS.map((m) => (
          <div key={m.step}>
            <h4 className="text-sm font-bold text-text-primary mb-1">
              {m.step}. {m.title}
            </h4>
            <p className="text-sm leading-relaxed text-text-secondary">
              {m.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
