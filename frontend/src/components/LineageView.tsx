import { ArrowRight } from "lucide-react";
import { useI18n } from "../i18n/I18nProvider";
import type { Lineage } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

export function LineageView({ lineage }: { lineage?: Lineage }) {
  const { t } = useI18n();
  if (!lineage) return <div className="empty-copy">{t("data.lineage.empty")}</div>;
  const levels = ["L0", "L1", "L2", "L3"] as const;
  const tiers = levels
    .map((level) => ({ level, nodes: lineage.nodes.filter((node) => node.level === level) }))
    .filter((tier) => tier.nodes.length > 0);
  return (
    <div className="lineage-list">
      {tiers.map((tier, tierIndex) => (
        <div className="lineage-stage" key={tier.level}>
          <section className="lineage-tier">
            <header>
              <strong>{tier.level}</strong>
              <span>{t(tier.nodes.length === 1 ? "common.nodeCountOne" : "common.nodeCountOther", { count: tier.nodes.length })}</span>
            </header>
            <div className="lineage-tier-nodes">
              {tier.nodes.map((node) => {
                const inputCount = lineage.edges.filter((edge) => edge.target === node.id).length;
                return (
                  <div
                    className={`lineage-node ${node.id === lineage.root_id ? "lineage-root" : ""}`}
                    key={node.id}
                  >
                    <div>
                      <strong>{node.kind === "RAW_FILE" ? "RAW" : node.level}</strong>
                      <small>{node.kind === "RAW_FILE" ? t("common.rawFile") : node.schema_version}</small>
                    </div>
                    {node.qc_flag && <StatusBadge value={node.qc_flag} subtle />}
                    <code title={node.sha256}>{node.sha256.slice(0, 12)}</code>
                    {inputCount > 0 && <small className="lineage-input-count">{t(inputCount === 1 ? "common.directInputCountOne" : "common.directInputCountOther", { count: inputCount })}</small>}
                  </div>
                );
              })}
            </div>
          </section>
          {tierIndex < tiers.length - 1 && (
            <div className="lineage-flow" title={t("data.lineage.relation")}>
              <span>{lineage.edges.filter((edge) => edge.target && tiers[tierIndex + 1].nodes.some((node) => node.id === edge.target)).length}</span>
              <ArrowRight size={17} aria-hidden="true" />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
