import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu, LockKeyhole, RadioTower, ShieldCheck, SlidersHorizontal, ThermometerSnowflake } from "lucide-react";
import { useOutletContext } from "react-router-dom";
import { MetricCard } from "../components/MetricCard";
import { Panel } from "../components/Panel";
import { ProcessOutput } from "../components/ProcessOutput";
import { RoleGate } from "../components/RoleGate";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n/I18nProvider";
import { api } from "../lib/api";
import { useStateStream } from "../lib/hooks";
import type { CurrentUser } from "../lib/types";

export function EngineeringPage() {
  const { user } = useOutletContext<{ user?: CurrentUser }>();
  const { t, formatUtc } = useI18n();
  const instrument = useQuery({ queryKey: ["instrument"], queryFn: api.instrument, refetchInterval: 1000 });
  const alarms = useQuery({ queryKey: ["alarms"], queryFn: api.alarms, refetchInterval: 1500 });
  const stream = useStateStream();
  const devices = instrument.data?.devices ?? {};
  const temperature = typeof devices.temperature_c === "number" ? devices.temperature_c : undefined;
  const interlockSafe = devices.interlock_safe === true;
  const guiderLocked = devices.guider_locked === true;
  const cards = [
    { title: t("engineering.device.title"), heading: t("engineering.device.heading"), copy: t("engineering.device.copy"), icon: RadioTower, status: "SIMULATION_ONLY" },
    { title: t("engineering.interlock.title"), heading: t("engineering.interlock.heading"), copy: t("engineering.interlock.copy"), icon: SlidersHorizontal, status: "READ_ONLY" },
    { title: t("engineering.boundary.title"), heading: t("engineering.boundary.heading"), copy: t("engineering.boundary.copy"), icon: Cpu, status: "NO HARDWARE" },
    { title: t("engineering.audit.title"), heading: t("engineering.audit.heading"), copy: t("engineering.audit.copy"), icon: LockKeyhole, status: "ENABLED" },
  ];
  return (
    <RoleGate user={user} allowed={["instrument_engineer"]}>
      <div className="page">
        <div className="page-heading"><div><p className="eyebrow">{t("engineering.eyebrow")}</p><h1>{t("engineering.title")}</h1><p>{t("engineering.subtitle")}</p></div><StatusBadge value="SIMULATION_ONLY" /></div>
        <div className="metric-grid">
          <MetricCard icon={<Activity size={20} />} label={t("engineering.metric.control")} value={instrument.data?.state ?? "OFFLINE"} detail={instrument.data ? t("common.updated", { time: formatUtc(instrument.data.observed_at, true) }) : t("common.loading")} status={instrument.data?.fresh ? "FRESH" : "STALE"} stale={!instrument.data?.fresh} />
          <MetricCard icon={<ShieldCheck size={20} />} label={t("engineering.metric.interlock")} value={interlockSafe ? "SAFE" : "BLOCKED"} detail={t("engineering.metric.interlockCopy")} status={interlockSafe ? "SAFE" : "BLOCKED"} />
          <MetricCard icon={<RadioTower size={20} />} label={t("engineering.metric.guider")} value={guiderLocked ? "LOCKED" : "UNLOCKED"} detail={t("engineering.metric.guiderCopy")} status={guiderLocked ? "LOCKED" : "WARNING"} />
          <MetricCard icon={<ThermometerSnowflake size={20} />} label={t("engineering.metric.environment")} value={temperature === undefined ? "— °C" : `${temperature.toFixed(1)} °C`} detail={t("engineering.metric.environmentCopy")} status={temperature === undefined ? "STALE" : "FRESH"} stale={temperature === undefined} />
        </div>
        <div className="engineering-live-grid">
          <Panel title={t("engineering.output.title")} eyebrow={t("engineering.output.eyebrow")} className="engineering-output-panel">
            <ProcessOutput events={stream.events} connected={stream.connected} metrics={[{ label: "CONTROL", value: instrument.data?.state ?? "OFFLINE" }, { label: "FENCE", value: String(instrument.data?.fencing_token ?? "—") }, { label: "ALARMS", value: String(alarms.data?.length ?? 0) }]} emptyLabel={t("engineering.output.empty")} />
          </Panel>
          <Panel title={t("engineering.snapshot.title")} eyebrow={t("engineering.snapshot.eyebrow")} className="engineering-snapshot-panel" action={<StatusBadge value={instrument.data?.fresh ? "FRESH" : "STALE"} subtle />}>
            <div className="engineering-snapshot-list">
              <div><span>TCS / CONTROL</span><strong>{instrument.data?.state ?? "—"}</strong></div>
              <div><span>FR1 / FR3</span><strong>{String(devices.fr1_deg ?? "—")}° / {String(devices.fr3_deg ?? "—")}°</strong></div>
              <div><span>OPTICAL MODE</span><strong>{String(devices.optical_mode ?? "—")}</strong></div>
              <div><span>INTERLOCK</span><StatusBadge value={interlockSafe ? "SAFE" : "BLOCKED"} subtle /></div>
              <div><span>GUIDER</span><StatusBadge value={guiderLocked ? "LOCKED" : "UNLOCKED"} subtle /></div>
              <div><span>ACTIVE ALARMS</span><strong>{alarms.data?.length ?? 0}</strong></div>
            </div>
          </Panel>
        </div>
        <div className="skeleton-grid">
          {cards.map(({ title, heading, copy, icon: Icon, status }) => <Panel key={title} title={title} action={<StatusBadge value={status} subtle />}><div className="route-skeleton"><Icon size={26} /><strong>{heading}</strong><p>{copy}</p></div></Panel>)}
        </div>
      </div>
    </RoleGate>
  );
}
