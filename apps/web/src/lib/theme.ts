import { useSyncExternalStore } from "react";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const themePreferences: ThemePreference[] = ["system", "light", "dark"];

const storageKey = "bento:theme";
const darkQuery = "(prefers-color-scheme: dark)";
const listeners = new Set<() => void>();

let preference: ThemePreference = readStoredPreference();
let mediaQuery: MediaQueryList | null = null;

export function initTheme(): void {
  applyTheme();

  if (mediaQuery || typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return;
  }

  mediaQuery = window.matchMedia(darkQuery);
  mediaQuery.addEventListener("change", () => {
    if (preference === "system") {
      applyTheme();
      notify();
    }
  });
}

export function setThemePreference(next: ThemePreference): void {
  preference = next;

  try {
    window.localStorage.setItem(storageKey, next);
  } catch {
    // Private windows can deny storage; the choice still applies to this session.
  }

  applyTheme();
  notify();
}

export function resolveTheme(value: ThemePreference = preference): ResolvedTheme {
  if (value !== "system") {
    return value;
  }

  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    return window.matchMedia(darkQuery).matches ? "dark" : "light";
  }

  return "light";
}

export function useThemePreference(): ThemePreference {
  return useSyncExternalStore(subscribe, () => preference, () => "system");
}

function applyTheme(): void {
  if (typeof document === "undefined") {
    return;
  }

  document.documentElement.dataset.theme = resolveTheme();
}

function readStoredPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(storageKey);
    return themePreferences.includes(stored as ThemePreference) ? (stored as ThemePreference) : "system";
  } catch {
    return "system";
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify(): void {
  listeners.forEach((listener) => listener());
}
