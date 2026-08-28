import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  DatabaseZap,
  FileCheck2,
  FolderSearch2,
  Gauge,
  Play,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useI18n } from "../i18n/I18nProvider";
import { ApiError, api } from "../lib/api";
import type {
  CalibrationSet,
  CurrentUser,
  ImportInspection,
  Sequence,
} from "../lib/types";
import { Heatmap } from "./Heatmap";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

interface WizardProps {
  user?: CurrentUser;
  onSequenceSelect?: (sequenceId: string) => void;
}

type Counts = Record<string, number>;

export function countInventory(inventory: Array<Record<string, unknown>>): Counts {
  return inventory.reduce<Counts>((counts, item) => {
    const role = typeof item.role === "string" ? item.role : "UNKNOWN";
    counts[role] = (counts[role] ?? 0) + 1;
    return counts;
  }, {});
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return `${error.body.code}: ${error.body.message}`;
  return error instanceof Error ? error.message : String(error);
}

function numberMetric(value: unknown, digits = 4): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function groupLabel(group: Record<string, unknown>): string {
  const mode = typeof group.mode === "string" ? group.mode : "POL";
  const target = typeof group.target_name === "string" ? group.target_name : "UNKNOWN";
  const artifacts = Array.isArray(group.artifacts) ? group.artifacts.length : 0;
  return `${mode} · ${target} · ${artifacts}/4`;
}

function CalibrationMetrics({ calibrationSet }: { calibrationSet: CalibrationSet }) {
  const wavelength = (
    calibrationSet.qc.wavelength && typeof calibrationSet.qc.wavelength === "object"
      ? calibrationSet.qc.wavelength
      : {}
  ) as Record<string, unknown>;
  return (
    <dl className="wizard-metrics">
      <div><dt>TRACE RMS</dt><dd>{numberMetric(calibrationSet.qc.trace_rms_pixel)} px</dd></div>
      <div><dt>WAVE RMS</dt><dd>{numberMetric(wavelength.wavelength_rms_m_s ?? wavelength.rms_ms, 1)} m/s</dd></div>
      <div><dt>ALIGNMENT</dt><dd>{numberMetric(calibrationSet.qc.alignment_valid_fraction, 3)}</dd></div>
      <div><dt>QC</dt><dd><StatusBadge value={calibrationSet.qc_flag} subtle /></dd></div>
    </dl>
  );
}

export function ESPaDOnSImportWizard({ user, onSequenceSelect }: WizardProps) {
  const { t, formatUtc } = useI18n();
  const queryClient = useQueryClient();
  const canReduce = user?.role === "data_reducer" || user?.role === "administrator";
  const isAdministrator = user?.role === "administrator";
  const [rootId, setRootId] = useState("");
  const [relativePath, setRelativePath] = useState(".");
  const [parameterVersion, setParameterVersion] = useState("espadons-olapa-v1");
  const [inspectionId, setInspectionId] = useState<string>();
  const [previewPath, setPreviewPath] = useState<string>();
  const [selectedSequenceIds, setSelectedSequenceIds] = useState<string[]>([]);
  const [approvalReason, setApprovalReason] = useState("");
  const [acceptWarnings, setAcceptWarnings] = useState(false);

  const inspections = useQuery({
    queryKey: ["import-inspections"],
    queryFn: api.importInspections,
    enabled: Boolean(user),
    refetchInterval: 2500,
  });
  const imports = useQuery({
    queryKey: ["imports"],
    queryFn: api.imports,
    enabled: Boolean(user),
    refetchInterval: 2500,
  });
  const calibrationRuns = useQuery({
    queryKey: ["calibration-runs"],
    queryFn: api.calibrationRuns,
    enabled: Boolean(user),
    refetchInterval: 2500,
  });
  const calibrationSets = useQuery({
    queryKey: ["calibration-sets"],
    queryFn: api.calibrationSets,
    enabled: Boolean(user),
    refetchInterval: 2500,
  });
  const sequences = useQuery({
    queryKey: ["sequences"],
    queryFn: api.sequences,
    enabled: Boolean(user),
    refetchInterval: 2500,
  });
  const processingRuns = useQuery({
    queryKey: ["processing-runs"],
    queryFn: api.processingRuns,
    enabled: Boolean(user),
    refetchInterval: 2500,
  });

  useEffect(() => {
    if (!inspectionId && inspections.data?.length) setInspectionId(inspections.data[0].id);
  }, [inspectionId, inspections.data]);

  const inspection = inspections.data?.find((item) => item.id === inspectionId);
  const importBatch = imports.data?.find((item) => item.inspection_id === inspection?.id);
  const calibrationRun = calibrationRuns.data?.find(
    (item) => item.import_batch_id === importBatch?.id,
  );
  const calibrationSet = calibrationSets.data?.find(
    (item) => item.calibration_run_id === calibrationRun?.id,
  );

  useEffect(() => {
    setSelectedSequenceIds(importBatch?.sequence_ids ?? []);
  }, [importBatch?.id]);

  const sequenceById = useMemo(
    () => new Map((sequences.data ?? []).map((item) => [item.id, item])),
    [sequences.data],
  );
  const inventoryCounts = useMemo(
    () => countInventory(inspection?.inventory ?? []),
    [inspection?.inventory],
  );
  const previewArtifacts = useMemo(
    () => (inspection?.inventory ?? []).filter(
      (item): item is Record<string, unknown> & { relative_path: string } =>
        typeof item.relative_path === "string",
    ),
    [inspection?.inventory],
  );
  useEffect(() => {
    setPreviewPath((current) => (
      current && previewArtifacts.some((item) => item.relative_path === current)
        ? current
        : previewArtifacts[0]?.relative_path
    ));
  }, [inspection?.id, previewArtifacts]);
  const selectedArtifact = previewArtifacts.find(
    (item) => item.relative_path === previewPath,
  );
  const artifactPreview = useQuery({
    queryKey: ["import-artifact-preview", inspection?.id, previewPath, calibrationSet?.id],
    queryFn: () => api.importArtifactPreview(inspection!.id, previewPath!),
    enabled: Boolean(inspection?.id && previewPath),
  });
  const processingBySequence = useMemo(() => new Map(
    (processingRuns.data ?? [])
      .filter((item) => !calibrationSet || item.calibration_set_id === calibrationSet.id)
      .map((item) => [item.sequence_id, item]),
  ), [calibrationSet, processingRuns.data]);
  const processingComplete = Boolean(importBatch?.sequence_ids.length)
    && importBatch!.sequence_ids.every(
      (id) => processingBySequence.get(id)?.status === "SUCCEEDED",
    );

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["import-inspections"] }),
      queryClient.invalidateQueries({ queryKey: ["imports"] }),
      queryClient.invalidateQueries({ queryKey: ["calibration-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["calibration-sets"] }),
      queryClient.invalidateQueries({ queryKey: ["sequences"] }),
      queryClient.invalidateQueries({ queryKey: ["processing-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["products"] }),
    ]);
  };

  const inspectMutation = useMutation({
    mutationFn: () => api.createImportInspection({
      root_id: rootId.trim(),
      relative_path: relativePath.trim(),
      instrument: "ESPADONS",
    }),
    onSuccess: async (result) => {
      setInspectionId(result.id);
      setApprovalReason("");
      setAcceptWarnings(false);
      await refreshAll();
    },
  });
  const importMutation = useMutation({
    mutationFn: (value: ImportInspection) => api.createImport(value),
    onSuccess: refreshAll,
  });
  const calibrationMutation = useMutation({
    mutationFn: () => api.createCalibrationRun(importBatch!.id, parameterVersion.trim()),
    onSuccess: refreshAll,
  });
  const approvalMutation = useMutation({
    mutationFn: () => api.approveCalibrationSet(
      calibrationSet!.id,
      approvalReason.trim(),
      acceptWarnings,
    ),
    onSuccess: refreshAll,
  });
  const processMutation = useMutation({
    mutationFn: (ids: string[]) => Promise.all(ids.map((sequenceId) =>
      api.createProcessingRun({
        sequence_id: sequenceId,
        calibration_set_id: calibrationSet!.id,
        parameter_version: parameterVersion.trim(),
        parameters: {},
      }))),
    onSuccess: async () => {
      await refreshAll();
      if (selectedSequenceIds[0]) onSequenceSelect?.(selectedSequenceIds[0]);
    },
  });

  const mutations = [
    inspectMutation,
    importMutation,
    calibrationMutation,
    approvalMutation,
    processMutation,
  ];
  const mutationError = mutations.find((item) => item.isError)?.error;
  const isBusy = mutations.some((item) => item.isPending);
  const hasCalibrationWarnings = Boolean(calibrationSet?.warnings.length);
  const processingReady = calibrationSet?.status === "APPROVED"
    && calibrationSet.qc_flag !== "FAIL";

  const submitInspection = (event: FormEvent) => {
    event.preventDefault();
    if (rootId.trim() && relativePath.trim()) inspectMutation.mutate();
  };

  const toggleSequence = (id: string) => {
    setSelectedSequenceIds((current) => current.includes(id)
      ? current.filter((item) => item !== id)
      : [...current, id]);
  };

  const steps = [
    { label: t("data.import.step.inspect"), done: inspection?.status === "SUCCEEDED" },
    { label: t("data.import.step.import"), done: importBatch?.status === "SUCCEEDED" },
    { label: t("data.import.step.calibrate"), done: calibrationSet !== undefined },
    { label: t("data.import.step.approve"), done: calibrationSet?.status === "APPROVED" },
    { label: t("data.import.step.process"), done: processingComplete },
  ];

  return (
    <Panel
      title={t("data.import.title")}
      eyebrow={t("data.import.eyebrow")}
      className="import-panel"
      action={<StatusBadge value="ESPADONS · OLAPA" subtle />}
    >
      <ol className="wizard-steps" aria-label={t("data.import.progressAria")}>
        {steps.map((step, index) => (
          <li key={step.label} className={step.done ? "wizard-step-done" : ""}>
            <span>{step.done ? <Check size={13} /> : index + 1}</span>{step.label}
          </li>
        ))}
      </ol>

      {!canReduce && (
        <div className="wizard-role-notice">
          <ShieldCheck size={18} />
          <div><strong>{t("data.import.readOnly")}</strong><p>{t("data.import.roleRequired")}</p></div>
        </div>
      )}

      <div className="wizard-grid">
        <section className="wizard-card">
          <header><FolderSearch2 size={18} /><div><b>01</b><strong>{t("data.import.inspectTitle")}</strong></div></header>
          <form className="wizard-form" onSubmit={submitInspection}>
            <label><span>{t("data.import.root")}</span><input value={rootId} onChange={(event) => setRootId(event.target.value)} placeholder="cadc-public" disabled={!canReduce || isBusy} /></label>
            <label><span>{t("data.import.relativePath")}</span><input value={relativePath} onChange={(event) => setRelativePath(event.target.value)} placeholder="night/target" disabled={!canReduce || isBusy} /></label>
            <button className="button button-primary" type="submit" disabled={!canReduce || !rootId.trim() || !relativePath.trim() || isBusy}><FolderSearch2 size={15} />{inspectMutation.isPending ? t("data.import.inspecting") : t("data.import.inspect")}</button>
          </form>
          {inspections.data?.length ? (
            <label className="wizard-resume"><span>{t("data.import.resume")}</span><select value={inspectionId ?? ""} onChange={(event) => setInspectionId(event.target.value)}>{inspections.data.map((item) => <option key={item.id} value={item.id}>{formatUtc(item.created_at)} · {item.relative_path} · {item.status}</option>)}</select></label>
          ) : null}
          {inspection && (
            <div className="wizard-result">
              <div><StatusBadge value={inspection.status} subtle /><code>{inspection.manifest_sha256?.slice(0, 12) ?? "NO MANIFEST"}</code></div>
              <ul className="inventory-chips">{Object.entries(inventoryCounts).map(([role, count]) => <li key={role}><b>{role}</b><span>{count}</span></li>)}</ul>
              {inspection.error_code && <p className="form-error">{inspection.error_code}: {inspection.error_message}</p>}
            </div>
          )}
        </section>

        <section className="wizard-card wizard-preview-card">
          <header><FileCheck2 size={18} /><div><b>02</b><strong>{t("data.import.previewTitle")}</strong></div></header>
          {previewArtifacts.length ? (
            <>
              <label className="wizard-preview-select">
                <span>{t("data.import.previewArtifact", { count: previewArtifacts.length })}</span>
                <select value={previewPath ?? ""} onChange={(event) => setPreviewPath(event.target.value)}>
                  {previewArtifacts.map((artifact) => (
                    <option key={artifact.relative_path} value={artifact.relative_path}>
                      {String(artifact.role ?? "UNKNOWN")} · {artifact.relative_path.split("/").at(-1)}
                    </option>
                  ))}
                </select>
              </label>
              <div className="mounted-preview" aria-live="polite">
                <div className="mounted-preview-header">
                  <StatusBadge value={String(selectedArtifact?.role ?? "UNKNOWN")} subtle />
                  <code title={previewPath}>{previewPath}</code>
                </div>
                {artifactPreview.isLoading && <div className="visualization-state">{t("common.loading")}</div>}
                {artifactPreview.isError && <div className="visualization-state visualization-error">{errorText(artifactPreview.error)}</div>}
                {artifactPreview.data && (
                  <>
                    <Heatmap
                      values={artifactPreview.data.image}
                      label={`${artifactPreview.data.role} · ${t("data.import.previewImage")}`}
                      emptyLabel={t("data.import.previewUnavailable")}
                      scaleLabel={t("observe.quicklook.scale")}
                      unit={t("observe.quicklook.unit")}
                      orderAnnotations={artifactPreview.data.order_annotations}
                    />
                    <div className="mounted-preview-stats">
                      <span>{t("data.stageDetail.shape")} <b>{artifactPreview.data.shape.join(" × ")}</b></span>
                      <span>MIN <b>{artifactPreview.data.minimum.toFixed(2)}</b></span>
                      <span>MEDIAN <b>{artifactPreview.data.median.toFixed(2)}</b></span>
                      <span>MAX <b>{artifactPreview.data.maximum.toFixed(2)}</b></span>
                    </div>
                  </>
                )}
              </div>
            </>
          ) : <p className="wizard-empty">{t("data.import.previewEmpty")}</p>}
          {inspection?.groups.length ? (
            <><p className="wizard-section-label">{t("data.import.sequenceGroups")}</p><ul className="group-preview">{inspection.groups.map((group, index) => <li key={String(group.group_key ?? index)}><StatusBadge value={String(group.mode ?? "POL")} subtle /><span>{groupLabel(group)}</span><code>{String(group.group_key ?? "")}</code></li>)}</ul></>
          ) : <p className="wizard-empty">{t("data.import.noGroups")}</p>}
          {inspection?.warnings.length ? (
            <ul className="wizard-warnings">{inspection.warnings.map((warning, index) => <li key={String(warning.code ?? index)}><TriangleAlert size={14} /><div><strong>{String(warning.code ?? "WARNING")}</strong><span>{String(warning.message ?? "")}</span></div></li>)}</ul>
          ) : inspection?.status === "SUCCEEDED" ? <p className="wizard-pass"><Check size={14} />{t("data.import.noWarnings")}</p> : null}
          <button className="button button-primary button-wide" type="button" disabled={!canReduce || inspection?.status !== "SUCCEEDED" || Boolean(importBatch) || isBusy} onClick={() => inspection && importMutation.mutate(inspection)}><DatabaseZap size={15} />{importMutation.isPending ? t("data.import.importing") : importBatch ? t("data.import.imported") : t("data.import.commit")}</button>
          {importBatch && <div className="wizard-status-row"><StatusBadge value={importBatch.status} subtle /><span>{t("data.import.sequences", { count: importBatch.sequence_ids.length })}</span><code>{importBatch.id.slice(0, 8)}</code></div>}
        </section>

        <section className="wizard-card">
          <header><Gauge size={18} /><div><b>03</b><strong>{t("data.import.calibrationTitle")}</strong></div></header>
          <label className="wizard-version"><span>{t("data.import.parameterVersion")}</span><input value={parameterVersion} onChange={(event) => setParameterVersion(event.target.value)} disabled={!canReduce || Boolean(calibrationRun) || isBusy} /></label>
          <button className="button button-primary button-wide" type="button" disabled={!canReduce || importBatch?.status !== "SUCCEEDED" || Boolean(calibrationRun) || !parameterVersion.trim() || isBusy} onClick={() => calibrationMutation.mutate()}><Gauge size={15} />{calibrationMutation.isPending ? t("data.import.calibrating") : calibrationRun ? t("data.import.calibrated") : t("data.import.buildCalibration")}</button>
          {calibrationRun && <div className="wizard-status-row"><StatusBadge value={calibrationRun.status} subtle /><span>{Math.round(calibrationRun.progress * 100)}%</span><code>{calibrationRun.id.slice(0, 8)}</code></div>}
          {calibrationSet && <CalibrationMetrics calibrationSet={calibrationSet} />}
        </section>

        <section className="wizard-card">
          <header><ShieldCheck size={18} /><div><b>04</b><strong>{t("data.import.approvalTitle")}</strong></div></header>
          {calibrationSet ? (
            <>
              <div className="wizard-status-row"><StatusBadge value={calibrationSet.status} subtle /><span>{calibrationSet.detector} · {calibrationSet.observing_night}</span><code>{calibrationSet.calibration_hash.slice(0, 8)}</code></div>
              {calibrationSet.status !== "APPROVED" && (
                <div className="approval-form">
                  <label><span>{t("data.import.approvalReason")}</span><textarea value={approvalReason} onChange={(event) => setApprovalReason(event.target.value)} placeholder={t("data.import.approvalPlaceholder")} disabled={!isAdministrator || isBusy} /></label>
                  {hasCalibrationWarnings && <label className="checkbox-field"><input type="checkbox" checked={acceptWarnings} onChange={(event) => setAcceptWarnings(event.target.checked)} disabled={!isAdministrator || isBusy} /><span>{t("data.import.acceptWarnings")}</span></label>}
                  <button className="button button-primary button-wide" type="button" disabled={!isAdministrator || !approvalReason.trim() || (hasCalibrationWarnings && !acceptWarnings) || isBusy} onClick={() => approvalMutation.mutate()}><ShieldCheck size={15} />{approvalMutation.isPending ? t("data.import.approving") : t("data.import.approve")}</button>
                </div>
              )}
              {calibrationSet.status === "APPROVED" && <p className="wizard-pass"><Check size={14} />{t("data.import.approvedBy", { user: calibrationSet.approved_by ?? "—" })}</p>}
            </>
          ) : <p className="wizard-empty">{t("data.import.waitCalibration")}</p>}
        </section>

        <section className="wizard-card wizard-process-card">
          <header><Play size={18} /><div><b>05</b><strong>{t("data.import.processTitle")}</strong></div></header>
          {importBatch?.sequence_ids.length ? (
            <div className="sequence-choice-list">{importBatch.sequence_ids.map((id) => {
              const sequence = sequenceById.get(id) as Sequence | undefined;
              const processing = processingBySequence.get(id);
              return <label key={id}><input type="checkbox" checked={selectedSequenceIds.includes(id)} onChange={() => toggleSequence(id)} disabled={!canReduce || isBusy} /><span><b>{sequence?.mode ?? "POL"}</b>{sequence?.target_name ?? id.slice(0, 8)}</span><StatusBadge value={processing?.status ?? "IMPORTED"} subtle /></label>;
            })}</div>
          ) : <p className="wizard-empty">{t("data.import.waitImport")}</p>}
          <button className="button button-primary button-wide" type="button" disabled={!canReduce || !processingReady || !selectedSequenceIds.length || isBusy} onClick={() => processMutation.mutate(selectedSequenceIds)}><Play size={15} />{processMutation.isPending ? t("data.import.processing") : t("data.import.processSelected", { count: selectedSequenceIds.length })}</button>
          {!processingReady && calibrationSet && <p className="wizard-hint">{t("data.import.processingBlocked")}</p>}
        </section>
      </div>
      {mutationError && <div className="query-error" role="alert">{errorText(mutationError)}</div>}
    </Panel>
  );
}
