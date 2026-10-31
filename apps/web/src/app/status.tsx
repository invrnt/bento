import { useEffect, useRef, useState } from "react";
import { HardDrive } from "lucide-react";

import { absoluteApiPath } from "../api/client";
import { accountAvatarPath, getAccount } from "../api/account";
import type { AccountStatus, TelegramAccount } from "../api/account";
import { getVault } from "../api/vault";
import type { VaultStatus } from "../api/vault";
import { StatusDot } from "../components/Badge";
import { StatusIndicator, statusToneMap } from "../components/StatusIndicator";
import { appRoutes, describeActivity } from "../features/activity/activityModel";
import type { ActivityStatus } from "../features/activity/activityModel";
import { activityStore, useActivity } from "../features/activity/activityStore";
import type { ActivityStore } from "../features/activity/activityStore";
import { t } from "../i18n/dictionary";
import { formatBytes, formatMessage } from "../lib/format";
import { cx } from "../lib/cx";
import { usePolledResource } from "../lib/usePolledResource";

type NavigateProps = {
  onNavigate?: (href: string) => void;
};

/* ------------------------------------------------------------------------------------------------
 * Top-bar pill
 * --------------------------------------------------------------------------------------------- */

export type ActivityStatusPillProps = NavigateProps & {
  status: ActivityStatus;
};

/** The always-visible pill in the top bar. One polite live region for the whole shell. */
export function ActivityStatusPill({ onNavigate, status }: ActivityStatusPillProps) {
  return (
    <div aria-live="polite" role="status">
      <StatusIndicator
        detail={status.detail}
        href={appRoutes.activity}
        label={status.label}
        onNavigate={onNavigate}
        tone={status.tone}
      />
    </div>
  );
}

export function ConnectedActivityStatusPill({ onNavigate, store = activityStore }: NavigateProps & { store?: ActivityStore }) {
  const { activity, error } = useActivity(store);
  return <ActivityStatusPill onNavigate={onNavigate} status={describeActivity(activity, error)} />;
}

/**
 * @deprecated Kept so `App.tsx` keeps compiling unchanged; it now shows the `/activity` summary.
 * Switch the import to `ConnectedActivityStatusPill`.
 */
export const ConnectedGlobalJobStatusIndicator = ConnectedActivityStatusPill;

/* ------------------------------------------------------------------------------------------------
 * Sidebar footer
 * --------------------------------------------------------------------------------------------- */

export type SidebarUsage = { bytes: number; scope: "cloud" | "device" };

export type SidebarStatusProps = NavigateProps & {
  account: TelegramAccount | null;
  avatarUrl?: string | null;
  status: ActivityStatus;
  usage: SidebarUsage | null;
};

/** Avatar, usage and one status line. The whole block opens Activity. */
export function SidebarStatus({ account, avatarUrl, onNavigate, status, usage }: SidebarStatusProps) {
  const name = account?.display_name || t("statusFooter.thisDevice");
  const usageText = usage
    ? formatMessage(usage.scope === "cloud" ? "statusFooter.usageCloud" : "statusFooter.usageDevice", {
        size: formatBytes(usage.bytes),
      })
    : null;

  return (
    <a
      aria-label={[name, usageText, status.label, t("statusFooter.open")].filter(Boolean).join(". ")}
      className="focus-ring group/status -mx-1 flex items-center gap-3 rounded-lg p-2 transition-colors duration-150 hover:bg-hover"
      href={appRoutes.activity}
      onClick={(event) => {
        if (!onNavigate) {
          return;
        }
        event.preventDefault();
        onNavigate(appRoutes.activity);
      }}
    >
      <Avatar account={account} src={avatarUrl ?? null} />
      <span className="grid min-w-0 flex-1 leading-tight">
        <span className="truncate text-sm font-medium text-ink">{name}</span>
        {usageText ? <span className="mt-0.5 truncate text-xs tabular-nums text-ink-muted">{usageText}</span> : null}
        <span className="mt-1.5 flex min-w-0 items-center gap-1.5 text-xs text-ink-muted group-hover/status:text-ink">
          <StatusDot pulse={status.tone === "active"} tone={statusToneMap[status.tone]} />
          <span className="truncate">{status.label}</span>
        </span>
      </span>
    </a>
  );
}

function Avatar({ account, src }: { account: TelegramAccount | null; src: string | null }) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const base = "grid size-9 shrink-0 place-items-center overflow-hidden rounded-full ring-1 ring-line";

  if (!account) {
    return (
      <span aria-hidden="true" className={cx(base, "bg-sunken text-ink-subtle")}>
        <HardDrive className="size-4" strokeWidth={1.75} />
      </span>
    );
  }

  if (src && src !== failedSrc) {
    return (
      <span aria-hidden="true" className={cx(base, "bg-sunken")}>
        <img alt="" className="size-full object-cover" draggable={false} onError={() => setFailedSrc(src)} src={src} />
      </span>
    );
  }

  return (
    <span aria-hidden="true" className={cx(base, "bg-accent-soft text-sm font-semibold text-accent-ink")}>
      {initials(account.display_name)}
    </span>
  );
}

function initials(name: string): string {
  const letters = name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => Array.from(part)[0] ?? "")
    .join("");
  return letters.toLocaleUpperCase() || "·";
}

export type SidebarStatusApi = {
  getAccount: () => Promise<AccountStatus>;
  getVault: () => Promise<VaultStatus>;
};

const defaultSidebarApi: SidebarStatusApi = { getAccount: () => getAccount(), getVault: () => getVault() };

export function ConnectedSidebarStatus({
  api = defaultSidebarApi,
  onNavigate,
  store = activityStore,
}: NavigateProps & { api?: SidebarStatusApi; store?: ActivityStore }) {
  const { activity, error } = useActivity(store);
  const account = usePolledResource(api.getAccount, 300_000);
  const vault = usePolledResource(api.getVault, 60_000);
  const signedIn = account.data?.step === "authorized" ? account.data.account : null;
  // A locked vault (e.g. this device was removed) reports no usage: say nothing rather than "0 B".
  const usage: SidebarUsage | null =
    vault.data && vault.data.state !== "locked"
      ? { bytes: vault.data.usage.bytes, scope: signedIn && vault.data.state !== "local_only" ? "cloud" : "device" }
      : null;

  return (
    <SidebarStatus
      account={signedIn}
      avatarUrl={signedIn ? absoluteApiPath(accountAvatarPath) : null}
      onNavigate={onNavigate}
      status={describeActivity(activity, error)}
      usage={usage}
    />
  );
}

/* ------------------------------------------------------------------------------------------------
 * Desktop notifications → in-app routes
 * --------------------------------------------------------------------------------------------- */

const desktopTargets: Record<string, string> = {
  activity: appRoutes.activity,
  devices: appRoutes.devices,
  drive: "/drive",
  "recovery-kit": appRoutes.recoveryKit,
  settings: appRoutes.settings,
};

/** Settings notifications that have a better home than the General section. */
const settingsAttentionTargets: Record<string, string> = {
  device_removed: appRoutes.account,
};

/**
 * Maps a desktop `NavigateRequest` (`{target, attentionId?}`) to a route. Unknown targets from a
 * newer desktop build fall back to Activity; anything that is not a request is ignored.
 */
export function desktopNavigationHref(request: unknown): string | null {
  if (!isRecord(request) || typeof request.target !== "string") {
    return null;
  }

  const href = Object.prototype.hasOwnProperty.call(desktopTargets, request.target) ? desktopTargets[request.target] : appRoutes.activity;
  const attentionId = request.attentionId;
  if (typeof attentionId !== "string" || attentionId.length === 0 || attentionId.length > 200) {
    return href;
  }
  if (href === appRoutes.activity) {
    return `${appRoutes.activity}?attention=${encodeURIComponent(attentionId)}`;
  }
  if (href === appRoutes.settings && Object.prototype.hasOwnProperty.call(settingsAttentionTargets, attentionId)) {
    return settingsAttentionTargets[attentionId];
  }

  return href;
}

type NavigateBridge = { onNavigate?: (listener: (request: unknown) => void) => unknown };

/**
 * Subscribes to `window.bento.onNavigate` when the desktop bridge offers it. In a plain browser,
 * or with an older desktop build, this is a no-op.
 */
export function subscribeDesktopNavigation(
  listener: (href: string) => void,
  bridge: unknown = typeof window !== "undefined" ? window.bento : undefined,
): () => void {
  const candidate = isRecord(bridge) ? (bridge as NavigateBridge).onNavigate : undefined;
  if (typeof candidate !== "function") {
    return () => undefined;
  }

  const unsubscribe = candidate.call(bridge, (request) => {
    const href = desktopNavigationHref(request);
    if (href) {
      listener(href);
    }
  });

  return typeof unsubscribe === "function" ? (unsubscribe as () => void) : () => undefined;
}

/** Routes the renderer when the user clicks a desktop notification. Call once from `App`. */
export function useDesktopNavigation(navigate: (href: string) => void): void {
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  useEffect(() => subscribeDesktopNavigation((href) => navigateRef.current(href)), []);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
