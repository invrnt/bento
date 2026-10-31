import { t } from "../i18n/dictionary";
import type { MessageKey } from "../i18n/dictionary";

export type MessageParams = Record<string, number | string>;

/** BCP 47 tag of the active dictionary (`es` or `en`). */
export function appLocale(): string {
  return t("app.locale");
}

/** Replaces `{name}` placeholders; unknown placeholders are left untouched. */
export function interpolate(template: string, params: MessageParams = {}): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match,
  );
}

export function formatMessage(key: MessageKey, params: MessageParams = {}): string {
  return interpolate(t(key), params);
}

/** Picks the `one`/`other` message with the active locale's plural rules; `{count}` is filled in. */
export function formatPlural(
  count: number,
  keys: { one: MessageKey; other: MessageKey },
  params: MessageParams = {},
): string {
  const rule = new Intl.PluralRules(appLocale()).select(count);
  return formatMessage(rule === "one" ? keys.one : keys.other, { count: formatNumber(count), ...params });
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat(appLocale()).format(value);
}

const byteUnits = ["B", "KB", "MB", "GB", "TB", "PB"] as const;

/** Human file size with local decimals: `1,5 KB`, `48,8 GB`, `512 MB`. Empty for unknown sizes. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) {
    return "";
  }

  const value = Math.max(0, bytes);
  let exponent = value < 1024 ? 0 : Math.min(Math.floor(Math.log(value) / Math.log(1024)), byteUnits.length - 1);
  let scaled = value / 1024 ** exponent;

  if (scaled >= 1023.95 && exponent < byteUnits.length - 1) {
    exponent += 1;
    scaled /= 1024;
  }

  const maximumFractionDigits = exponent === 0 || scaled >= 100 ? 0 : 1;
  return `${new Intl.NumberFormat(appLocale(), { maximumFractionDigits }).format(scaled)} ${byteUnits[exponent]}`;
}

/** Rounded-up remaining time: `3 min`, `1 h 20 min`. `null` when unknown. */
export function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return null;
  }

  const minutes = Math.max(1, Math.ceil(seconds / 60));
  if (minutes < 60) {
    return formatUnit(minutes, "minute");
  }

  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${formatUnit(hours, "hour")} ${formatUnit(rest, "minute")}` : formatUnit(hours, "hour");
}

function formatUnit(value: number, unit: "hour" | "minute"): string {
  return new Intl.NumberFormat(appLocale(), { style: "unit", unit, unitDisplay: "short" }).format(value);
}

/** Calendar date such as `1 de noviembre` (adds the year when it is not the current one). */
export function formatDay(value: string | null | undefined, now: Date = new Date()): string {
  const date = value ? new Date(value) : null;

  if (!date || Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat(appLocale(), {
    day: "numeric",
    month: "long",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  }).format(date);
}
