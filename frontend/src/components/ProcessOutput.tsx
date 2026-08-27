import { Radio, TerminalSquare } from "lucide-react";
import { useI18n } from "../i18n/I18nProvider";
import type { StateEvent } from "../lib/types";

interface ProcessMetric {
  label: string;
  value: string;
}

function payloadSummary(payload?: Record<string, unknown>): string {
  if (!payload) return "event";
  const preferred = ["status", "state", "action", "reason_code", "level", "sub_index", "progress"];
  const selected = preferred
    .filter((key) => payload[key] !== undefined)
    .slice(0, 3)
    .map((key) => `${key}=${String(payload[key])}`);
  if (selected.length) return selected.join(" · ");
  const first = Object.entries(payload).find(([, value]) => ["string", "number", "boolean"].includes(typeof value));
  return first ? `${first[0]}=${String(first[1])}` : "event";
}

export function ProcessOutput({ events, connected, metrics = [], emptyLabel }: { events: StateEvent[]; connected: boolean; metrics?: ProcessMetric[]; emptyLabel?: string }) {
  const { t } = useI18n();
  const recent = events.slice(-12).reverse();

  return (
    <div className="process-output" data-testid="process-output">
      <header className="process-output-header">
        <div><TerminalSquare size={16} /><strong>{t("process.stream")}</strong><span className={`socket-state ${connected ? "connected" : ""}`}>{connected ? t("process.connected") : t("process.reconnecting")}</span></div>
        <code>{t("process.eventCount", { count: events.length })}</code>
      </header>
      {metrics.length > 0 && <dl className="process-metrics">{metrics.map((metric) => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl>}
      <ol className="process-lines">
        {recent.map((event, index) => (
          <li key={event.event_id ?? `${event.cursor}-${index}`}>
            <span className="process-index">{String(event.cursor ?? index + 1).padStart(4, "0")}</span>
            <time>{event.occurred_at.slice(11, 19)}</time>
            <strong>{event.event_type}</strong>
            <code>{payloadSummary(event.payload)}</code>
            <small>{event.sequence_id ? `${t("process.sequence")} ${event.sequence_id.slice(0, 8)}` : t("process.global")}</small>
          </li>
        ))}
        {!recent.length && <li className="process-empty"><Radio size={15} />{emptyLabel ?? t("process.empty")}</li>}
      </ol>
    </div>
  );
}
