import type React from "react";

export function SummaryFact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="summaryFact">
      {icon}
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}
