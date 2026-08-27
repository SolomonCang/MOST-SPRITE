import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { translations, type Locale, type TranslationKey } from "./translations";

const STORAGE_KEY = "most-sprite.locale";

type TranslationValues = Record<string, string | number>;

interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey, values?: TranslationValues) => string;
  formatUtc: (value: string | Date, includeSeconds?: boolean) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

function initialLocale(): Locale {
  if (typeof window === "undefined") return "zh-CN";
  const saved = window.localStorage.getItem(STORAGE_KEY);
  return saved === "en-US" || saved === "zh-CN" ? saved : "zh-CN";
}

function interpolate(template: string, values?: TranslationValues): string {
  if (!values) return template;
  return template.replace(/\{([^}]+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  );
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(initialLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
    window.localStorage.setItem(STORAGE_KEY, locale);
  }, [locale]);

  const t = useCallback(
    (key: TranslationKey, values?: TranslationValues) => interpolate(translations[locale][key], values),
    [locale],
  );

  const formatUtc = useCallback(
    (value: string | Date, includeSeconds = false) =>
      new Intl.DateTimeFormat(locale, {
        timeZone: "UTC",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        ...(includeSeconds ? { second: "2-digit" } : {}),
        hour12: false,
      }).format(typeof value === "string" ? new Date(value) : value),
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t, formatUtc }), [formatUtc, locale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used within I18nProvider");
  return value;
}
