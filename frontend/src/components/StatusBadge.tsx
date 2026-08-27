interface StatusBadgeProps {
  value: string;
  subtle?: boolean;
}

const toneFor = (value: string): string => {
  const normalized = value.toUpperCase();
  if (["SUCCEEDED", "COMMITTED", "READY", "PASS", "FRESH", "SAFE", "APPROVED", "HEALTHY", "AVAILABLE"].includes(normalized)) {
    return "good";
  }
  if (["FAILED", "SAFE_FAULT", "FAIL", "SERIOUS", "EMERGENCY", "ABORTED", "BLOCKED"].includes(normalized)) {
    return "bad";
  }
  if (["RUNNING", "EXPOSING", "READING", "QUEUED", "EXECUTING", "LOCKED", "CONNECTED"].includes(normalized)) {
    return "active";
  }
  if (["PAUSED", "PAUSING", "WARNING", "UNVERIFIED", "SIMULATION_ONLY", "STALE", "UNLOCKED", "PARTIAL"].includes(normalized)) {
    return "warn";
  }
  return "neutral";
};

export function StatusBadge({ value, subtle = false }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-${toneFor(value)} ${subtle ? "status-subtle" : ""}`}>
      <span className="status-dot" aria-hidden="true" />
      {value.replaceAll("_", " ")}
    </span>
  );
}
