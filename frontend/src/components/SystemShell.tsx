import { Activity, ShieldCheck } from "lucide-react";
import { useEffect } from "react";
import { Link, Outlet, useOutletContext } from "react-router-dom";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/translations";
import type { Role } from "../lib/types";
import { useTheme } from "../theme/ThemeProvider";
import type { ShellOutletContext } from "./AppShell";
import { AccountMenu } from "./AccountMenu";
import { PreferenceControls } from "./PreferenceControls";
import { StatusBadge } from "./StatusBadge";

const roleKeys: Record<Role, TranslationKey> = {
  observer: "role.observer",
  instrument_engineer: "role.instrument_engineer",
  data_reducer: "role.data_reducer",
  administrator: "role.administrator",
};

export function SystemShell() {
  const context = useOutletContext<ShellOutletContext>();
  const { t } = useI18n();
  const { theme } = useTheme();

  useEffect(() => {
    document.title = `MOST-SPRITE · ${t("admin.title")}`;
  }, [t]);

  return (
    <div className="system-shell">
      <header className="system-topbar">
        <Link to="/admin" className="system-brand" aria-label={t("admin.title")}>
          <img src={theme === "dark" ? "/brand/most-sprite-logo-dark.png" : "/brand/most-sprite-logo.png"} alt="MOST-SPRITE" />
          <span><strong>MOST-SPRITE</strong><small>CONTROL CENTER</small></span>
        </Link>
        <div className="system-topbar-status">
          <Activity size={16} aria-hidden="true" />
          <span>{t("app.serviceStatus")}</span>
          <StatusBadge value={context.serviceHealthy ? "HEALTHY" : "STALE"} subtle />
          <span className="system-simulation"><ShieldCheck size={14} />{t("app.simulation")}</span>
        </div>
        <div className="system-account">
          <div className="identity-avatar">{context.user.display_name.slice(0, 2).toUpperCase()}</div>
          <div><strong>{context.user.display_name}</strong><small>{t(roleKeys[context.user.role])}</small></div>
          <PreferenceControls />
          <AccountMenu user={context.user} configuration={context.auth} busy={context.authBusy} onLogin={context.login} onLogout={context.logout} />
        </div>
      </header>
      <main className="system-content"><Outlet context={context} /></main>
    </div>
  );
}
