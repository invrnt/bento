import { defaultLocale, t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";

export type MessageParams = Record<string, number | string>;

/** Translates a key and fills `{name}` placeholders. */
export function tf(key: MessageKey, params: MessageParams = {}): string {
  return t(key).replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

// ES2023 `useGrouping: "always"`; the ES2022 lib in tsconfig only types booleans.
const alwaysGroup = { useGrouping: "always" } as unknown as Intl.NumberFormatOptions;

/** Counts such as "1.240 de 3.000": always grouped, even for 4-digit numbers in Spanish. */
export function formatNumber(value: number): string {
  return new Intl.NumberFormat(defaultLocale, alwaysGroup).format(value);
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 1024) return `${formatNumber(Math.max(0, Math.round(bytes || 0)))} B`;
  const units = ["KB", "MB", "GB", "TB", "PB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length);
  const value = bytes / 1024 ** exponent;
  const formatted = new Intl.NumberFormat(defaultLocale, { maximumFractionDigits: value >= 10 ? 0 : 1 }).format(value);
  return `${formatted} ${units[exponent - 1]}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(defaultLocale, { dateStyle: "long" }).format(date);
}

const relativeSteps: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 7],
  ["week", 4.35],
  ["month", 12],
  ["year", Number.POSITIVE_INFINITY],
];

/** "hace 5 minutos" / "5 minutes ago". */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "";
  let value = (time - now) / 1000;
  const formatter = new Intl.RelativeTimeFormat(defaultLocale, { numeric: "auto" });
  for (const [unit, size] of relativeSteps) {
    if (Math.abs(value) < size) return formatter.format(Math.round(value), unit);
    value /= size;
  }
  return formatter.format(Math.round(value), "year");
}

/** "4:05" for countdowns. */
export function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.ceil(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** Human wait such as "45 s", "4 min" or "1 h 5 min". */
export function formatWait(totalSeconds: number): string {
  const safe = Math.max(0, Math.ceil(totalSeconds));
  if (safe < 60) return `${safe} s`;
  const minutes = Math.ceil(safe / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}
