import { Check, ChevronDown, LogOut, RefreshCw, UserRound } from "lucide-react";
import { useRef } from "react";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/translations";
import type { AuthConfiguration, CurrentUser, Role } from "../lib/types";

const roleKeys: Record<Role, TranslationKey> = {
  observer: "role.observer",
  instrument_engineer: "role.instrument_engineer",
  data_reducer: "role.data_reducer",
  administrator: "role.administrator",
};

export function AccountMenu({
  user,
  configuration,
  busy,
  onLogin,
  onLogout,
}: {
  user: CurrentUser;
  configuration: AuthConfiguration;
  busy: boolean;
  onLogin: (accountId: string) => Promise<void>;
  onLogout: () => Promise<void>;
}) {
  const { t } = useI18n();
  const details = useRef<HTMLDetailsElement>(null);
  const close = () => { if (details.current) details.current.open = false; };

  return (
    <details className="account-menu" ref={details}>
      <summary aria-label={t("auth.menu")}><UserRound size={16} /><ChevronDown size={13} /></summary>
      <div className="account-menu-popover">
        <header><strong>{user.display_name}</strong><small>{t(roleKeys[user.role])}</small></header>
        {configuration.auth_mode === "dev" && (
          <div className="account-switch-list">
            <p><RefreshCw size={12} />{t("auth.switch")}</p>
            {configuration.accounts.map((account) => {
              const current = account.username === user.subject;
              return (
                <button
                  key={account.id}
                  type="button"
                  disabled={busy || current}
                  onClick={() => { close(); void onLogin(account.id); }}
                >
                  <span><strong>{account.display_name}</strong><small>{t(roleKeys[account.role])}</small></span>
                  {current && <Check size={14} />}
                </button>
              );
            })}
          </div>
        )}
        <button className="account-logout" type="button" disabled={busy} onClick={() => { close(); void onLogout(); }}><LogOut size={14} />{t("auth.logout")}</button>
      </div>
    </details>
  );
}
