import { useQuery } from "@tanstack/react-query";
import { Activity, Database, Gauge, Settings2, ShieldCheck, Telescope, Thermometer, Waves } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/translations";
import { api } from "../lib/api";
import { useUtcClock } from "../lib/hooks";
import type { Role } from "../lib/types";
import { useTheme } from "../theme/ThemeProvider";
import { PreferenceControls } from "./PreferenceControls";
import { StatusBadge } from "./StatusBadge";

const nav = [
  { to: "/observe", label: "app.nav.observe", detail: "app.nav.observeHint", icon: Telescope },
  { to: "/engineering", label: "app.nav.engineering", detail: "app.nav.engineeringHint", icon: Gauge },
  { to: "/data", label: "app.nav.data", detail: "app.nav.dataHint", icon: Database },
  { to: "/admin", label: "app.nav.admin", detail: "app.nav.adminHint", icon: Settings2 },
] satisfies Array<{ to: string; label: TranslationKey; detail: TranslationKey; icon: typeof Telescope }>;

const roleKeys: Record<Role, TranslationKey> = {
  observer: "role.observer",
  instrument_engineer: "role.instrument_engineer",
  data_reducer: "role.data_reducer",
  administrator: "role.administrator",
};

export function AppShell() {
  const utc = useUtcClock();
  const { t } = useI18n();
  const { theme } = useTheme();
  const user = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60_000 });
  const instrument = useQuery({ queryKey: ["instrument"], queryFn: api.instrument, refetchInterval: 1500 });
  const temperature = instrument.data?.devices.temperature_c;
  const humidity = instrument.data?.devices.humidity_percent;
  const serviceHealthy = Boolean(instrument.data?.fresh && !instrument.isError);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <img src={theme === "dark" ? "/brand/most-sprite-logo-dark.png" : "/brand/most-sprite-logo.png"} alt="MOST-SPRITE" />
        </div>
        <div className="simulation-ribbon" title={t("app.simulationTitle")}><ShieldCheck size={14} /> {t("app.simulation")}</div>
        <nav aria-label={t("app.nav.aria")}>
          {nav.map(({ to, label, detail, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "nav-active" : "")}>
              <Icon size={19} aria-hidden="true" />
              <span><strong>{t(label)}</strong><small>{t(detail)}</small></span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-status">
          <div><Activity size={15} /><span>{t("app.serviceStatus")}</span></div>
          <StatusBadge value={serviceHealthy ? "HEALTHY" : "STALE"} subtle />
          <small>{serviceHealthy ? t("app.serviceHealthy") : t("app.serviceDegraded")}</small>
        </div>
        <div className="sidebar-foot">
          <div className="identity-avatar">{user.data?.display_name.slice(0, 2).toUpperCase() ?? "--"}</div>
          <div><strong>{user.data?.display_name ?? t("app.connecting")}</strong><small>{user.data ? t(roleKeys[user.data.role]) : t("app.identityLoading")}</small></div>
        </div>
      </aside>
      <main className="main-shell">
        <header className="topbar">
          <div className="top-status">
            <Activity size={17} aria-hidden="true" />
            <span>{t("app.instrument")}</span>
            <StatusBadge value={instrument.data?.state ?? "CONNECTING"} subtle />
            <StatusBadge value={instrument.data?.fresh ? "FRESH" : "STALE"} subtle />
          </div>
          <div className="top-telemetry" aria-label={t("app.environment")}>
            <span><Thermometer size={14} /><b>TEMP</b>{typeof temperature === "number" ? `${temperature.toFixed(1)} °C` : "—"}</span>
            <span><Waves size={14} /><b>RH</b>{typeof humidity === "number" ? `${humidity.toFixed(0)} %` : "—"}</span>
          </div>
          <div className="top-actions">
            <div className="utc-clock"><span>{t("common.utc")}</span><time>{utc.replace("T", " ").slice(0, 19)}</time></div>
            <PreferenceControls />
          </div>
        </header>
        <div className="mobile-safety-notice"><ShieldCheck size={16} />{t("app.mobileNotice")}</div>
        <div className="route-content"><Outlet context={{ user: user.data }} /></div>
      </main>
    </div>
  );
}
