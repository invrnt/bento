import { appLocale } from "../../lib/format";

// Shared formatters live in lib/format.ts; `tf` is the short name used across the core flows.
export { formatBytes, formatDuration, formatMessage as tf } from "../../lib/format";
export type { MessageParams } from "../../lib/format";

// ES2023 `useGrouping: "always"`; the ES2022 lib in tsconfig only types booleans.
const alwaysGroup = { useGrouping: "always" } as unknown as Intl.NumberFormatOptions;

/** Counts such as "1.240 de 3.000": always grouped, even for 4-digit numbers in Spanish. */
export function formatCount(value: number): string {
  return new Intl.NumberFormat(appLocale(), alwaysGroup).format(value);
}

/** Full date with year, for the printed kit and device history: "31 de octubre de 2026". */
export function formatLongDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(appLocale(), { dateStyle: "long" }).format(date);
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
  const formatter = new Intl.RelativeTimeFormat(appLocale(), { numeric: "auto" });
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
