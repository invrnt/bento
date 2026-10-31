import { useState } from "react";
import { Cloud, CloudOff, HardDriveDownload } from "lucide-react";

import { StatusDot } from "../../components/Badge";
import type { BadgeTone } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Card } from "../../components/Card";
import { Dialog } from "../../components/Dialog";
import { PageHeader } from "../../components/PageHeader";
import { ErrorState, LoadingState } from "../../components/States";
import type { PublicSettings, ProviderState, StorageReclaimResult, WorkerStatus } from "../../api/settings";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { EditableSettingsPage } from "./EditableSettingsPage";
import type { SettingsController } from "./useSettingsController";

export type SettingsPageProps = {
  controller?: SettingsController;
  error?: Error | null;
  isLoading?: boolean;
  isReclaiming?: boolean;
  onReclaim?: () => Promise<void> | void;
  onRetry?: () => void;
  reclaimError?: Error | null;
  reclaimResult?: StorageReclaimResult | null;
  settings?: PublicSettings | null;
};

type Tone = "danger" | "idle" | "success" | "warning";

type StatusItem = {
  detail?: string;
  label: string;
  tone: Tone;
  value: string;
};

const toneDots: Record<Tone, BadgeTone> = {
  danger: "danger",
  idle: "neutral",
  success: "success",
  warning: "warning",
};

const providerLabels: Record<string, MessageKey> = {
  disabled: "settings.provider.disabled",
  error: "settings.provider.error",
  pending: "settings.provider.pending",
  ready: "settings.provider.ready",
};

const workerLabels: Record<string, MessageKey> = {
  degraded: "settings.worker.degraded",
  running: "settings.worker.running",
  stopped: "settings.worker.stopped",
};

export function SettingsPage({ controller, ...props }: SettingsPageProps) {
  if (controller) {
    return <EditableSettingsPage controller={controller} />;
  }

  return <SettingsStatusPage {...props} />;
}

function SettingsStatusPage({
  error,
  isLoading = false,
  isReclaiming = false,
  onReclaim,
  onRetry,
  reclaimError,
  reclaimResult,
  settings,
}: Omit<SettingsPageProps, "controller">) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const items = settings ? settingsItems(settings) : [];
  const maintenance = settings?.storage_maintenance;
  const connected = maintenance?.connection_state === "connected";

  async function confirmReclaim() {
    setConfirmOpen(false);
    await onReclaim?.();
  }

  return (
    <div className="mx-auto grid w-full max-w-6xl gap-6">
      <PageHeader description={t("settings.header.body")} title={t("settings.header.title")} />

      {error ? <ErrorState body={t("settings.settingsError.body")} onRetry={onRetry} /> : null}
      {isLoading ? <LoadingState /> : null}

      {!isLoading && settings ? (
        <>
          {maintenance ? (
            <Card aria-labelledby="cloud-storage-title" as="section" className="overflow-hidden" padding="none">
              <div className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 gap-4">
                  <span
                    aria-hidden="true"
                    className={cx("grid size-10 shrink-0 place-items-center rounded-md", connected ? "bg-success-soft text-success-ink" : "bg-warning-soft text-warning-ink")}
                  >
                    {connected ? <Cloud className="size-5" strokeWidth={1.75} /> : <CloudOff className="size-5" strokeWidth={1.75} />}
                  </span>
                  <div className="min-w-0">
                    <h2 className="text-lg font-semibold text-ink" id="cloud-storage-title">{t("settings.space.title")}</h2>
                    <p className="mt-0.5 text-base text-ink-muted">{maintenanceDescription(settings)}</p>
                    <p className="mt-2 text-sm font-medium tabular-nums text-ink-muted">
                      {t("settings.space.reclaimable")}: {formatBytes(maintenance.reclaimable_bytes)} · {maintenance.reclaimable_files} {t("settings.space.files")}
                    </p>
                  </div>
                </div>
                <Button
                  disabled={!maintenance.can_reclaim}
                  leadingIcon={<HardDriveDownload />}
                  loading={isReclaiming}
                  onClick={() => setConfirmOpen(true)}
                  variant="primary"
                >
                  {isReclaiming ? t("settings.space.reclaiming") : t("settings.space.action")}
                </Button>
              </div>
              <p className="border-t border-line bg-subtle px-5 py-3 text-xs text-ink-muted">{t("settings.space.localMetadata")}</p>
            </Card>
          ) : null}

          {reclaimResult ? (
            <Callout role="status" tone="success">
              {t("settings.space.success")} {formatBytes(reclaimResult.freed_bytes)}.
            </Callout>
          ) : null}
          {reclaimError ? <Callout role="alert" tone="danger">{t("settings.space.error")}</Callout> : null}

          <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {items.map((item) => (
              <Card className="grid content-start gap-1.5" key={item.label} padding="sm">
                <dt className="text-sm text-ink-muted">{item.label}</dt>
                <dd className="flex items-center gap-2 font-semibold text-ink">
                  <StatusDot className="size-2" tone={toneDots[item.tone]} />
                  <span className="min-w-0 truncate">{item.value}</span>
                </dd>
                {item.detail ? <dd className="text-xs text-ink-muted">{item.detail}</dd> : null}
              </Card>
            ))}
          </dl>
        </>
      ) : null}

      <Dialog
        actions={
          <>
            <Button onClick={() => setConfirmOpen(false)} variant="ghost">{t("common.close")}</Button>
            <Button leadingIcon={<HardDriveDownload />} onClick={() => void confirmReclaim()} variant="primary">{t("settings.space.confirm")}</Button>
          </>
        }
        icon={<HardDriveDownload />}
        onOpenChange={setConfirmOpen}
        open={confirmOpen}
        title={t("settings.space.dialogTitle")}
      >
        <p>{t("settings.space.dialogBody")}</p>
      </Dialog>
    </div>
  );
}

function maintenanceDescription(settings: PublicSettings): string {
  const maintenance = settings.storage_maintenance;
  if (!maintenance) return "";
  if (maintenance.connection_state === "connected" && maintenance.fully_remote) return t("settings.space.connected");
  if (maintenance.local_blob_count > 0) return t("settings.space.localBlobs");
  if (maintenance.connection_state === "unavailable") return t("settings.space.unavailable");
  return t("settings.space.notConfigured");
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length);
  const value = bytes / 1024 ** exponent;
  return `${new Intl.NumberFormat("es", { maximumFractionDigits: value >= 10 ? 1 : 2 }).format(value)} ${units[exponent - 1]}`;
}

export function settingsItems(settings: PublicSettings): StatusItem[] {
  const telegramConfigured = settings.telegram_configured ?? settings.telegram_enabled ?? false;
  const ocrState = providerState(settings.ocr_state, settings.ocr_enabled);
  const embeddingsState = providerState(settings.embeddings_state, settings.embeddings_enabled);
  const workerStatus = settings.worker_status ?? "stopped";

  return [
    {
      label: t("settings.storage"),
      tone: settings.storage_backend === "telegram" ? "warning" : "success",
      value: storageLabel(settings.storage_backend),
    },
    {
      label: t("settings.telegram"),
      tone: telegramConfigured ? "success" : "idle",
      value: telegramConfigured ? t("settings.telegram.configured") : t("settings.telegram.notConfigured"),
    },
    {
      label: t("settings.ocr"),
      tone: providerTone(ocrState),
      value: providerLabel(ocrState),
    },
    {
      label: t("settings.embeddings"),
      tone: providerTone(embeddingsState),
      value: providerLabel(embeddingsState),
    },
    {
      label: t("settings.model"),
      tone: settings.model_available ? "success" : "warning",
      value: settings.model_available ? t("settings.model.available") : t("settings.model.pending"),
    },
    {
      detail:
        typeof settings.worker_concurrency === "number"
          ? `${t("settings.worker.concurrency")}: ${settings.worker_concurrency}`
          : undefined,
      label: t("settings.worker"),
      tone: workerTone(workerStatus),
      value: workerLabel(workerStatus),
    },
    {
      label: t("settings.dataPaths"),
      tone: "idle",
      value: dataPathSummary(settings.data_paths),
    },
  ];
}

function storageLabel(storageBackend: string): string {
  if (storageBackend === "local") {
    return t("settings.storage.local");
  }

  if (storageBackend === "telegram") {
    return t("settings.storage.telegram");
  }

  return storageBackend || t("common.unknown");
}

function providerState(state?: ProviderState, enabled?: boolean): ProviderState {
  if (state) {
    return state;
  }

  return enabled ? "ready" : "disabled";
}

function providerLabel(state: ProviderState): string {
  return t(providerLabels[state] ?? "common.unknown");
}

function providerTone(state: ProviderState): Tone {
  if (state === "ready") {
    return "success";
  }

  if (state === "error") {
    return "danger";
  }

  if (state === "pending") {
    return "warning";
  }

  return "idle";
}

function workerLabel(status: WorkerStatus): string {
  return t(workerLabels[status] ?? "common.unknown");
}

function workerTone(status: WorkerStatus): Tone {
  if (status === "running") {
    return "success";
  }

  if (status === "degraded") {
    return "warning";
  }

  return "idle";
}

function dataPathSummary(paths?: Record<string, string>): string {
  const labels = Object.keys(paths ?? {}).sort();

  return labels.length > 0 ? labels.join(", ") : t("settings.emptyPaths");
}
