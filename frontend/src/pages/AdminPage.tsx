import { FileClock, KeyRound, ServerCog, ShieldAlert } from "lucide-react";
import { useOutletContext } from "react-router-dom";
import { Panel } from "../components/Panel";
import { RoleGate } from "../components/RoleGate";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n/I18nProvider";
import type { CurrentUser } from "../lib/types";

export function AdminPage() {
  const { user } = useOutletContext<{ user?: CurrentUser }>();
  const { t } = useI18n();
  const cards = [
    { title: t("admin.identity.title"), heading: t("admin.identity.heading"), copy: t("admin.identity.copy"), icon: KeyRound, status: "OIDC" },
    { title: t("admin.config.title"), heading: t("admin.config.heading"), copy: t("admin.config.copy"), icon: ShieldAlert, status: "UNVERIFIED" },
    { title: t("admin.health.title"), heading: t("admin.health.heading"), copy: t("admin.health.copy"), icon: ServerCog, status: "HEALTHY" },
    { title: t("admin.audit.title"), heading: t("admin.audit.heading"), copy: t("admin.audit.copy"), icon: FileClock, status: "APPEND_ONLY" },
  ];
  return (
    <RoleGate user={user} allowed={["administrator"]}>
      <div className="page">
        <div className="page-heading"><div><p className="eyebrow">{t("admin.eyebrow")}</p><h1>{t("admin.title")}</h1><p>{t("admin.subtitle")}</p></div><StatusBadge value="SIMULATION_ONLY" /></div>
        <div className="skeleton-grid">
          {cards.map(({ title, heading, copy, icon: Icon, status }) => <Panel key={title} title={title} action={<StatusBadge value={status} subtle />}><div className="route-skeleton"><Icon size={26} /><strong>{heading}</strong><p>{copy}</p></div></Panel>)}
        </div>
      </div>
    </RoleGate>
  );
}
