import { ArrowUpRight, Database, FileClock, Gauge, KeyRound, MonitorCog, ServerCog, ShieldAlert, Telescope } from "lucide-react";
import { Link, useOutletContext } from "react-router-dom";
import { Panel } from "../components/Panel";
import { PreferenceControls } from "../components/PreferenceControls";
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
  const workspaces = [
    { to: "/observe", title: t("admin.workspace.observe"), label: "OBSERVE", copy: t("admin.workspace.observeCopy"), icon: Telescope, role: t("role.observer"), accent: "observe" },
    { to: "/engineering", title: t("admin.workspace.engineering"), label: "ENGINEERING", copy: t("admin.workspace.engineeringCopy"), icon: Gauge, role: t("role.instrument_engineer"), accent: "engineering" },
    { to: "/data", title: t("admin.workspace.data"), label: "DATA", copy: t("admin.workspace.dataCopy"), icon: Database, role: t("role.data_reducer"), accent: "data" },
  ];
  return (
    <div className="page dashboard-page">
      <div className="page-heading"><div><p className="eyebrow">{t("admin.eyebrow")}</p><h1>{t("admin.title")}</h1><p>{t("admin.subtitle")}</p></div><div className="heading-state"><StatusBadge value="SIMULATION_ONLY" /><span>{user?.display_name ?? t("app.connecting")}</span></div></div>

      <section className="workspace-launch-section" aria-labelledby="workspace-launch-title">
        <div className="section-heading"><div><p className="eyebrow">{t("admin.workspace.eyebrow")}</p><h2 id="workspace-launch-title">{t("admin.workspace.title")}</h2></div><p>{t("admin.workspace.copy")}</p></div>
        <div className="workspace-launch-grid">
          {workspaces.map(({ to, title, label, copy, icon: Icon, role, accent }) => (
            <Link key={to} to={to} target="_blank" rel="noopener noreferrer" className={`workspace-launch-card workspace-launch-${accent}`}>
              <div className="workspace-launch-icon"><Icon size={24} aria-hidden="true" /></div>
              <span>{label}</span>
              <h3>{title}</h3>
              <p>{copy}</p>
              <footer><small>{t("admin.workspace.role", { role })}</small><strong>{t("admin.workspace.open")}<ArrowUpRight size={15} /></strong></footer>
            </Link>
          ))}
        </div>
      </section>

      <section className="system-settings-section" aria-labelledby="system-settings-title">
        <div className="section-heading"><div><p className="eyebrow">{t("admin.system.eyebrow")}</p><h2 id="system-settings-title">{t("admin.system.title")}</h2></div><p>{t("admin.system.copy")}</p></div>
        <div className="skeleton-grid">
          <Panel title={t("admin.preferences.title")} action={<StatusBadge value="LOCAL" subtle />}><div className="route-skeleton preference-settings"><MonitorCog size={26} /><strong>{t("admin.preferences.heading")}</strong><p>{t("admin.preferences.copy")}</p><PreferenceControls /></div></Panel>
          {cards.map(({ title, heading, copy, icon: Icon, status }) => <Panel key={title} title={title} action={<StatusBadge value={status} subtle />}><div className="route-skeleton"><Icon size={26} /><strong>{heading}</strong><p>{copy}</p></div></Panel>)}
        </div>
      </section>
    </div>
  );
}
