import { Activity, ArrowLeft, Boxes, Database, Gauge, ShieldCheck, Telescope, type LucideIcon } from "lucide-react";
import { useEffect } from "react";
import { Link, Outlet, useLocation, useOutletContext } from "react-router-dom";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/translations";
import { useUtcClock } from "../lib/hooks";
import type { Role } from "../lib/types";
import type { ShellOutletContext } from "./AppShell";
import { AccountMenu } from "./AccountMenu";
import { PreferenceControls } from "./PreferenceControls";
import { StatusBadge } from "./StatusBadge";

export type WorkspaceKind = "observe" | "engineering" | "data";

const workspaceConfig: Record<WorkspaceKind, { title: TranslationKey; eyebrow: TranslationKey; description: TranslationKey; icon: LucideIcon }> = {
  observe: { title: "workspace.observe.title", eyebrow: "workspace.observe.eyebrow", description: "workspace.observe.description", icon: Telescope },
  engineering: { title: "workspace.engineering.title", eyebrow: "workspace.engineering.eyebrow", description: "workspace.engineering.description", icon: Gauge },
  data: { title: "workspace.data.title", eyebrow: "workspace.data.eyebrow", description: "workspace.data.description", icon: Database },
};

const roleKeys: Record<Role, TranslationKey> = {
  observer: "role.observer",
  instrument_engineer: "role.instrument_engineer",
  data_reducer: "role.data_reducer",
  administrator: "role.administrator",
};

export function WorkspaceShell({ workspace }: { workspace: WorkspaceKind }) {
  const context = useOutletContext<ShellOutletContext>();
  const { t } = useI18n();
  const location = useLocation();
  const utc = useUtcClock();
  const config = workspaceConfig[workspace];
  const Icon = config.icon;
  const statusValue = workspace === "data"
    ? context.serviceHealthy ? "READY" : "DEGRADED"
    : context.instrument?.state ?? "CONNECTING";
  const statusLabel = workspace === "data" ? t("workspace.data.pipeline") : t("app.instrument");

  useEffect(() => {
    document.title = location.pathname.endsWith("/spectrum")
      ? `MOST-SPRITE · L3 · ${t("data.preview.spectrumTitle")}`
      : `MOST-SPRITE · ${t(config.title)}`;
  }, [config.title, location.pathname, t]);

  return (
    <div className={`workspace-shell workspace-shell-${workspace}`}>
      <header className="workspace-topbar">
        <div className="workspace-identity">
          <Link to="/admin" className="dashboard-return"><ArrowLeft size={16} /><span>{t("workspace.back")}</span></Link>
          <div className="workspace-mark"><Icon size={21} aria-hidden="true" /></div>
          <div><p>{t(config.eyebrow)}</p><strong>{t(config.title)}</strong></div>
        </div>
        <div className="workspace-live-state">
          <Activity size={16} />
          <span>{statusLabel}</span>
          <StatusBadge value={statusValue} subtle />
          {workspace !== "data" && <StatusBadge value={context.instrument?.fresh ? "FRESH" : "STALE"} subtle />}
        </div>
        <div className="workspace-actions">
          <div className="workspace-clock"><span>{t("common.utc")}</span><time>{utc.replace("T", " ").slice(0, 19)}</time></div>
          <div className="workspace-user"><strong>{context.user.display_name}</strong><small>{t(roleKeys[context.user.role])}</small></div>
          <PreferenceControls />
          <AccountMenu user={context.user} configuration={context.auth} busy={context.authBusy} onLogin={context.login} onLogout={context.logout} />
        </div>
      </header>
      <div className="workspace-context-strip">
        <span><Boxes size={14} />{t("workspace.independent")}</span>
        <span><ShieldCheck size={14} />{workspace === "data" ? t("workspace.data.boundary") : t("workspace.deviceBoundary")}</span>
        <p>{t(config.description)}</p>
      </div>
      <div className="workspace-mobile-notice"><ShieldCheck size={16} />{t("app.mobileNotice")}</div>
      <main className="workspace-content"><Outlet context={context} /></main>
    </div>
  );
}
