import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileLock2, Layers3, MousePointer2 } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { Panel } from "../components/Panel";
import { ProductVisualization } from "../components/ProductVisualization";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n/I18nProvider";
import { api } from "../lib/api";

export function SpectrumViewerPage() {
  const { productId } = useParams<{ productId: string }>();
  const { t, formatUtc } = useI18n();
  const product = useQuery({ queryKey: ["product", productId], queryFn: () => api.product(productId!), enabled: Boolean(productId) });
  const preview = useQuery({ queryKey: ["preview", productId], queryFn: () => api.preview(productId!), enabled: Boolean(productId && product.data?.level === "L3") });

  if (product.isLoading) return <div className="page spectrum-viewer-page"><div className="visualization-state">{t("common.loading")}</div></div>;
  if (product.isError || !product.data || product.data.level !== "L3") {
    return <div className="page spectrum-viewer-page"><Link className="stage-back-link" to="/data"><ArrowLeft size={15} />{t("data.preview.back")}</Link><div className="query-error" role="alert">{t("data.preview.viewerUnavailable")}</div></div>;
  }

  return (
    <div className="page spectrum-viewer-page" data-testid="spectrum-viewer-page">
      <Link className="stage-back-link" to={`/data?sequence=${product.data.sequence_id}`}><ArrowLeft size={15} />{t("data.preview.back")}</Link>
      <div className="page-heading spectrum-viewer-heading">
        <div><p className="eyebrow">INTERACTIVE SCIENCE PRODUCT</p><h1>L3 · {t("data.preview.spectrumTitle")}</h1><p>{t("data.preview.viewerDescription")}</p></div>
        <div className="stage-heading-meta"><StatusBadge value={product.data.qc_flag} /><code>{product.data.id.slice(0, 12)}</code></div>
      </div>

      <Panel title={t("data.preview.interactiveSpectrum")} eyebrow={`${product.data.mode} · ${product.data.schema_version}`} className="spectrum-viewer-panel" action={<span className="viewer-interaction-badge"><MousePointer2 size={14} />{t("data.preview.interactive")}</span>}>
        <ProductVisualization product={product.data} preview={preview.data} loading={preview.isLoading} error={preview.isError} />
        <div className="product-meta">
          <span><Layers3 size={15} />{product.data.schema_version}</span>
          <span><FileLock2 size={15} />{t("common.immutable")}</span>
          {product.data.instrument && <span>{product.data.instrument} · {product.data.detector_profile ?? "—"}</span>}
          <time>{formatUtc(product.data.created_at, true)} UTC</time>
        </div>
      </Panel>
    </div>
  );
}
