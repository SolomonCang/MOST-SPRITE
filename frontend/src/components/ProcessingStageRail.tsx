import { ArrowRight, Image, ScanLine } from "lucide-react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/translations";
import type { ProcessingStage, ProcessingStageKey } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

const stageCopy: Record<ProcessingStageKey, { title: TranslationKey; description: TranslationKey }> = {
  l0: { title: "data.stage.l0.title", description: "data.stage.l0.description" },
  quicklook: { title: "data.stage.quicklook.title", description: "data.stage.quicklook.description" },
  l1: { title: "data.stage.l1.title", description: "data.stage.l1.description" },
  l2: { title: "data.stage.l2.title", description: "data.stage.l2.description" },
  l3: { title: "data.stage.l3.title", description: "data.stage.l3.description" },
};

export function stageTitle(key: ProcessingStageKey, t: (key: TranslationKey) => string): string {
  return t(stageCopy[key].title);
}

export function ProcessingStageRail({ runId, stages, loading = false }: { runId?: string; stages?: ProcessingStage[]; loading?: boolean }) {
  const { t } = useI18n();

  if (loading) return <div className="stage-rail-empty">{t("common.loading")}</div>;
  if (!runId || !stages?.length) return <div className="stage-rail-empty">{t("data.stages.empty")}</div>;

  return (
    <ol className="stage-rail" data-testid="processing-stages">
      {stages.map((stage) => {
        const Icon = stage.preview_kind === "image" ? Image : ScanLine;
        const content = (
          <>
            <header><span>{String(stage.order).padStart(2, "0")}</span><StatusBadge value={stage.status} subtle /></header>
            <div className="stage-icon"><Icon size={19} aria-hidden="true" /></div>
            <div className="stage-copy"><strong>{t(stageCopy[stage.key].title)}</strong><p>{t(stageCopy[stage.key].description)}</p></div>
            <footer><span>{t("data.stages.outputCount", { count: stage.products.length, expected: stage.expected_output_count })}</span>{stage.products.length > 0 && <><b>{t("data.stages.view")}</b><ArrowRight size={14} /></>}</footer>
          </>
        );
        return (
          <li key={stage.key} className={`stage-${stage.status.toLowerCase().replaceAll("_", "-")}`}>
            {stage.products.length > 0
              ? <Link data-testid={`product-${stage.level}`} to={`/data/runs/${runId}/stages/${stage.key}`}>{content}</Link>
              : <div>{content}</div>}
          </li>
        );
      })}
    </ol>
  );
}
