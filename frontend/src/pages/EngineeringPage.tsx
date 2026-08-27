import { Cpu, LockKeyhole, RadioTower, SlidersHorizontal } from "lucide-react";
import { useOutletContext } from "react-router-dom";
import { Panel } from "../components/Panel";
import { RoleGate } from "../components/RoleGate";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n/I18nProvider";
import type { CurrentUser } from "../lib/types";

export function EngineeringPage() {
  const { user } = useOutletContext<{ user?: CurrentUser }>();
  const { t } = useI18n();
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
        <div className="skeleton-grid">
          {cards.map(({ title, heading, copy, icon: Icon, status }) => <Panel key={title} title={title} action={<StatusBadge value={status} subtle />}><div className="route-skeleton"><Icon size={26} /><strong>{heading}</strong><p>{copy}</p></div></Panel>)}
        </div>
      </div>
    </RoleGate>
  );
}
