import { KeyRound, LoaderCircle, ShieldCheck, UserRound } from "lucide-react";
import { PreferenceControls } from "./PreferenceControls";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/translations";
import type { AuthConfiguration, Role } from "../lib/types";
import { useTheme } from "../theme/ThemeProvider";

const roleKeys: Record<Role, TranslationKey> = {
  observer: "role.observer",
  instrument_engineer: "role.instrument_engineer",
  data_reducer: "role.data_reducer",
  administrator: "role.administrator",
};

export function LoginPage({
  configuration,
  loading,
  busy,
  error,
  onLogin,
}: {
  configuration?: AuthConfiguration;
  loading: boolean;
  busy: boolean;
  error?: string;
  onLogin: (accountId: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const { theme } = useTheme();

  return (
    <div className="auth-screen">
      <header className="auth-screen-header">
        <div className="auth-brand">
          <img src={theme === "dark" ? "/brand/most-sprite-logo-dark.png" : "/brand/most-sprite-logo.png"} alt="MOST-SPRITE" />
          <span><strong>MOST-SPRITE</strong><small>LOCAL ACCESS</small></span>
        </div>
        <PreferenceControls />
      </header>
      <main className="auth-card">
        <div className="auth-card-heading">
          <div className="auth-key-icon"><KeyRound size={26} /></div>
          <div><p className="eyebrow">LOCAL IDENTITY</p><h1>{t("auth.title")}</h1></div>
        </div>
        <p className="auth-description">{t("auth.description")}</p>
        <div className="auth-key-notice"><ShieldCheck size={17} /><span><strong>{t("auth.keyReady")}</strong>{t("auth.keyCopy")}</span></div>

        {loading ? (
          <div className="auth-loading"><LoaderCircle className="spin" size={22} />{t("auth.loading")}</div>
        ) : configuration?.accounts.length ? (
          <div className="auth-account-list" aria-label={t("auth.accounts")}>
            {configuration.accounts.map((account) => {
              const isDefault = account.id === configuration.default_account_id;
              return (
                <button key={account.id} type="button" disabled={busy} onClick={() => void onLogin(account.id)}>
                  <span className="auth-account-avatar"><UserRound size={19} /></span>
                  <span><strong>{account.display_name}</strong><small>@{account.username} · {t(roleKeys[account.role])}</small></span>
                  {isDefault && <em>{t("auth.default")}</em>}
                </button>
              );
            })}
          </div>
        ) : (
          <div className="auth-loading">{t("auth.noAccounts")}</div>
        )}
        {error && <p className="auth-error" role="alert">{t("auth.error")}</p>}
        <footer>{t("auth.footer")}</footer>
      </main>
    </div>
  );
}
