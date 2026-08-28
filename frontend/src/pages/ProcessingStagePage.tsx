import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Box, Download, ExternalLink, FileLock2, GitBranch, Layers3 } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { LineageView } from "../components/LineageView";
import { Panel } from "../components/Panel";
import { ProductVisualization } from "../components/ProductVisualization";
import { stageTitle } from "../components/ProcessingStageRail";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n/I18nProvider";
import { api } from "../lib/api";
import type { ProcessingStageKey } from "../lib/types";

export function ProcessingStagePage() {
  const { runId, stageKey } = useParams<{ runId: string; stageKey: ProcessingStageKey }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { t, formatUtc } = useI18n();
  const run = useQuery({ queryKey: ["processing-run", runId], queryFn: () => api.processingRun(runId!), enabled: Boolean(runId) });
  const stages = useQuery({ queryKey: ["processing-stages", runId], queryFn: () => api.processingStages(runId!), enabled: Boolean(runId) });
  const stage = stages.data?.find((item) => item.key === stageKey);
  const requestedProductId = searchParams.get("product");
  const product = stage?.products.find((item) => item.id === requestedProductId) ?? stage?.products[0];
  const preview = useQuery({ queryKey: ["preview", product?.id], queryFn: () => api.preview(product!.id), enabled: Boolean(product) });
  const qc = useQuery({ queryKey: ["qc", product?.id], queryFn: () => api.qc(product!.id), enabled: Boolean(product) });
  const lineage = useQuery({ queryKey: ["lineage", product?.id], queryFn: () => api.lineage(product!.id), enabled: Boolean(product) });
  const stageIndex = stages.data?.findIndex((item) => item.key === stageKey) ?? -1;
  const previousStage = stageIndex > 0 ? stages.data?.[stageIndex - 1] : undefined;
  const nextStage = stageIndex >= 0 ? stages.data?.[stageIndex + 1] : undefined;

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

  if (run.isLoading || stages.isLoading) {
    return <div className="page stage-detail-page"><div className="visualization-state">{t("common.loading")}</div></div>;
  }
  if (run.isError || stages.isError || !run.data || !stage) {
    return <div className="page stage-detail-page"><Link className="stage-back-link" to="/data"><ArrowLeft size={15} />{t("data.stageDetail.back")}</Link><div className="query-error" role="alert">{t("data.stageDetail.notFound")}</div></div>;
  }

  return (
    <div className="page stage-detail-page">
      <Link className="stage-back-link" to={`/data?sequence=${run.data.sequence_id}`}><ArrowLeft size={15} />{t("data.stageDetail.back")}</Link>
      <div className="page-heading stage-detail-heading">
        <div><p className="eyebrow">{t("data.stageDetail.eyebrow", { order: String(stage.order).padStart(2, "0"), level: stage.level })}</p><h1>{stageTitle(stage.key, t)}</h1><p>{t(`data.stage.${stage.key}.description`)}</p></div>
        <div className="stage-heading-meta"><StatusBadge value={stage.status} /><span>{t("data.stages.outputCount", { count: stage.products.length, expected: stage.expected_output_count })}</span><code>{run.data.id.slice(0, 12)}</code></div>
      </div>

      <div className="stage-detail-grid">
        <Panel title={t("data.stageDetail.outputs")} eyebrow={t("data.stageDetail.outputsEyebrow")} className="stage-output-panel" action={<span>{stage.products.length}</span>}>
          <div className="stage-output-list" data-testid="stage-output-list">
            {stage.products.map((item, index) => (
              <button key={item.id} type="button" className={item.id === product?.id ? "selected" : ""} aria-pressed={item.id === product?.id} onClick={() => setSearchParams({ product: item.id })}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{item.level} · {item.exposure_id ? t("data.stageDetail.exposure") : t("data.stageDetail.combined")}</strong><code>{item.id.slice(0, 12)}</code><time>{formatUtc(item.created_at, true)} UTC</time></div>
                <StatusBadge value={item.qc_flag} subtle />
              </button>
            ))}
            {!stage.products.length && <div className="empty-copy">{t("data.stageDetail.noOutputs")}</div>}
          </div>
          <dl className="stage-run-facts">
            <div><dt>{t("data.stageDetail.run")}</dt><dd>{run.data.id.slice(0, 12)}</dd></div>
            <div><dt>{t("data.stageDetail.parameter")}</dt><dd>{run.data.parameter_version}</dd></div>
            <div><dt>{t("data.stageDetail.updated")}</dt><dd>{formatUtc(run.data.updated_at, true)} UTC</dd></div>
          </dl>
        </Panel>

        <Panel title={product ? `${product.level} · ${product.level === "L3" ? t("data.preview.spectrumTitle") : t("data.stageDetail.preview")}` : t("data.stageDetail.preview")} eyebrow={stage.preview_kind === "image" ? t("data.stages.image") : t("data.stages.spectrum")} className="stage-preview-panel" action={product && <div className="product-ident"><StatusBadge value={product.qc_flag} subtle /><code>{product.sha256.slice(0, 12)}</code></div>}>
          <ProductVisualization product={product} preview={preview.data} loading={preview.isLoading} error={preview.isError} />
          {product && <><div className="product-meta"><span><Box size={15} />{(product.size / 1024).toFixed(1)} KiB</span><span><Layers3 size={15} />{product.schema_version}</span><span><FileLock2 size={15} />{t("common.immutable")}</span>{product.instrument && <span>{product.instrument} · {product.detector_profile ?? "—"}</span>}<time>{formatUtc(product.created_at, true)} UTC</time></div><div className="product-actions">{product.level === "L3" && <a className="button button-secondary" href={`/data/products/${product.id}/spectrum`} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} />{t("data.preview.openWindow")}</a>}<button className="button button-secondary" type="button" disabled={downloadMutation.isPending} onClick={() => downloadMutation.mutate(product.id)}><Download size={15} />{downloadMutation.isPending ? t("data.product.downloading") : t("data.product.download")}</button></div></>}
          {downloadMutation.isError && <div className="query-error" role="alert">{downloadMutation.error.message}</div>}
        </Panel>

        <Panel title={t("data.qc.title")} eyebrow={t("data.qc.eyebrow")} className="stage-qc-panel">
          <div className="qc-list" data-testid="qc-list">
            {qc.data?.map((item) => <article key={item.id} className={item.passed ? "qc-pass" : "qc-fail"}><div><strong>{item.metric}</strong><span>{item.passed ? t("data.qc.pass") : t("data.qc.fail")}</span></div><dl><div><dt>{t("data.qc.value")}</dt><dd>{item.value === null ? "—" : item.value.toExponential(3)}</dd></div><div><dt>{t("data.qc.threshold")}</dt><dd>{item.threshold === null ? "—" : item.threshold.toExponential(3)}</dd></div><div><dt>{t("data.qc.reason")}</dt><dd>{item.reason_code}</dd></div></dl></article>)}
            {!qc.data?.length && !qc.isLoading && <div className="empty-copy">{t("data.qc.empty")}</div>}
          </div>
        </Panel>

        <Panel title={t("data.lineage.title")} eyebrow={t("data.lineage.eyebrow")} className="stage-lineage-panel" action={<GitBranch size={17} />}>
          <div data-testid="lineage-view"><LineageView lineage={lineage.data} /></div>
        </Panel>
      </div>

      <nav className="stage-neighbor-nav" aria-label={t("data.stageDetail.stageNavigation")}>
        {previousStage ? <Link to={`/data/runs/${runId}/stages/${previousStage.key}`}><ArrowLeft size={15} /><span><small>{t("data.stageDetail.previous")}</small><strong>{stageTitle(previousStage.key, t)}</strong></span></Link> : <span />}
        {nextStage ? <Link to={`/data/runs/${runId}/stages/${nextStage.key}`}><span><small>{t("data.stageDetail.next")}</small><strong>{stageTitle(nextStage.key, t)}</strong></span><ArrowRight size={15} /></Link> : <span />}
      </nav>
    </div>
  );
}
