import { ShieldCheck, Lock } from "lucide-react";

const BADGES = [
  { icon: ShieldCheck, label: "SOC2 TYPE II" },
  { icon: ShieldCheck, label: "GDPR COMPLIANT" },
  { icon: Lock, label: "END-TO-END ENCRYPTION" },
];

export default function TrustSecurity() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-6 lg:p-8">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
        <div>
          <h3 className="font-serif text-xl font-bold text-text-primary mb-1">
            Trust &amp; Security
          </h3>
          <p className="text-sm text-text-secondary max-w-xs">
            Your intellectual property is protected by institutional-grade
            protocols.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {BADGES.map((badge) => {
            const Icon = badge.icon;
            return (
              <div
                key={badge.label}
                className="flex items-center gap-2 rounded-full border border-border bg-background px-4 py-2 text-xs font-semibold tracking-wide text-text-primary"
              >
                <Icon className="h-3.5 w-3.5 text-accent" />
                {badge.label}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
