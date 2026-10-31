import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity as ActivityIcon,
  ArrowRight,
  BellRing,
  CircleCheck,
  CirclePause,
  CloudAlert,
  CloudDownload,
  CloudOff,
  CloudUpload,
  Download,
  Hourglass,
  Inbox,
  KeyRound,
  Pause,
  Play,
  RefreshCw,
  RotateCw,
  Settings2,
  TriangleAlert,
  Upload,
} from "lucide-react";

import type { AttentionItem, TransferStats } from "../../api/activity";
import { getBackupPolicy, updateBackupPolicy } from "../../api/backup";
import type { BackupPolicy } from "../../api/backup";
import { retryJob } from "../../api/jobs";
import { requestSyncNow } from "../../api/sync";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { PageHeader } from "../../components/PageHeader";
import { ProgressBar } from "../../components/ProgressBar";
import { ErrorState, LoadingState } from "../../components/States";
import { showToast } from "../../components/Toast";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { formatBytes, formatDuration, formatMessage, formatNumber } from "../../lib/format";
import { navigateTo } from "../../lib/navigation";
import { usePolledResource } from "../../lib/usePolledResource";
import {
  actionableAttention,
  appRoutes,
  attentionBody,
  attentionJobId,
  attentionTitle,
  describeActivity,
  transferCount,
  transferPercent,
} from "./activityModel";
import type { ActivityStatusKind } from "./activityModel";
import { activityStore, useActivity } from "./activityStore";
import type { ActivityStore } from "./activityStore";

export type ActivityPageApi = {
  getBackupPolicy: () => Promise<BackupPolicy>;
  retryJob: (jobId: string) => Promise<unknown>;
  syncNow: () => Promise<unknown>;
  updateBackupPolicy: (patch: { paused: boolean }) => Promise<BackupPolicy>;
};

const defaultApi: ActivityPageApi = {
  getBackupPolicy: () => getBackupPolicy(),
  retryJob: (jobId) => retryJob(jobId),
  syncNow: () => requestSyncNow(),
  updateBackupPolicy: (patch) => updateBackupPolicy(patch),
};

export type ActivityPageProps = {
  api?: ActivityPageApi;
  /** Attention item to highlight and focus, from `/activity?attention=<id>` (desktop notifications). */
  focusAttentionId?: string | null;
  onNavigate?: (href: string) => void;
  store?: ActivityStore;
};

const heroStyles: Record<ActivityStatusKind, { icon: ReactNode; tile: string }> = {
  attention: { icon: <BellRing />, tile: "bg-warning-soft text-warning-ink" },
  downloading: { icon: <CloudDownload />, tile: "bg-accent-soft text-accent-ink" },
  loading: { icon: <RefreshCw />, tile: "bg-sunken text-ink-muted" },
  offline: { icon: <CloudOff />, tile: "bg-warning-soft text-warning-ink" },
  paused: { icon: <CirclePause />, tile: "bg-sunken text-ink-muted" },
  syncing: { icon: <RefreshCw />, tile: "bg-accent-soft text-accent-ink" },
  unavailable: { icon: <CloudAlert />, tile: "bg-sunken text-ink-muted" },
  up_to_date: { icon: <CircleCheck />, tile: "bg-success-soft text-success-ink" },
  uploading: { icon: <CloudUpload />, tile: "bg-accent-soft text-accent-ink" },
  waiting: { icon: <Hourglass />, tile: "bg-warning-soft text-warning-ink" },
};

/** The Activity page: transfers, queue, backup pause and attention items with one action each. */
export function ActivityPage({
  api = defaultApi,
  focusAttentionId = null,
  onNavigate = navigateTo,
  store = activityStore,
}: ActivityPageProps) {
  const { activity, error, isLoading, refresh } = useActivity(store);
  const policyResource = usePolledResource(api.getBackupPolicy, null);
  const [policyOverride, setPolicyOverride] = useState<BackupPolicy | null>(null);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [pendingItemId, setPendingItemId] = useState<string | null>(null);
  const policy = policyOverride ?? policyResource.data;
  const status = describeActivity(activity, error);
  const hero = heroStyles[status.kind];
  const attention = activity ? actionableAttention(activity) : [];
  const batteryPause = Boolean(policy && !policy.paused && policy.effective_paused && policy.on_battery);

  async function togglePaused() {
    if (!policy) {
      return;
    }

    setSavingPolicy(true);
    try {
      setPolicyOverride(await api.updateBackupPolicy({ paused: !policy.paused }));
      await refresh();
    } catch {
      showToast({ message: t("activity.policyError"), tone: "danger" });
    } finally {
      setSavingPolicy(false);
    }
  }

  async function runAttention(item: AttentionItem) {
    if (item.action === "open_settings") {
      onNavigate(appRoutes.settings);
      return;
    }

    if (item.action === "save_recovery_kit") {
      onNavigate(appRoutes.recoveryKit);
      return;
    }

    if (item.action !== "retry") {
      return;
    }

    setPendingItemId(item.id);
    try {
      if (item.kind === "sync_error") {
        await api.syncNow();
      } else {
        await api.retryJob(attentionJobId(item));
      }
      showToast({ message: t("activity.action.retried"), tone: "success" });
      await refresh();
    } catch {
      showToast({ message: t("activity.action.failed"), tone: "danger" });
    } finally {
      setPendingItemId(null);
    }
  }

  const pauseButton = policy ? (
    <Button
      leadingIcon={policy.paused ? <Play /> : <Pause />}
      loading={savingPolicy}
      onClick={() => void togglePaused()}
      variant={policy.paused ? "primary" : "secondary"}
    >
      {policy.paused ? t("activity.resume") : t("activity.pause")}
    </Button>
  ) : null;

  return (
    <div className="grid w-full max-w-4xl content-start gap-6">
      <PageHeader actions={pauseButton} description={t("activity.subtitle")} title={t("activity.title")} />

      {isLoading && !activity ? <LoadingState label={t("activity.loading")} /> : null}
      {!activity && error ? <ErrorState body={t("activity.error")} onRetry={() => void refresh()} /> : null}

      {activity ? (
        <>
          <Card as="section" aria-labelledby="activity-status-title" className="flex items-start gap-4" padding="lg">
            <span aria-hidden="true" className={cx("grid size-11 shrink-0 place-items-center rounded-lg [&_svg]:size-5", hero.tile)}>
              {hero.icon}
            </span>
            <div className="min-w-0 pt-0.5">
              <h2 className="text-lg font-semibold text-ink" id="activity-status-title">
                {status.label}
              </h2>
              <p className="mt-0.5 text-base text-ink-muted">{status.detail}</p>
              {batteryPause ? <p className="mt-1 text-sm text-ink-muted">{t("activity.pausedOnBattery")}</p> : null}
            </div>
          </Card>

          <div className="grid gap-4 sm:grid-cols-2">
            <TransferCard
              icon={<Upload />}
              idleKey="activity.uploads.idle"
              progressKey="activity.uploads.progressLabel"
              stats={activity.uploads}
              titleKey="activity.uploads.title"
            />
            <TransferCard
              icon={<Download />}
              idleKey="activity.downloads.idle"
              progressKey="activity.downloads.progressLabel"
              stats={activity.downloads}
              titleKey="activity.downloads.title"
            />
          </div>

          {attention.length > 0 ? (
            <section aria-labelledby="activity-attention-title" className="grid gap-3">
              <h2 className="text-base font-semibold text-ink" id="activity-attention-title">
                {t("activity.attention.title")}
              </h2>
              <Card as="div" className="overflow-hidden" padding="none">
                <ul aria-label={t("activity.attention.label")} className="divide-y divide-line">
                  {attention.map((item) => (
                    <AttentionRow
                      focused={item.id === focusAttentionId}
                      item={item}
                      key={item.id}
                      onRun={() => void runAttention(item)}
                      pending={pendingItemId === item.id}
                    />
                  ))}
                </ul>
              </Card>
            </section>
          ) : null}
        </>
      ) : null}

      <section aria-labelledby="activity-advanced-title" className="flex flex-col gap-3 border-t border-line pt-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 gap-3">
          <ActivityIcon aria-hidden="true" className="mt-0.5 size-[1.125rem] shrink-0 text-ink-subtle" strokeWidth={1.75} />
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-ink" id="activity-advanced-title">
              {t("activity.advanced.title")}
            </h2>
            <p className="text-sm text-ink-muted">{t("activity.advanced.body")}</p>
          </div>
        </div>
        <a
          className="focus-ring inline-flex shrink-0 items-center gap-1.5 self-start rounded-sm text-sm font-medium text-accent-ink hover:underline sm:self-center"
          href={appRoutes.jobs}
          onClick={(event) => {
            event.preventDefault();
            onNavigate(appRoutes.jobs);
          }}
        >
          {t("activity.advanced.link")}
          <ArrowRight aria-hidden="true" className="size-3.5" />
        </a>
      </section>
    </div>
  );
}

function TransferCard({
  icon,
  idleKey,
  progressKey,
  stats,
  titleKey,
}: {
  icon: ReactNode;
  idleKey: MessageKey;
  progressKey: MessageKey;
  stats: TransferStats;
  titleKey: MessageKey;
}) {
  const count = transferCount(stats);
  const percent = transferPercent(stats);
  const eta = formatDuration(stats.eta_seconds);

  return (
    <Card as="section" aria-label={t(titleKey)} className="grid content-start gap-3">
      <div className="flex items-center gap-2.5">
        <span aria-hidden="true" className="flex text-ink-subtle [&_svg]:size-4">
          {icon}
        </span>
        <h2 className="text-base font-semibold text-ink">{t(titleKey)}</h2>
        {count > 0 ? (
          <span className="ml-auto text-sm tabular-nums text-ink-muted">
            {formatMessage("activity.transfer.counts", { active: formatNumber(stats.active), queued: formatNumber(stats.queued) })}
          </span>
        ) : null}
      </div>
      {count > 0 ? (
        <>
          <ProgressBar label={t(progressKey)} value={percent ?? 0} />
          <div className="flex flex-wrap justify-between gap-x-4 gap-y-1 text-sm tabular-nums text-ink-muted">
            {stats.bytes_total > 0 ? (
              <span>
                {formatMessage("activity.transfer.progress", {
                  done: formatBytes(stats.bytes_done),
                  total: formatBytes(stats.bytes_total),
                })}
              </span>
            ) : null}
            {eta ? <span>{formatMessage("activity.transfer.eta", { eta })}</span> : null}
          </div>
        </>
      ) : (
        <p className="text-sm text-ink-muted">{t(idleKey)}</p>
      )}
    </Card>
  );
}

const attentionIcons: Record<string, ReactNode> = {
  inbox_failed: <Inbox />,
  recovery_kit: <KeyRound />,
  sync_error: <RefreshCw />,
  upload_failed: <CloudUpload />,
};

const actionContent: Record<Exclude<AttentionItem["action"], "none">, { icon: ReactNode; key: MessageKey }> = {
  open_settings: { icon: <Settings2 />, key: "activity.action.openSettings" },
  retry: { icon: <RotateCw />, key: "activity.action.retry" },
  save_recovery_kit: { icon: <KeyRound />, key: "activity.action.saveKit" },
};

function AttentionRow({
  focused,
  item,
  onRun,
  pending,
}: {
  focused: boolean;
  item: AttentionItem;
  onRun: () => void;
  pending: boolean;
}) {
  const action = item.action === "none" ? null : actionContent[item.action];
  const isKit = item.kind === "recovery_kit";
  const rowRef = useRef<HTMLLIElement | null>(null);

  // Arriving from a desktop notification: bring that item into view and move focus to it once.
  useEffect(() => {
    if (focused) {
      rowRef.current?.scrollIntoView?.({ block: "center" });
      rowRef.current?.focus();
    }
  }, [focused]);

  return (
    <li
      aria-current={focused || undefined}
      className={cx(
        "flex flex-col gap-3 p-4 outline-none transition-colors duration-200 sm:flex-row sm:items-center",
        focused && "bg-accent-soft/60 shadow-[inset_3px_0_0_var(--color-accent)]",
      )}
      data-attention-id={item.id}
      ref={rowRef}
      tabIndex={focused ? -1 : undefined}
    >
      <div className="flex min-w-0 flex-1 gap-3">
        <span
          aria-hidden="true"
          className={cx(
            "grid size-9 shrink-0 place-items-center rounded-md [&_svg]:size-[1.125rem]",
            isKit ? "bg-accent-soft text-accent-ink" : "bg-warning-soft text-warning-ink",
          )}
        >
          {attentionIcons[item.kind] ?? <TriangleAlert />}
        </span>
        <div className="min-w-0">
          <p className="font-medium text-ink">{attentionTitle(item)}</p>
          <p className="text-sm text-ink-muted">{attentionBody(item)}</p>
        </div>
      </div>
      {action ? (
        <Button className="self-start sm:self-center" leadingIcon={action.icon} loading={pending} onClick={onRun} size="sm">
          {t(action.key)}
        </Button>
      ) : null}
    </li>
  );
}
