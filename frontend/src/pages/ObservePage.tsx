import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CircleStop,
  Crosshair,
  HardDrive,
  Pause,
  RotateCw,
  Satellite,
  ShieldCheck,
  Sparkles,
  ThermometerSnowflake,
} from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Heatmap } from "../components/Heatmap";
import { MetricCard } from "../components/MetricCard";
import { Panel } from "../components/Panel";
import { ProcessOutput } from "../components/ProcessOutput";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n/I18nProvider";
import { api } from "../lib/api";
import { useStateStream } from "../lib/hooks";
import type { DataMode, SequencePayload } from "../lib/types";

export function ObservePage() {
  const queryClient = useQueryClient();
  const { t, formatUtc } = useI18n();
  const [form, setForm] = useState<SequencePayload>({ target_name: "AD Leo (SIM)", mode: "POL_Q", exposure_time: 1, repeats: 1 });
  const [sequenceId, setSequenceId] = useState<string>();
  const [abortOpen, setAbortOpen] = useState(false);

  const validation = useQuery({
    queryKey: ["sequence-validation", form],
    queryFn: () => api.validateSequence(form),
    enabled: form.target_name.trim().length > 0 && form.exposure_time > 0,
  });
  const instrument = useQuery({ queryKey: ["instrument"], queryFn: api.instrument, refetchInterval: 1000 });
  const sequence = useQuery({ queryKey: ["sequence", sequenceId], queryFn: () => api.sequence(sequenceId!), enabled: Boolean(sequenceId), refetchInterval: 700 });
  const exposures = useQuery({ queryKey: ["exposures", sequenceId], queryFn: () => api.exposures(sequenceId!), enabled: Boolean(sequenceId), refetchInterval: 700 });
  const products = useQuery({ queryKey: ["products", sequenceId], queryFn: () => api.products(sequenceId), enabled: Boolean(sequenceId), refetchInterval: 1000 });
  const alarms = useQuery({ queryKey: ["alarms"], queryFn: api.alarms, refetchInterval: 1500 });
  const quicklookProduct = products.data?.find((product) => product.level === "QUICKLOOK");
  const quicklook = useQuery({ queryKey: ["preview", quicklookProduct?.id], queryFn: () => api.preview(quicklookProduct!.id), enabled: Boolean(quicklookProduct), refetchInterval: false });
  const stream = useStateStream(sequenceId);

  const create = useMutation({
    mutationFn: async () => {
      const accepted = await api.createSequence(form);
      if (!accepted.resource_id) throw new Error(t("observe.missingResource"));
      setSequenceId(accepted.resource_id);
      await api.sequenceAction(accepted.resource_id, "start");
      return accepted.resource_id;
    },
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const action = useMutation({
    mutationFn: (value: "pause" | "resume" | "abort") => api.sequenceAction(sequenceId!, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sequence", sequenceId] }),
  });

  const activeMode: DataMode = sequence.data?.mode ?? form.mode;
  const expected = sequence.data?.expected_exposures ?? (activeMode === "NONPOL" ? form.repeats : form.repeats * 4);
  const slots = useMemo(
    () => Array.from({ length: expected }, (_, index) => exposures.data?.find((item) => item.sub_index === index + 1)),
    [expected, exposures.data],
  );
  const completed = sequence.data?.completed_exposures ?? 0;
  const progress = sequence.data ? completed / Math.max(1, sequence.data.expected_exposures) : 0;
  const currentAlarm = alarms.data?.[0];
  const devices = instrument.data?.devices ?? {};
  const faults = typeof devices.faults === "object" && devices.faults !== null ? devices.faults as Record<string, unknown> : {};
  const storageFault = Boolean(faults.DISK_FULL || faults.NAS_UNAVAILABLE);
  const guiderLocked = devices.guider_locked === true;
  const interlockSafe = devices.interlock_safe === true;
  const ccdTemperature = typeof devices.ccd_temperature_c === "number" ? devices.ccd_temperature_c : undefined;
  const safetyItems = [
    { label: t("observe.safety.telemetry"), status: instrument.data?.fresh ? "FRESH" : "STALE", ready: Boolean(instrument.data?.fresh) },
    { label: t("observe.safety.interlock"), status: interlockSafe ? "SAFE" : "BLOCKED", ready: interlockSafe },
    { label: t("observe.safety.guider"), status: guiderLocked ? "LOCKED" : "UNLOCKED", ready: guiderLocked },
    { label: t("observe.safety.storage"), status: storageFault ? "BLOCKED" : "SAFE", ready: !storageFault },
    { label: t("observe.safety.configuration"), status: "UNVERIFIED", ready: false },
  ];
  const safetyReady = safetyItems.filter((item) => item.ready).length;
  const alarmMessage = currentAlarm?.reason_code === "NOT_INITIALIZED" ? t("observe.events.reasonNotInitialized") : currentAlarm?.message;
  const protectiveAction = currentAlarm?.protective_action === "close shutter and stop simulated motion" ? t("observe.events.protectiveDefault") : currentAlarm?.protective_action;
  const recoveryCondition = currentAlarm?.recovery_condition === "clear fault and request authorized recovery" ? t("observe.events.recoveryDefault") : currentAlarm?.recovery_condition;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (validation.data?.valid) create.mutate();
  };
  const validationTitle = validation.data
    ? validation.data.valid ? t("observe.validation.passed") : t("observe.validation.blocked")
    : t("observe.validation.checking");

  return (
    <div className="page observe-page">
      <div className="page-heading">
        <div><p className="eyebrow">{t("observe.eyebrow")}</p><h1>{t("observe.title")}</h1><p>{t("observe.subtitle")}</p></div>
        <div className="heading-state" data-testid="sequence-status" aria-live="polite">
          {sequence.data && <code className="sequence-reference">SEQ · {sequence.data.id.slice(0, 8)}</code>}
          <StatusBadge value={sequence.data?.status ?? t("observe.noSequence")} />
          <span>{sequence.data ? t("observe.submitted", { done: completed, total: sequence.data.expected_exposures }) : t("observe.notStarted")}</span>
        </div>
      </div>

      <div className="metric-grid">
        <MetricCard icon={<Satellite size={20} />} label={t("observe.metric.instrument")} value={instrument.data?.state ?? "OFFLINE"} detail={t("observe.metric.instrumentDetail")} status={instrument.data?.fresh ? "FRESH" : "STALE"} stale={!instrument.data?.fresh} />
        <MetricCard icon={<Crosshair size={20} />} label={t("observe.metric.guider")} value={guiderLocked ? "LOCKED" : "UNLOCKED"} detail={guiderLocked ? t("observe.metric.guiderLocked") : t("observe.metric.guiderUnlocked")} status={guiderLocked ? "LOCKED" : "WARNING"} />
        <MetricCard icon={<ThermometerSnowflake size={20} />} label={t("observe.metric.ccd")} value={ccdTemperature === undefined ? "— °C" : `${ccdTemperature.toFixed(1)} °C`} detail={ccdTemperature === undefined ? t("observe.metric.ccdMissing") : t("common.updated", { time: instrument.data ? formatUtc(instrument.data.observed_at, true) : "—" })} status={ccdTemperature === undefined ? "STALE" : "FRESH"} stale={ccdTemperature === undefined} />
        <MetricCard icon={<HardDrive size={20} />} label={t("observe.metric.storage")} value={storageFault ? "BLOCKED" : "MONITORED"} detail={storageFault ? t("observe.metric.storageFault") : t("observe.metric.storageNominal")} status={storageFault ? "BLOCKED" : "SAFE"} />
      </div>

      <div className="observe-grid">
        <Panel title={t("observe.setup.title")} eyebrow={t("observe.setup.eyebrow")} className="setup-panel">
          <form onSubmit={submit} className="observe-form" data-testid="observe-form">
            <label>{t("observe.setup.target")}<input value={form.target_name} onChange={(event) => setForm({ ...form, target_name: event.target.value })} disabled={create.isPending} /></label>
            <div className="field-row">
              <label>{t("observe.setup.mode")}<select value={form.mode} onChange={(event) => setForm({ ...form, mode: event.target.value as DataMode })} disabled={create.isPending} data-testid="mode-select"><option value="POL_Q">{t("observe.setup.polQ")}</option><option value="NONPOL">{t("observe.setup.nonpol")}</option></select></label>
              <label>{t("observe.setup.repeats")}<input type="number" min="1" max="100" value={form.repeats} onChange={(event) => setForm({ ...form, repeats: Number(event.target.value) })} /></label>
            </div>
            <label>{t("observe.setup.exposure")} <span>{form.exposure_time.toFixed(1)} s</span><input type="range" min="0.1" max="60" step="0.1" value={form.exposure_time} onChange={(event) => setForm({ ...form, exposure_time: Number(event.target.value) })} /></label>
            <div className="validation-box">
              <div><span className="validation-icon">{validation.data?.valid ? <Check size={16} /> : <AlertTriangle size={16} />}</span><div><strong>{validationTitle}</strong><small>{validation.data ? t("observe.validation.estimate", { frames: validation.data.estimated_exposures, duration: validation.data.estimated_duration.toFixed(1) }) : t("observe.validation.pending")}</small></div></div>
              {validation.data?.issues.map((issue) => <p key={issue.code} className={issue.blocking ? "issue-blocking" : "issue-info"}><code>{issue.code}</code> · {issue.code === "UNVERIFIED_CONFIGURATION" ? t("observe.validation.unverified") : issue.message}</p>)}
            </div>
            <button className="button button-primary button-wide" type="submit" disabled={!validation.data?.valid || create.isPending || ["QUEUED", "RUNNING"].includes(sequence.data?.status ?? "")} data-testid="start-sequence"><Sparkles size={17} />{create.isPending ? t("observe.submitting") : t("observe.start")}</button>
            {create.error && <p className="form-error">{create.error.message}</p>}
          </form>
        </Panel>

        <Panel title={activeMode === "NONPOL" ? t("observe.sequence.nonpolTitle") : t("observe.sequence.polTitle")} eyebrow={t("observe.sequence.eyebrow")} className="sequence-panel" action={<span className={`socket-state ${stream.connected ? "connected" : ""}`}>{stream.connected ? t("observe.sequence.online") : t("observe.sequence.reconnecting")}</span>}>
          <div className="progress-summary" data-testid="sequence-progress">
            <div><strong>{t("observe.sequence.ratio", { done: String(completed).padStart(2, "0"), total: String(expected).padStart(2, "0") })}</strong><span>{t("observe.sequence.progress")}</span></div>
            <div><div className="progress-track"><i style={{ width: `${progress * 100}%` }} /></div><b>{Math.round(progress * 100)}%</b></div>
          </div>
          <div className={`exposure-slots ${activeMode === "NONPOL" ? "single-slot" : ""}`}>
            {slots.map((exposure, index) => (
              <article className={`exposure-card exposure-${exposure?.status.toLowerCase() ?? "pending"}`} key={index} data-testid={`exposure-${index + 1}`}>
                <header><span>{String(index + 1).padStart(2, "0")}</span><StatusBadge value={exposure?.status ?? "PENDING"} subtle /></header>
                {activeMode === "NONPOL" ? <div className="channel-map"><b>TARGET</b><b>SKY</b><b className="disabled-channel">DISABLED</b></div> : <dl><div><dt>FR1 · CMD / ACT</dt><dd>{exposure?.fr1_commanded?.toFixed(1) ?? "—"}° / {exposure?.fr1_measured?.toFixed(3) ?? "—"}°</dd></div><div><dt>FR3 · CMD / ACT</dt><dd>{exposure?.fr3_commanded?.toFixed(1) ?? "—"}° / {exposure?.fr3_measured?.toFixed(3) ?? "—"}°</dd></div></dl>}
                <small>{exposure?.raw_file_id ? `L0 · ${exposure.raw_file_id.slice(0, 8)}` : t("observe.sequence.waitingBoundary")}</small>
                {exposure?.committed_at && <time>{exposure.committed_at.slice(11, 19)} UTC</time>}
              </article>
            ))}
          </div>
          <div className="sequence-controls">
            <button type="button" className="button button-secondary" disabled={!sequenceId || sequence.data?.status !== "RUNNING" || action.isPending} onClick={() => action.mutate("pause")}><Pause size={16} />{t("observe.sequence.pause")}</button>
            <button type="button" className="button button-secondary" disabled={!sequenceId || !["PAUSED", "FAILED"].includes(sequence.data?.status ?? "") || action.isPending} onClick={() => action.mutate("resume")}><RotateCw size={16} />{t("observe.sequence.resume")}</button>
            <button type="button" className="button button-danger" disabled={!sequenceId || !["QUEUED", "RUNNING", "PAUSED"].includes(sequence.data?.status ?? "") || action.isPending} onClick={() => setAbortOpen(true)}><CircleStop size={16} />{t("observe.sequence.abort")}</button>
          </div>
          {sequence.data?.last_error_code && <div className="inline-alarm"><AlertTriangle size={17} /><div><strong>{sequence.data.last_error_code}</strong><span>{sequence.data.last_error_message}</span></div></div>}
        </Panel>

        <Panel title={t("observe.instrument.title")} eyebrow={t("observe.instrument.eyebrow")} className="devices-panel" action={<span className="safety-count">{t("observe.safety.nominalCount", { ready: safetyReady, total: safetyItems.length })}</span>}>
          <div className="device-list">
            <div><Satellite size={17} /><span>{t("observe.instrument.control")}</span><StatusBadge value={instrument.data?.state ?? "OFFLINE"} subtle /></div>
            <div><span className="device-glyph">G</span><span>{t("observe.instrument.guider")}</span><StatusBadge value={guiderLocked ? "LOCKED" : "UNLOCKED"} subtle /></div>
            <div><span className="device-glyph">FR</span><span>{t("observe.instrument.fr")}</span><strong>{String(devices.fr1_deg ?? "—")}° / {String(devices.fr3_deg ?? "—")}°</strong></div>
            <div><span className="device-glyph">Ω</span><span>{t("observe.instrument.optics")}</span><strong>{String(devices.optical_mode ?? "STANDBY")}</strong></div>
            <div><span className="device-glyph">T</span><span>{t("observe.instrument.environment")}</span><strong>{String(devices.temperature_c ?? "—")} °C · {String(devices.humidity_percent ?? "—")} %</strong></div>
          </div>
          <div className="safety-list">
            {safetyItems.map((item) => <div key={item.label}><ShieldCheck size={14} /><span>{item.label}</span><StatusBadge value={item.status} subtle /></div>)}
          </div>
          <div className="target-state"><p>{t("observe.instrument.currentTarget")}</p><strong>{sequence.data?.target_name ?? form.target_name}</strong><span>{activeMode === "NONPOL" ? t("observe.instrument.nonpolMapping") : t("observe.instrument.polMapping")}</span></div>
        </Panel>

        <Panel title={t("observe.quicklook.title")} eyebrow={t("observe.quicklook.eyebrow")} className="quicklook-panel" action={quicklook.data?.shape && <span>{quicklook.data.shape.join(" × ")}</span>}>
          <Heatmap values={quicklook.data?.image} emptyLabel={t("observe.quicklook.empty")} scaleLabel={t("observe.quicklook.scale")} unit={t("observe.quicklook.unit")} />
          <div className="quicklook-metrics"><span>MIN <b>{quicklook.data?.minimum?.toFixed(0) ?? "—"}</b></span><span>MEDIAN <b>{quicklook.data?.median?.toFixed(0) ?? "—"}</b></span><span>MAX <b>{quicklook.data?.maximum?.toFixed(0) ?? "—"}</b></span><span>SAT <b>{quicklook.data ? `${((quicklook.data.saturated_fraction ?? 0) * 100).toFixed(3)} %` : "—"}</b></span></div>
        </Panel>

        <Panel title={t("observe.events.title")} eyebrow={t("observe.events.eyebrow")} className="events-panel">
          {currentAlarm ? <div className="alarm-card"><AlertTriangle size={20} /><div><header><StatusBadge value={currentAlarm.severity} subtle /><strong>{currentAlarm.reason_code}</strong><StatusBadge value={currentAlarm.acknowledged ? "ACKNOWLEDGED" : "UNACKNOWLEDGED"} subtle /></header><p>{alarmMessage}</p><dl><div><dt>{t("observe.events.protectiveAction")}</dt><dd>{protectiveAction}</dd></div><div><dt>{t("observe.events.recovery")}</dt><dd>{recoveryCondition}</dd></div><div><dt>{t("observe.events.firstSeen")}</dt><dd>{formatUtc(currentAlarm.created_at, true)} UTC</dd></div></dl></div></div> : <div className="no-alarm"><ShieldCheck size={16} />{t("observe.events.noAlarm")}</div>}
          <div data-testid="event-log"><ProcessOutput events={stream.events} connected={stream.connected} metrics={[{ label: "SEQUENCE", value: sequence.data?.status ?? "IDLE" }, { label: "EXPOSURES", value: `${completed} / ${expected}` }, { label: "L0", value: String(exposures.data?.filter((item) => item.raw_file_id).length ?? 0) }]} emptyLabel={t("observe.events.empty")} /></div>
        </Panel>
      </div>

      <ConfirmDialog open={abortOpen} title={t("observe.abort.title")} description={t("observe.abort.description")} confirmLabel={t("observe.abort.confirm")} onCancel={() => setAbortOpen(false)} onConfirm={() => { setAbortOpen(false); action.mutate("abort"); }} />
    </div>
  );
}
