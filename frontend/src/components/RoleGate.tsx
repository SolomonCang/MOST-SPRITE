import { LockKeyhole } from "lucide-react";
import type { ReactNode } from "react";
import { useI18n } from "../i18n/I18nProvider";
import type { CurrentUser, Role } from "../lib/types";

export function RoleGate({ user, allowed, children }: { user?: CurrentUser; allowed: Role[]; children: ReactNode }) {
  const { t } = useI18n();
  if (!user || (!allowed.includes(user.role) && user.role !== "administrator")) {
    return (
      <div className="access-gate">
        <LockKeyhole size={30} />
        <h1>{t("access.title")}</h1>
        <p>{t("access.description")}</p>
        <span>{t("access.required")}</span>
        <code>{allowed.join(" · ")}</code>
      </div>
    );
  }
  return children;
}
