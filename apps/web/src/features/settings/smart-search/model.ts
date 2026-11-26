import { useEffect, useRef, useState } from "react";

import type { SmartSearchErrorCode, SmartSearchNoSpaceDetails, SmartSearchState, SmartSearchStatus } from "../../../api/smartSearch";
import { smartSearchErrorCodes } from "../../../api/smartSearch";
import type { BadgeTone } from "../../../components/Badge";
import { t } from "../../../i18n/dictionary";
import type { MessageKey } from "../../../i18n/dictionary";
import { appLocale, formatMessage } from "../../../lib/format";
import { apiErrorBody } from "../../onboarding/apiErrors";
import { formatCount } from "../../onboarding/format";

/** States with work running in the background: poll often and show progress. */
export const busyStates: ReadonlySet<SmartSearchState> = new Set<SmartSearchState>(["downloading", "verifying", "starting", "indexing"]);
/** `POST /smart-search/cancel` is legal from these. */
export const cancellableStates: ReadonlySet<SmartSearchState> = new Set<SmartSearchState>(["downloading", "paused", "verifying", "starting", "error"]);
/** Turning the switch off here asks to remove the installed model. */
export const removableStates: ReadonlySet<SmartSearchState> = new Set<SmartSearchState>(["indexing", "ready"]);

const errorMessages: Record<SmartSearchErrorCode, MessageKey> = {
  checksum: "smartSearch.state.error.checksum",
  download: "smartSearch.state.error.download",
  runtime: "smartSearch.state.error.runtime",
  space: "smartSearch.state.error.space",
};

const badges: Record<SmartSearchState, { label: MessageKey; pulse?: boolean; tone: BadgeTone }> = {
  downloading: { label: "smartSearch.badge.working", pulse: true, tone: "accent" },
  error: { label: "smartSearch.badge.error", tone: "danger" },
  indexing: { label: "smartSearch.badge.working", pulse: true, tone: "accent" },
  off: { label: "smartSearch.state.off", tone: "neutral" },
  paused: { label: "smartSearch.badge.paused", tone: "warning" },
  ready: { label: "smartSearch.state.ready", tone: "success" },
  starting: { label: "smartSearch.badge.working", pulse: true, tone: "accent" },
  verifying: { label: "smartSearch.badge.working", pulse: true, tone: "accent" },
};

const siUnits = ["B", "KB", "MB", "GB", "TB"] as const;

/**
 * Model sizes in decimal units, as the model card and the confirmation sheet state them
 * (309,855,456 B → "310 MB"); progress and free space use the same scale so they add up.
 */
export function formatModelBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return "";
  const value = Math.max(0, bytes);
  let exponent = value < 1000 ? 0 : Math.min(Math.floor(Math.log10(value) / 3), siUnits.length - 1);
  let scaled = value / 1000 ** exponent;
  if (scaled >= 999.95 && exponent < siUnits.length - 1) {
    exponent += 1;
    scaled /= 1000;
  }
  const maximumFractionDigits = exponent === 0 || scaled >= 100 ? 0 : 1;
  return `${new Intl.NumberFormat(appLocale(), { maximumFractionDigits }).format(scaled)} ${siUnits[exponent]}`;
}

export function formatPercent(percent: number): string {
  return formatMessage("smartSearch.progress.percent", { percent: new Intl.NumberFormat(appLocale(), { maximumFractionDigits: 0 }).format(Math.floor(percent)) });
}

export type SmartSearchProgressView = { kind: "download" | "indexing"; percent: number };

export type SmartSearchView = {
  badge: { label: string; pulse: boolean; tone: BadgeTone };
  /** Shows a spinner instead of a bar (verifying, starting). */
  indeterminate: boolean;
  progress: SmartSearchProgressView | null;
  text: string;
};

function ratio(done: number, total: number): number {
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) return 0;
  return Math.min(100, Math.max(0, (done / total) * 100));
}

/** One place that turns a status body into the copy, badge and progress the section shows. */
export function describeSmartSearch(status: SmartSearchStatus): SmartSearchView {
  const badge = badges[status.state] ?? badges.off;
  const view = (text: string, progress: SmartSearchProgressView | null = null, indeterminate = false): SmartSearchView => ({
    badge: { label: t(badge.label), pulse: Boolean(badge.pulse), tone: badge.tone },
    indeterminate,
    progress,
    text,
  });
  const download = { kind: "download" as const, percent: ratio(status.download.bytes_done, status.download.bytes_total) };
  const bytes = { done: formatModelBytes(status.download.bytes_done), total: formatModelBytes(status.download.bytes_total) };

  switch (status.state) {
    case "downloading":
      return status.waiting_network
        ? view(t("smartSearch.state.waitingNetwork"), download)
        : view(formatMessage("smartSearch.state.downloading", bytes), download);
    case "paused":
      return view(formatMessage("smartSearch.state.paused", bytes), download);
    case "verifying":
      return view(t("smartSearch.state.verifying"), null, true);
    case "starting":
      return view(t("smartSearch.state.starting"), null, true);
    case "indexing":
      return status.indexing.total > 0
        ? view(
            formatMessage("smartSearch.state.indexing", { done: formatCount(status.indexing.done), total: formatCount(status.indexing.total) }),
            { kind: "indexing", percent: ratio(status.indexing.done, status.indexing.total) },
          )
        : view(t("smartSearch.state.indexingStart"), null, true);
    case "ready":
      return view(t("smartSearch.state.ready"));
    case "error":
      return view(t(errorMessages[status.error_code ?? "download"] ?? errorMessages.download));
    default:
      return view(t("smartSearch.state.off"));
  }
}

/** The precheck the API applies on activation: free space must cover the model plus 10 %. */
export function requiredBytes(sizeBytes: number): number {
  return Math.ceil(sizeBytes * 1.1);
}

export function hasRoomForModel(status: SmartSearchStatus | null): boolean {
  if (!status?.model) return false;
  if (status.free_bytes === null || status.free_bytes === undefined) return true;
  return status.free_bytes >= requiredBytes(status.model.size_bytes);
}

export function spaceMessage(required: number, free: number): string {
  return formatMessage("smartSearch.activate.space", { free: formatModelBytes(free), size: formatModelBytes(required) });
}

/** What to tell the person when a smart search request is refused. */
export function actionErrorMessage(error: unknown): string {
  const body = apiErrorBody(error);
  if (body?.code === smartSearchErrorCodes.locked) return t("smartSearch.locked");
  if (body?.code === smartSearchErrorCodes.stateConflict) return t("smartSearch.error.conflict");
  if (body?.code === smartSearchErrorCodes.noSpace) {
    const details = body.details as Partial<SmartSearchNoSpaceDetails>;
    if (typeof details.required_bytes === "number" && typeof details.free_bytes === "number") return spaceMessage(details.required_bytes, details.free_bytes);
    return t("smartSearch.state.error.space");
  }
  return t("smartSearch.error.action");
}

/* ------------------------------------------------------------------------------------------------
 * Live-region announcements: on every state change, and at most once per 10 % of progress.
 * --------------------------------------------------------------------------------------------- */

export type Announcement = { bucket: number; key: string; message: string };

function announcementKey(status: SmartSearchStatus): string {
  return `${status.state}:${status.waiting_network ? "offline" : "online"}:${status.error_code ?? ""}`;
}

/**
 * Returns the next announcement, or `null` when nothing worth saying changed. The first status
 * seen is recorded without a message: the current state is already on screen.
 */
export function nextAnnouncement(previous: Announcement | null, status: SmartSearchStatus | null): Announcement | null {
  if (!status) return null;
  const view = describeSmartSearch(status);
  const key = announcementKey(status);
  const bucket = view.progress ? Math.floor(view.progress.percent / 10) : -1;
  if (!previous) return { bucket, key, message: "" };
  if (previous.key === key && previous.bucket === bucket) return null;
  const message = view.progress ? formatMessage("smartSearch.announce.progress", { percent: formatPercent(view.progress.percent), state: view.text }) : view.text;
  return { bucket, key, message };
}

/** The polite live-region text for `status`, throttled by `nextAnnouncement`. */
export function useThrottledAnnouncement(status: SmartSearchStatus | null): string {
  const last = useRef<Announcement | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const next = nextAnnouncement(last.current, status);
    if (!next) return;
    last.current = next;
    if (next.message) setMessage(next.message);
  }, [status]);

  return message;
}

/* ------------------------------------------------------------------------------------------------
 * Onboarding suggestion (D8): the same thresholds as `suggest_in_onboarding` in the domain.
 * --------------------------------------------------------------------------------------------- */

export const onboardingMinCores = 4;
export const onboardingMinRamBytes = 8 * 1024 ** 3;

export type Hardware = { cores: number | null; ramBytes: number | null };

/** The API runs on this machine (loopback only), so the browser's numbers describe it. */
export function detectHardware(): Hardware {
  if (typeof navigator === "undefined") return { cores: null, ramBytes: null };
  const nav = navigator as Navigator & { deviceMemory?: number };
  const cores = typeof nav.hardwareConcurrency === "number" && nav.hardwareConcurrency > 0 ? nav.hardwareConcurrency : null;
  // `deviceMemory` is capped at 8 (GiB) by Chromium, which is exactly the threshold.
  const ramBytes = typeof nav.deviceMemory === "number" && nav.deviceMemory > 0 ? nav.deviceMemory * 1024 ** 3 : null;
  return { cores, ramBytes };
}

/** Unknown numbers never suggest: the person can still turn it on in Ajustes. */
export function suggestInOnboarding(hardware: Hardware): boolean {
  return hardware.cores !== null && hardware.ramBytes !== null && hardware.cores >= onboardingMinCores && hardware.ramBytes >= onboardingMinRamBytes;
}
