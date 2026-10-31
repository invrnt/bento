import type { Locale } from "./dictionary";

const STORAGE_KEY = "bento.locale";
const supported: readonly Locale[] = ["es", "en"];

function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (supported as readonly string[]).includes(value);
}

/** Saved choice, else the browser/OS language, else Spanish. */
export function detectLocale(): Locale {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (isLocale(saved)) return saved;
  } catch {
    // Storage can be unavailable (private mode, sandboxed previews).
  }
  const language = typeof navigator !== "undefined" ? navigator.language.slice(0, 2).toLowerCase() : "es";
  return isLocale(language) ? language : "es";
}

/** Persists the choice and reloads, because navigation labels are resolved at module load. */
export function setLocale(locale: Locale, reload: () => void = () => window.location.reload()): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Without storage the choice lasts for this session only.
  }
  reload();
}

export const supportedLocales = supported;
