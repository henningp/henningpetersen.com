import type { Locale } from "./config";

type LocaleStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function getDefaultLocale(language = navigator.language || "en"): Locale {
  return language.toLowerCase().startsWith("de") ? "de" : "en";
}

export function isLocale(value: unknown): value is Locale {
  return value === "en" || value === "de";
}

export function getLocale(
  defaultLocale = getDefaultLocale(),
  storage: () => LocaleStorage = () => localStorage,
): Locale {
  try {
    const stored = storage().getItem("locale");
    if (isLocale(stored)) return stored;
  } catch {
    // Storage may be blocked; browser detection still works.
  }
  return defaultLocale;
}

/** Persist only explicit overrides, never the browser's default language. */
export function saveLocale(
  locale: Locale,
  defaultLocale = getDefaultLocale(),
  storage: () => LocaleStorage = () => localStorage,
): void {
  try {
    if (locale === defaultLocale) storage().removeItem("locale");
    else storage().setItem("locale", locale);
  } catch {
    // The active locale remains usable even when persistence is unavailable.
  }
}
