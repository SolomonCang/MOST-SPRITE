import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Box, CheckCircle2, ChevronRight, Download, FileLock2, GitBranch, Layers3, Search, Send, Undo2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { ESPaDOnSImportWizard } from "../components/ESPaDOnSImportWizard";
import { Heatmap } from "../components/Heatmap";
import { LineageView } from "../components/LineageView";
import { Panel } from "../components/Panel";
import { SpectrumChart } from "../components/SpectrumChart";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n/I18nProvider";
import { api } from "../lib/api";
import type { CurrentUser, DataMode } from "../lib/types";

export function DataPage() {
  const { user } = useOutletContext<{ user?: CurrentUser }>();
  const { t, formatUtc } = useI18n();
  const queryClient = useQueryClient();
  const [sequenceId, setSequenceId] = useState<string>();
  const [productId, setProductId] = useState<string>();
  const [filter, setFilter] = useState("");
  const [modeFilter, setModeFilter] = useState<DataMode | "ALL">("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [publicationReason, setPublicationReason] = useState("");
  const sequences = useQuery({ queryKey: ["sequences"], queryFn: api.sequences, refetchInterval: 2000 });
  useEffect(() => {
    if (!sequenceId && sequences.data?.length) setSequenceId(sequences.data[0].id);
  }, [sequenceId, sequences.data]);
  const products = useQuery({ queryKey: ["products", sequenceId], queryFn: () => api.products(sequenceId), enabled: Boolean(sequenceId), refetchInterval: 1500 });
  const runs = useQuery({ queryKey: ["processing-runs"], queryFn: api.processingRuns, refetchInterval: 1500 });
  useEffect(() => {
    if (!products.data?.length) return;
    if (!products.data.some((item) => item.id === productId)) setProductId(products.data.find((item) => item.level === "L3")?.id ?? products.data[0].id);
  }, [productId, products.data]);

  const selectedSequence = sequences.data?.find((item) => item.id === sequenceId);
  const selectedProduct = products.data?.find((item) => item.id === productId);
  const preview = useQuery({ queryKey: ["preview", productId], queryFn: () => api.preview(productId!), enabled: Boolean(productId) });
  const qc = useQuery({ queryKey: ["qc", productId], queryFn: () => api.qc(productId!), enabled: Boolean(productId) });
  const lineage = useQuery({ queryKey: ["lineage", productId], queryFn: () => api.lineage(productId!), enabled: Boolean(productId) });
  const run = runs.data?.find((item) => item.sequence_id === sequenceId);
  const statuses = useMemo(() => [...new Set(sequences.data?.map((item) => item.status) ?? [])].sort(), [sequences.data]);
  const filteredSequences = useMemo(
    () => sequences.data?.filter((item) =>
      item.target_name.toLowerCase().includes(filter.toLowerCase())
      && (modeFilter === "ALL" || item.mode === modeFilter)
      && (statusFilter === "ALL" || item.status === statusFilter),
    ) ?? [],
    [filter, modeFilter, sequences.data, statusFilter],
  );
  const isImagePreview = Boolean(preview.data?.image?.length);
  const isAdministrator = user?.role === "administrator";
  const dqValues = preview.data?.columns?.DQ ?? [];
  const flaggedPoints = dqValues.filter((value) => typeof value === "number" && value !== 0).length;
  const finiteDqPoints = dqValues.filter((value) => typeof value === "number").length;

  const downloadMutation = useMutation({
    mutationFn: (id: string) => api.downloadProduct(id),
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    },
  });
  const publicationMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "publish" | "withdraw" }) =>
      api.productAction(id, action, publicationReason.trim() || null),
    onSuccess: async () => {
      setPublicationReason("");
      await queryClient.invalidateQueries({ queryKey: ["products"] });
    },
  });

  const selectImportedSequence = (id: string) => {
    setSequenceId(id);
    setProductId(undefined);
  };

  return (
    <div className="page data-page">
      <div className="page-heading">
        <div><p className="eyebrow">{t("data.eyebrow")}</p><h1>{t("data.title")}</h1><p>{t("data.subtitle")}</p></div>
        <div className="heading-state" aria-live="polite"><StatusBadge value={run?.status ?? t("data.noRun")} /><span>{run ? t("data.processing", { progress: Math.round(run.progress * 100) }) : t("data.waitingInput")}</span></div>
      </div>
      <ESPaDOnSImportWizard user={user} onSequenceSelect={selectImportedSequence} />
      <div className="data-grid">
        <Panel title={t("data.catalog.title")} eyebrow={t("data.catalog.eyebrow")} className="catalog-panel">
          <label className="search-box"><Search size={16} /><span className="visually-hidden">{t("data.catalog.search")}</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={t("data.catalog.search")} /></label>
          <div className="catalog-filters">
            <label><span>{t("data.catalog.mode")}</span><select value={modeFilter} onChange={(event) => setModeFilter(event.target.value as DataMode | "ALL")}><option value="ALL">{t("data.catalog.allModes")}</option><option value="POL_Q">POL_Q</option><option value="POL_U">POL_U</option><option value="POL_V">POL_V</option><option value="NONPOL">NONPOL</option></select></label>
            <label><span>{t("data.catalog.status")}</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">{t("data.catalog.allStatuses")}</option>{statuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
          </div>
          {sequences.isError && <div className="query-error">{t("common.networkError")}</div>}
          <div className="sequence-list" data-testid="sequence-list">
            {filteredSequences.map((sequence) => (
              <button key={sequence.id} type="button" aria-pressed={sequence.id === sequenceId} className={sequence.id === sequenceId ? "selected" : ""} onClick={() => { setSequenceId(sequence.id); setProductId(undefined); }}>
                <span className="mode-chip">{sequence.mode}</span>
                <div><strong>{sequence.target_name}</strong><small>{formatUtc(sequence.created_at, true)} UTC</small><code>{sequence.id.slice(0, 8)}</code></div>
                <StatusBadge value={sequence.status} subtle /><ChevronRight size={15} />
              </button>
            ))}
            {!filteredSequences.length && !sequences.isLoading && <div className="empty-copy">{t("data.catalog.empty")}</div>}
          </div>
        </Panel>

        <Panel title={t("data.products.title")} eyebrow={t("data.products.eyebrow")} className="products-panel" action={selectedSequence && <StatusBadge value={selectedSequence.mode} subtle />}>
          <div className="run-progress">
            <div><span>{t("data.products.run")}</span><strong>{run?.id.slice(0, 8) ?? t("data.products.noRun")}</strong><StatusBadge value={run?.status ?? "WAITING"} subtle /></div>
            <div className="progress-track"><i style={{ width: `${(run?.progress ?? 0) * 100}%` }} /></div>
          </div>
          <div className="product-levels">
            {(["L0", "QUICKLOOK", "L1", "L2", "L3"] as const).map((level) => {
              const rows = products.data?.filter((item) => item.level === level) ?? [];
              return (
                <div className="level-column" key={level}>
                  <header><span>{level === "QUICKLOOK" ? "QL" : level}</span><b>{rows.length}</b></header>
                  {rows.slice(0, 8).map((product) => (
                    <button data-testid={`product-${product.level}`} key={product.id} type="button" aria-pressed={product.id === productId} onClick={() => setProductId(product.id)} className={product.id === productId ? "selected" : ""}>
                      <FileLock2 size={16} /><div><strong>{product.schema_version}</strong><small>{product.id.slice(0, 8)}</small><time>{formatUtc(product.created_at)} UTC</time></div><StatusBadge value={product.qc_flag} subtle />
                    </button>
                  ))}
                  {!rows.length && <span className="level-empty">{t("data.products.emptyLevel")}</span>}
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel title={selectedProduct ? `${selectedProduct.level} · ${t("data.preview.title")}` : t("data.preview.title")} eyebrow={selectedProduct?.level === "QUICKLOOK" ? t("data.preview.quicklook") : t("data.preview.formal")} className="spectrum-panel" action={selectedProduct && <div className="product-ident"><StatusBadge value={selectedProduct.qc_flag} subtle /><code>{selectedProduct.sha256.slice(0, 12)}</code></div>}>
          {isImagePreview
            ? <Heatmap values={preview.data?.image} emptyLabel={t("observe.quicklook.empty")} scaleLabel={t("observe.quicklook.scale")} unit={t("observe.quicklook.unit")} />
            : preview.data?.columns
              ? (
                <div className="science-chart-stack">
                  {selectedProduct?.level === "L2" && <><SpectrumChart columns={preview.data.columns} series={["FLUX"]} /><SpectrumChart columns={preview.data.columns} series={["VAR"]} compact /></>}
                  {selectedProduct?.level === "L3" && selectedProduct.mode !== "NONPOL" && <><SpectrumChart columns={preview.data.columns} series={["I"]} compact /><SpectrumChart columns={preview.data.columns} series={["P", "N1", "N2"]} /><SpectrumChart columns={preview.data.columns} series={["ERR_P", "ERR_N1", "ERR_N2"]} compact /></>}
                  {selectedProduct?.level === "L3" && selectedProduct.mode === "NONPOL" && <><SpectrumChart columns={preview.data.columns} series={["TARGET", "SKY", "I"]} /><SpectrumChart columns={preview.data.columns} series={["ALPHA"]} compact /><SpectrumChart columns={preview.data.columns} series={["ERR_TARGET", "ERR_SKY", "ERR_I"]} compact /></>}
                  {selectedProduct?.level !== "L2" && selectedProduct?.level !== "L3" && <SpectrumChart columns={preview.data.columns} series={["FLUX", "I"]} />}
                  {finiteDqPoints > 0 && <div className="dq-summary"><span>DQ</span><strong>{flaggedPoints} / {finiteDqPoints}</strong><div className="progress-track"><i style={{ width: `${finiteDqPoints ? (flaggedPoints / finiteDqPoints) * 100 : 0}%` }} /></div><small>{t("data.preview.dqSummary")}</small></div>}
                </div>
              )
              : <div className="image-summary"><strong>{preview.data?.shape?.join(" × ") ?? "—"}</strong><div><span>MIN <b>{preview.data?.minimum?.toFixed(2) ?? "—"}</b></span><span>MEDIAN <b>{preview.data?.median?.toFixed(2) ?? "—"}</b></span><span>MAX <b>{preview.data?.maximum?.toFixed(2) ?? "—"}</b></span></div></div>}
          {selectedProduct && (
            <>
              <div className="product-meta">
                <span><Box size={15} />{(selectedProduct.size / 1024).toFixed(1)} KiB</span>
                <span><Layers3 size={15} />{selectedProduct.schema_version}</span>
                <span><FileLock2 size={15} />{t("common.immutable")}</span>
                {selectedProduct.instrument && <span>{selectedProduct.instrument} · {selectedProduct.detector_profile ?? "—"}</span>}
                <StatusBadge value={selectedProduct.publication_status} subtle />
                <time>{formatUtc(selectedProduct.created_at, true)} UTC</time>
              </div>
              {selectedProduct.level === "L3" && <dl className="variant-meta"><div><dt>NORMSTAT</dt><dd>{String(selectedProduct.metadata.normalization ?? "—")}</dd></div><div><dt>SPECSYS</dt><dd>{String(selectedProduct.metadata.specsys ?? "—")}</dd></div><div><dt>WAVETYPE</dt><dd>{String(selectedProduct.metadata.wavelength_type ?? "—")}</dd></div><div><dt>POLCONT</dt><dd>{selectedProduct.metadata.polarization_continuum_removed === false ? "PRESERVED" : String(selectedProduct.metadata.polarization_continuum_removed ?? "—")}</dd></div></dl>}
              <div className="product-actions">
                <button className="button button-secondary" type="button" disabled={downloadMutation.isPending} onClick={() => downloadMutation.mutate(selectedProduct.id)}><Download size={15} />{downloadMutation.isPending ? t("data.product.downloading") : t("data.product.download")}</button>
                {isAdministrator && selectedProduct.level === "L3" && (
                  <>
                    <label><span>{t("data.product.publicationReason")}</span><input value={publicationReason} onChange={(event) => setPublicationReason(event.target.value)} placeholder={t("data.product.publicationPlaceholder")} /></label>
                    {selectedProduct.publication_status !== "PUBLISHED"
                      ? <button className="button button-primary" type="button" disabled={publicationMutation.isPending || selectedProduct.qc_flag === "FAIL" || selectedProduct.qc_flag === "SIMULATION_ONLY" || (selectedProduct.qc_flag === "WARNING" && publicationReason.trim().length < 8)} onClick={() => publicationMutation.mutate({ id: selectedProduct.id, action: "publish" })}><Send size={15} />{t("data.product.publish")}</button>
                      : <button className="button button-danger" type="button" disabled={publicationMutation.isPending || publicationReason.trim().length < 8} onClick={() => publicationMutation.mutate({ id: selectedProduct.id, action: "withdraw" })}><Undo2 size={15} />{t("data.product.withdraw")}</button>}
                  </>
                )}
              </div>
              {(downloadMutation.isError || publicationMutation.isError) && <div className="query-error" role="alert">{downloadMutation.error?.message ?? publicationMutation.error?.message}</div>}
            </>
          )}
        </Panel>

        <Panel title={t("data.qc.title")} eyebrow={t("data.qc.eyebrow")} className="qc-panel">
          <div className="qc-list" data-testid="qc-list">
            {qc.data?.map((item) => (
              <article key={item.id} className={item.passed ? "qc-pass" : "qc-fail"}>
                {item.passed ? <CheckCircle2 size={19} /> : <XCircle size={19} />}
                <div><strong>{item.metric}</strong><span>{item.passed ? t("data.qc.pass") : t("data.qc.fail")}</span></div>
                <dl><div><dt>{t("data.qc.value")}</dt><dd>{item.value === null ? "—" : item.value.toExponential(3)}</dd></div><div><dt>{t("data.qc.threshold")}</dt><dd>{item.threshold === null ? "—" : item.threshold.toExponential(3)}</dd></div><div><dt>{t("data.qc.reason")}</dt><dd>{item.reason_code}</dd></div></dl>
              </article>
            ))}
            {!qc.data?.length && !qc.isLoading && <div className="empty-copy">{t("data.qc.empty")}</div>}
          </div>
        </Panel>

        <Panel title={t("data.lineage.title")} eyebrow={t("data.lineage.eyebrow")} className="lineage-panel" action={<GitBranch size={17} />}>
          <div data-testid="lineage-view"><LineageView lineage={lineage.data} /></div>
        </Panel>
      </div>
    </div>
  );
}
