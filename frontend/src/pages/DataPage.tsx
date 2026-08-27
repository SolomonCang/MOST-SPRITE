import { useQuery } from "@tanstack/react-query";
import { Box, CheckCircle2, ChevronRight, FileLock2, GitBranch, Layers3, Search, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Heatmap } from "../components/Heatmap";
import { LineageView } from "../components/LineageView";
import { Panel } from "../components/Panel";
import { SpectrumChart } from "../components/SpectrumChart";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n/I18nProvider";
import { api } from "../lib/api";
import type { DataMode } from "../lib/types";

export function DataPage() {
  const { t, formatUtc } = useI18n();
  const [sequenceId, setSequenceId] = useState<string>();
  const [productId, setProductId] = useState<string>();
  const [filter, setFilter] = useState("");
  const [modeFilter, setModeFilter] = useState<DataMode | "ALL">("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");
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
  const series = selectedProduct?.level === "L2"
    ? ["FLUX"]
    : selectedProduct?.mode === "NONPOL" ? ["TARGET", "SKY", "ALPHA", "I"] : ["P", "N1", "N2"];
  const isImagePreview = Boolean(preview.data?.image?.length);

  return (
    <div className="page data-page">
      <div className="page-heading">
        <div><p className="eyebrow">{t("data.eyebrow")}</p><h1>{t("data.title")}</h1><p>{t("data.subtitle")}</p></div>
        <div className="heading-state" aria-live="polite"><StatusBadge value={run?.status ?? t("data.noRun")} /><span>{run ? t("data.processing", { progress: Math.round(run.progress * 100) }) : t("data.waitingInput")}</span></div>
      </div>
      <div className="data-grid">
        <Panel title={t("data.catalog.title")} eyebrow={t("data.catalog.eyebrow")} className="catalog-panel">
          <label className="search-box"><Search size={16} /><span className="visually-hidden">{t("data.catalog.search")}</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={t("data.catalog.search")} /></label>
          <div className="catalog-filters">
            <label><span>{t("data.catalog.mode")}</span><select value={modeFilter} onChange={(event) => setModeFilter(event.target.value as DataMode | "ALL")}><option value="ALL">{t("data.catalog.allModes")}</option><option value="POL_Q">POL_Q</option><option value="NONPOL">NONPOL</option></select></label>
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
              ? selectedProduct?.mode === "NONPOL" && selectedProduct.level === "L3"
                ? <div className="science-chart-stack"><SpectrumChart columns={preview.data.columns} series={["TARGET", "SKY", "I"]} /><SpectrumChart columns={preview.data.columns} series={["ALPHA"]} compact /></div>
                : <SpectrumChart columns={preview.data.columns} series={series} />
              : <div className="image-summary"><strong>{preview.data?.shape?.join(" × ") ?? "—"}</strong><div><span>MIN <b>{preview.data?.minimum?.toFixed(2) ?? "—"}</b></span><span>MEDIAN <b>{preview.data?.median?.toFixed(2) ?? "—"}</b></span><span>MAX <b>{preview.data?.maximum?.toFixed(2) ?? "—"}</b></span></div></div>}
          {selectedProduct && <div className="product-meta"><span><Box size={15} />{(selectedProduct.size / 1024).toFixed(1)} KiB</span><span><Layers3 size={15} />{selectedProduct.schema_version}</span><span><FileLock2 size={15} />{t("common.immutable")}</span><time>{formatUtc(selectedProduct.created_at, true)} UTC</time></div>}
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
