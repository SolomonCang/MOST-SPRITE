import { Languages, Moon, Sun } from "lucide-react";
import { useI18n } from "../i18n/I18nProvider";
import { useTheme } from "../theme/ThemeProvider";

export function PreferenceControls() {
  const { locale, setLocale, t } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const themeLabel = theme === "dark" ? t("app.themeLight") : t("app.themeDark");

  return (
    <div className="preference-controls">
      <div className="language-switch" role="group" aria-label={t("app.languageGroup")}>
        <Languages size={16} aria-hidden="true" />
        <button type="button" aria-pressed={locale === "zh-CN"} aria-label={t("app.languageChinese")} data-testid="locale-zh" onClick={() => setLocale("zh-CN")}>{t("app.languageChineseShort")}</button>
        <button type="button" aria-pressed={locale === "en-US"} aria-label={t("app.languageEnglish")} data-testid="locale-en" onClick={() => setLocale("en-US")}>EN</button>
      </div>
      <button className="icon-button" type="button" aria-label={themeLabel} title={themeLabel} data-testid="theme-toggle" onClick={toggleTheme}>
        {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
      </button>
    </div>
  );
}
