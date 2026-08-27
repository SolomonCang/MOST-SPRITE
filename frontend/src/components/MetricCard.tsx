import type { ReactNode } from "react";
import { StatusBadge } from "./StatusBadge";

interface MetricCardProps {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  status: string;
  stale?: boolean;
}

export function MetricCard({ icon, label, value, detail, status, stale = false }: MetricCardProps) {
  return (
    <article className={`metric-card ${stale ? "metric-stale" : ""}`}>
      <div className="metric-icon" aria-hidden="true">{icon}</div>
      <div className="metric-copy"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
      <StatusBadge value={status} subtle />
    </article>
  );
}
