import type { Activity, ActivitySummary, AttentionAction, AttentionItem, AttentionKind, TransferStats } from "../../api/activity";
import type { StatusTone } from "../../components/StatusIndicator";
import { hasMessage, t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { formatBytes, formatDuration, formatMessage, formatPlural, interpolate } from "../../lib/format";

/** In-app destinations used by status, attention actions and desktop notifications. */
export const appRoutes = {
  account: "/settings/account",
  activity: "/activity",
  devices: "/settings/devices",
  jobs: "/jobs",
  recoveryKit: "/settings?section=recovery",
  settings: "/settings",
  trash: "/trash",
} as const;

export const activePollMs = 3_000;
export const idlePollMs = 15_000;

export type ActivityStatusKind =
  | "loading"
  | "unavailable"
  | "up_to_date"
  | "uploading"
  | "downloading"
  | "syncing"
  | "paused"
  | "offline"
  | "waiting"
  | "removed"
  | "attention";

export type ActivityStatus = {
  detail: string;
  kind: ActivityStatusKind;
  label: string;
  tone: StatusTone;
};

const summaries: readonly ActivitySummary[] = ["up_to_date", "uploading", "downloading", "syncing", "paused", "offline", "attention"];
const emptyStats: TransferStats = { active: 0, bytes_done: 0, bytes_total: 0, eta_seconds: null, queued: 0 };

/** Tolerates partial payloads so a half-implemented backend never breaks the shell. */
export function normalizeActivity(raw: unknown): Activity {
  const record = isRecord(raw) ? raw : {};
  const summary = summaries.includes(record.summary as ActivitySummary) ? (record.summary as ActivitySummary) : "up_to_date";

  return {
    attention: Array.isArray(record.attention) ? record.attention.flatMap(normalizeAttention) : [],
    downloads: normalizeStats(record.downloads),
    summary,
    uploads: normalizeStats(record.uploads),
  };
}

export function transferCount(stats: TransferStats): number {
  return stats.active + stats.queued;
}

export function transferPercent(stats: TransferStats): number | null {
  return stats.bytes_total > 0 ? Math.min(100, (stats.bytes_done / stats.bytes_total) * 100) : null;
}

export function hasActiveTransfers(activity: Activity | null): boolean {
  if (!activity) {
    return false;
  }

  return (
    ["uploading", "downloading", "syncing"].includes(activity.summary) ||
    transferCount(activity.uploads) > 0 ||
    transferCount(activity.downloads) > 0
  );
}

/** 3 s while something moves, 15 s when idle. */
export function activityPollInterval(activity: Activity | null): number {
  return hasActiveTransfers(activity) ? activePollMs : idlePollMs;
}

export function floodWaitItem(activity: Activity): AttentionItem | null {
  return activity.attention.find((item) => item.kind === "flood_wait") ?? null;
}

export function floodWaitSeconds(item: AttentionItem): number | null {
  for (const key of ["retry_after_seconds", "wait_seconds", "seconds"]) {
    const value = item.params[key];
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      return value;
    }
  }

  return null;
}

/** Items the user can act on; a flood wait resolves itself and is shown as status instead. */
export function actionableAttention(activity: Activity): AttentionItem[] {
  return activity.attention.filter((item) => item.kind !== "flood_wait");
}

/** One calm sentence for the sidebar footer and the top-bar pill. */
export function describeActivity(activity: Activity | null, error: Error | null = null): ActivityStatus {
  if (!activity) {
    return error
      ? status("unavailable", "idle", t("activity.status.unavailable"), t("activity.status.unavailableDetail"))
      : status("loading", "idle", t("activity.status.loading"), t("activity.status.loadingDetail"));
  }

  // Nothing syncs until this device joins again, so that outranks every other state.
  if (activity.attention.some((item) => item.kind === "device_removed")) {
    return status("removed", "warning", t("activity.status.removed"), t("activity.status.removedDetail"));
  }

  if (activity.summary === "offline") {
    return status("offline", "warning", t("activity.status.offline"), t("activity.status.offlineDetail"));
  }

  if (activity.summary === "paused") {
    return status("paused", "idle", t("activity.status.paused"), t("activity.status.pausedDetail"));
  }

  const flood = floodWaitItem(activity);
  if (flood) {
    const duration = formatDuration(floodWaitSeconds(flood));
    return status(
      "waiting",
      "warning",
      duration ? formatMessage("activity.status.waiting", { duration }) : t("activity.status.waitingShort"),
      t("activity.status.waitingDetail"),
    );
  }

  const attention = actionableAttention(activity);
  if (activity.summary === "attention" && attention.length > 0) {
    return status(
      "attention",
      "warning",
      formatPlural(attention.length, { one: "activity.status.attention.one", other: "activity.status.attention.other" }),
      attention.length === 1 ? attentionTitle(attention[0]) : t("activity.status.attentionDetail"),
    );
  }

  if (activity.summary === "uploading") {
    return transferStatus("uploading", activity.uploads, {
      indeterminate: "activity.status.uploading.indeterminate",
      one: "activity.status.uploading.one",
      other: "activity.status.uploading.other",
    });
  }

  if (activity.summary === "downloading") {
    return transferStatus("downloading", activity.downloads, {
      indeterminate: "activity.status.downloading.indeterminate",
      one: "activity.status.downloading.one",
      other: "activity.status.downloading.other",
    });
  }

  if (activity.summary === "syncing") {
    return status("syncing", "active", t("activity.status.syncing"), t("activity.status.syncingDetail"));
  }

  return status("up_to_date", "success", t("activity.status.upToDate"), t("activity.status.upToDateDetail"));
}

function transferStatus(
  kind: "uploading" | "downloading",
  stats: TransferStats,
  keys: { indeterminate: MessageKey; one: MessageKey; other: MessageKey },
): ActivityStatus {
  const count = transferCount(stats);
  const eta = formatDuration(stats.eta_seconds);
  const base = count > 0 ? formatPlural(count, keys) : t(keys.indeterminate);
  const detail =
    stats.bytes_total > 0
      ? formatMessage("activity.status.transferDetail", {
          done: formatBytes(stats.bytes_done),
          total: formatBytes(stats.bytes_total),
        })
      : base;

  return status(kind, "active", count > 0 && eta ? `${base} · ${eta}` : base, detail);
}

const attentionKinds: readonly AttentionKind[] = [
  "upload_failed",
  "sync_error",
  "flood_wait",
  "recovery_kit",
  "inbox_failed",
  "new_device",
  "device_removed",
  "clock_skew",
];

/** A kit saved before the cloud's keys changed (`params.reason = "stale"`) no longer opens it. */
export function isStaleKitItem(item: AttentionItem): boolean {
  return item.kind === "recovery_kit" && item.params.reason === "stale";
}

/** Uses the backend's `title_key` when the dictionary knows it, else a sentence for the kind. */
export function attentionTitle(item: AttentionItem): string {
  return interpolate(t(attentionTitleKey(item)), stringParams(item.params));
}

function attentionTitleKey(item: AttentionItem): MessageKey {
  if (isStaleKitItem(item)) return "activity.attention.recovery_kit.stale";
  if (item.kind === "new_device" && !nonEmptyString(item.params.name)) return "activity.attention.new_device.unnamed";
  if (hasMessage(item.title_key)) return item.title_key;
  return attentionKinds.includes(item.kind) ? (`activity.attention.${item.kind}` as MessageKey) : "activity.attention.generic";
}

export function attentionBody(item: AttentionItem): string {
  if (isStaleKitItem(item)) return t("activity.attention.recovery_kit.stale.body");
  return t(attentionKinds.includes(item.kind) ? (`activity.attention.${item.kind}.body` as MessageKey) : "activity.attention.generic.body");
}

/** Where a navigation action leads; null for actions handled in place (`retry`) or none. */
export function attentionHref(item: AttentionItem): string | null {
  switch (item.action) {
    case "open_devices":
      return appRoutes.devices;
    case "save_recovery_kit":
      return appRoutes.recoveryKit;
    case "open_settings":
      // A removed device is re-joined from Cuenta y nube.
      return item.kind === "device_removed" ? appRoutes.account : appRoutes.settings;
    default:
      return null;
  }
}

/** Jobs to retry for `retry` actions: `params.job_id` when present, else the item id. */
export function attentionJobId(item: AttentionItem): string {
  const jobId = item.params.job_id;
  return typeof jobId === "string" && jobId ? jobId : item.id;
}

function stringParams(params: Record<string, unknown>): Record<string, string | number> {
  const result: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string" || typeof value === "number") {
      result[key] = value;
    }
  }
  return result;
}

function status(kind: ActivityStatusKind, tone: StatusTone, label: string, detail: string): ActivityStatus {
  return { detail, kind, label, tone };
}

function normalizeStats(raw: unknown): TransferStats {
  if (!isRecord(raw)) {
    return emptyStats;
  }

  return {
    active: finiteOr(raw.active, 0),
    bytes_done: finiteOr(raw.bytes_done, 0),
    bytes_total: finiteOr(raw.bytes_total, 0),
    eta_seconds: typeof raw.eta_seconds === "number" && Number.isFinite(raw.eta_seconds) ? raw.eta_seconds : null,
    queued: finiteOr(raw.queued, 0),
  };
}

const attentionActions: readonly AttentionAction[] = ["retry", "open_settings", "save_recovery_kit", "open_devices", "none"];

function normalizeAttention(raw: unknown): AttentionItem[] {
  if (!isRecord(raw) || typeof raw.id !== "string" || typeof raw.kind !== "string") {
    return [];
  }

  const action = attentionActions.find((candidate) => candidate === raw.action) ?? "none";
  return [
    {
      action,
      id: raw.id,
      kind: raw.kind as AttentionKind,
      params: isRecord(raw.params) ? raw.params : {},
      title_key: typeof raw.title_key === "string" ? raw.title_key : "",
    },
  ];
}

function nonEmptyString(value: unknown): boolean {
  return typeof value === "string" && value.trim().length > 0;
}

function finiteOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
