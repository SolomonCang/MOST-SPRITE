import { Heatmap } from "./Heatmap";
import { SpectrumChart } from "./SpectrumChart";
import { useI18n } from "../i18n/I18nProvider";
import type { Preview, Product } from "../lib/types";

interface ProductVisualizationProps {
  product?: Product;
  preview?: Preview;
  loading?: boolean;
  error?: boolean;
}

export function ProductVisualization({ product, preview, loading = false, error = false }: ProductVisualizationProps) {
  const { t } = useI18n();

  if (loading) return <div className="visualization-state">{t("common.loading")}</div>;
  if (error) return <div className="visualization-state visualization-error">{t("common.networkError")}</div>;
  if (!product || !preview) return <div className="visualization-state">{t("data.preview.empty")}</div>;

  const dqValues = preview.columns?.DQ ?? [];
  const flaggedPoints = dqValues.filter((value) => typeof value === "number" && value !== 0).length;
  const finiteDqPoints = dqValues.filter((value) => typeof value === "number").length;

  if (preview.image?.length) {
    return (
      <div className="science-chart-stack">
        <Heatmap
          values={preview.image}
          label={`${product.level} ${t("data.stageDetail.preview")}`}
          emptyLabel={t("observe.quicklook.empty")}
          scaleLabel={t("observe.quicklook.scale")}
          unit={t("observe.quicklook.unit")}
          orderAnnotations={preview.order_annotations}
        />
        <div className="image-stat-strip">
          <span>{t("data.stageDetail.shape")} <b>{preview.shape?.join(" × ") ?? "—"}</b></span>
          <span>MIN <b>{preview.minimum?.toFixed(2) ?? "—"}</b></span>
          <span>MEDIAN <b>{preview.median?.toFixed(2) ?? "—"}</b></span>
          <span>MAX <b>{preview.maximum?.toFixed(2) ?? "—"}</b></span>
        </div>
      </div>
    );
  }

  if (!preview.columns) {
    return (
      <div className="image-summary">
        <strong>{preview.shape?.join(" × ") ?? "—"}</strong>
        <div><span>MIN <b>{preview.minimum?.toFixed(2) ?? "—"}</b></span><span>MEDIAN <b>{preview.median?.toFixed(2) ?? "—"}</b></span><span>MAX <b>{preview.maximum?.toFixed(2) ?? "—"}</b></span></div>
      </div>
    );
  }

  return (
    <div className="science-chart-stack">
      {product.level === "L2" && <><SpectrumChart columns={preview.columns} series={["FLUX"]} /><SpectrumChart columns={preview.columns} series={["VAR"]} compact /></>}
      {product.level === "L3" && product.mode !== "NONPOL" && <><SpectrumChart columns={preview.columns} series={["I"]} compact interactive /><SpectrumChart columns={preview.columns} series={["P", "N1", "N2"]} interactive /><SpectrumChart columns={preview.columns} series={["ERR_P", "ERR_N1", "ERR_N2"]} compact interactive /></>}
      {product.level === "L3" && product.mode === "NONPOL" && <><SpectrumChart columns={preview.columns} series={["TARGET", "SKY", "I"]} interactive /><SpectrumChart columns={preview.columns} series={["ALPHA"]} compact interactive /><SpectrumChart columns={preview.columns} series={["ERR_TARGET", "ERR_SKY", "ERR_I"]} compact interactive /></>}
      {product.level !== "L2" && product.level !== "L3" && <SpectrumChart columns={preview.columns} series={["FLUX", "I"]} />}
      {finiteDqPoints > 0 && <div className="dq-summary"><span>DQ</span><strong>{flaggedPoints} / {finiteDqPoints}</strong><div className="progress-track"><i style={{ width: `${(flaggedPoints / finiteDqPoints) * 100}%` }} /></div><small>{t("data.preview.dqSummary")}</small></div>}
    </div>
  );
}
