import { useState } from "react";
import type { FormEvent } from "react";
import { BatteryLow, FolderPlus, Gauge, HardDriveUpload, Pause, RefreshCw, Trash2 } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import {
  addBackupSource,
  getBackupPolicy,
  listBackupSources,
  listBackupSuggestions,
  removeBackupSource,
  scanBackupSource,
  updateBackupPolicy,
  updateBackupSource,
} from "../../api/backup";
import type { BackupPolicy, BackupSource } from "../../api/backup";
import type { VaultStatus } from "../../api/vault";
import { Badge } from "../../components/Badge";
import type { BadgeTone } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { CheckboxBox } from "../../components/Checkbox";
import { Dialog } from "../../components/Dialog";
import { IconButton } from "../../components/IconButton";
import { Input } from "../../components/Input";
import { ProgressBar } from "../../components/ProgressBar";
import { Select } from "../../components/Select";
import { ErrorState, LoadingState } from "../../components/States";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { usePolledResource } from "../../lib/usePolledResource";
import { backupErrorKey, backupKindIcon, folderLabel } from "../onboarding/backupSources";
import { canPickDirectory, pickDirectory } from "../onboarding/desktopHost";
import { formatBytes, formatCount, tf } from "../onboarding/format";
import { SettingsCard, ToggleRow } from "./SettingsCard";

/** Friendly upload speed presets, in kilobits per second (0 = no limit). */
export const speedPresets: Array<{ kbps: number; label: MessageKey }> = [
  { kbps: 0, label: "backup.speed.unlimited" },
  { kbps: 20_000, label: "backup.speed.fast" },
  { kbps: 5_000, label: "backup.speed.balanced" },
  { kbps: 1_000, label: "backup.speed.gentle" },
];

const stateTones: Record<BackupSource["state"], BadgeTone> = {
  error: "danger",
  idle: "success",
  paused: "neutral",
  scanning: "warning",
  uploading: "accent",
};

export type BackupSectionProps = {
  client?: ApiClient;
  pollIntervalMs?: number;
  vault: VaultStatus | null;
};

/** Ajustes › Respaldo: folders, pause, pause on battery, speed limit. */
export function BackupSection({ client = apiClient, pollIntervalMs = 5000, vault }: BackupSectionProps) {
  const sources = usePolledResource(() => listBackupSources(client), pollIntervalMs);
  const suggestions = usePolledResource(() => listBackupSuggestions(client), null);
  const policy = usePolledResource(() => getBackupPolicy(client), null);
  const [policyOverride, setPolicyOverride] = useState<BackupPolicy | null>(null);
  const [policyFailed, setPolicyFailed] = useState(false);
  const [removing, setRemoving] = useState<BackupSource | null>(null);
  const [sourceError, setSourceError] = useState<MessageKey | null>(null);
  const currentPolicy = policyOverride ?? policy.data;
  const localOnly = !(vault?.state === "ready" || vault?.state === "bootstrapping");

  async function changePolicy(patch: Partial<Pick<BackupPolicy, "bandwidth_limit_kbps" | "pause_on_battery" | "paused">>) {
    setPolicyFailed(false);
    if (currentPolicy) setPolicyOverride({ ...currentPolicy, ...patch });
    try {
      setPolicyOverride(await updateBackupPolicy(patch, client));
    } catch {
      setPolicyOverride(null);
      setPolicyFailed(true);
    }
  }

  async function addFolder(path: string) {
    setSourceError(null);
    try {
      await addBackupSource(path, folderLabel(path), client);
      await sources.refresh();
    } catch (caught) {
      setSourceError(backupErrorKey(caught));
    }
  }

  async function runSourceAction(action: () => Promise<unknown>) {
    setSourceError(null);
    try {
      await action();
      await sources.refresh();
    } catch {
      setSourceError("backup.error.action");
    }
  }

  const items = sources.data?.items ?? [];
  const known = new Set(items.map((item) => item.path));
  const quickAdds = (suggestions.data?.items ?? []).filter((item) => !known.has(item.path));
  const limit = currentPolicy?.bandwidth_limit_kbps ?? 0;
  const speedOptions = speedPresets.map((preset) => ({ label: t(preset.label), value: String(preset.kbps) }));
  if (currentPolicy && !speedPresets.some((preset) => preset.kbps === limit)) {
    speedOptions.push({ label: tf("backup.speed.custom", { speed: formatSpeed(limit) }), value: String(limit) });
  }

  return (
    <div className="grid gap-4">
      {localOnly ? <Callout tone="info">{t("backup.localNote")}</Callout> : null}

      <SettingsCard
        action={<AddFolderButton onAdd={(path) => void addFolder(path)} />}
        description={t("backup.folders.body")}
        icon={<HardDriveUpload />}
        title={t("backup.folders.title")}
      >
        {sources.isLoading && !sources.data ? <LoadingState /> : null}
        {sources.error && !sources.data ? (
          <div className="p-4">
            <ErrorState body={t("backup.loadFailed")} onRetry={() => void sources.refresh()} />
          </div>
        ) : null}
        {sources.data && !items.length ? <p className="px-5 py-6 text-center text-base text-ink-muted">{t("backup.folders.empty")}</p> : null}
        {items.map((source) => (
          <SourceRow
            key={source.id}
            onRemove={() => setRemoving(source)}
            onScan={() => void runSourceAction(() => scanBackupSource(source.id, client))}
            onToggle={(enabled) => void runSourceAction(() => updateBackupSource(source.id, { enabled }, client))}
            source={source}
          />
        ))}
        {quickAdds.length ? (
          <div className="flex flex-wrap items-center gap-2 bg-subtle px-5 py-3">
            <span className="text-sm text-ink-muted">{t("backup.suggestions")}</span>
            {quickAdds.map((suggestion) => {
              const Icon = backupKindIcon(suggestion.kind);
              return (
                <Button key={suggestion.path} leadingIcon={<Icon />} onClick={() => void addFolder(suggestion.path)} size="sm" variant="secondary">
                  {suggestion.label}
                </Button>
              );
            })}
          </div>
        ) : null}
        {sourceError ? (
          <div className="px-5 py-3" role="alert">
            <p className="text-sm font-medium text-danger-ink">{t(sourceError)}</p>
          </div>
        ) : null}
      </SettingsCard>

      <SettingsCard description={t("backup.policy.body")} icon={<Gauge />} title={t("backup.policy.title")}>
        {currentPolicy ? (
          <>
            <ToggleRow
              checked={currentPolicy.paused}
              description={t("backup.pause.body")}
              label={t("backup.pause.label")}
              onChange={(paused) => void changePolicy({ paused })}
              trailing={currentPolicy.paused ? <Badge icon={<Pause />}>{t("backup.pause.badge")}</Badge> : null}
            />
            <ToggleRow
              checked={currentPolicy.pause_on_battery}
              description={t("backup.battery.body")}
              label={t("backup.battery.label")}
              onChange={(pause_on_battery) => void changePolicy({ pause_on_battery })}
              trailing={currentPolicy.on_battery ? <Badge icon={<BatteryLow />}>{t("backup.battery.onBattery")}</Badge> : null}
            />
            <div className="px-5 py-4">
              <Select
                label={t("backup.speed.label")}
                onChange={(event) => void changePolicy({ bandwidth_limit_kbps: Number(event.target.value) })}
                options={speedOptions}
                value={String(limit)}
                wrapperClassName="max-w-xs"
              />
              <p className="mt-1.5 text-xs text-ink-muted">{t("backup.speed.hint")}</p>
            </div>
          </>
        ) : policy.error ? (
          <div className="p-4">
            <ErrorState body={t("backup.policy.loadFailed")} onRetry={() => void policy.refresh()} />
          </div>
        ) : (
          <LoadingState />
        )}
        {currentPolicy?.effective_paused && !currentPolicy.paused ? (
          <div className="px-5 py-3">
            <Callout icon={<BatteryLow />} role="status" tone="warning">
              {t("backup.battery.active")}
            </Callout>
          </div>
        ) : null}
        {policyFailed ? (
          <div className="px-5 py-3">
            <Callout role="alert" tone="danger">
              {t("backup.policy.failed")}
            </Callout>
          </div>
        ) : null}
      </SettingsCard>

      <Dialog
        actions={
          <>
            <Button onClick={() => setRemoving(null)} variant="ghost">
              {t("setup.cancel")}
            </Button>
            <Button
              leadingIcon={<Trash2 />}
              onClick={() => {
                const source = removing;
                setRemoving(null);
                if (source) void runSourceAction(() => removeBackupSource(source.id, client));
              }}
              variant="danger"
            >
              {t("backup.remove.confirm")}
            </Button>
          </>
        }
        icon={<Trash2 />}
        onOpenChange={(open) => !open && setRemoving(null)}
        open={removing !== null}
        title={tf("backup.remove.title", { name: removing?.label ?? "" })}
        tone="danger"
      >
        <p>{t("backup.remove.body")}</p>
      </Dialog>
    </div>
  );
}

function formatSpeed(kbps: number): string {
  return kbps >= 1000 ? `${formatCount(Math.round(kbps / 100) / 10)} Mbit/s` : `${formatCount(kbps)} kbit/s`;
}

function AddFolderButton({ onAdd }: { onAdd: (path: string) => void }) {
  const [typing, setTyping] = useState(false);
  const [path, setPath] = useState("");

  async function start() {
    if (canPickDirectory()) {
      const picked = await pickDirectory(t("backup.pickTitle"));
      if (picked) onAdd(picked);
      return;
    }
    setTyping(true);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!path.trim()) return;
    onAdd(path.trim());
    setPath("");
    setTyping(false);
  }

  if (typing) {
    return (
      <form className="flex flex-wrap items-end gap-2" onSubmit={submit}>
        <Input
          autoFocus
          className="font-mono text-sm"
          hideLabel
          label={t("backup.typePath.label")}
          onChange={(event) => setPath(event.target.value)}
          onKeyDown={(event) => event.key === "Escape" && setTyping(false)}
          placeholder={t("backup.typePath.placeholder")}
          value={path}
          wrapperClassName="w-64"
        />
        <Button disabled={!path.trim()} type="submit" variant="primary">
          {t("backup.typePath.add")}
        </Button>
      </form>
    );
  }

  return (
    <Button leadingIcon={<FolderPlus />} onClick={() => void start()}>
      {t("backup.addFolder")}
    </Button>
  );
}

function SourceRow({
  onRemove,
  onScan,
  onToggle,
  source,
}: {
  onRemove: () => void;
  onScan: () => void;
  onToggle: (enabled: boolean) => void;
  source: BackupSource;
}) {
  const Icon = backupKindIcon(null);
  const active = source.state === "uploading" || source.state === "scanning";
  const progress = source.files_total > 0 ? (source.files_done / source.files_total) * 100 : 0;

  return (
    <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <CheckboxBox
          aria-label={tf("backup.source.toggle", { name: source.label })}
          boxClassName="mt-2.5"
          checked={source.enabled}
          onChange={(event) => onToggle(event.target.checked)}
        />
        <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-sunken text-ink-muted">
          <Icon className="size-[1.125rem]" strokeWidth={1.75} />
        </span>
        <div className="grid min-w-0 flex-1 gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-base font-medium text-ink">{source.label}</span>
            <Badge dot pulse={active} tone={source.enabled ? stateTones[source.state] : "neutral"}>
              {source.enabled ? sourceStateLabel(source) : t("backup.source.disabled")}
            </Badge>
          </div>
          <span className="truncate font-mono text-xs text-ink-muted">{source.path}</span>
          {active && source.files_total > 0 ? (
            <div className="mt-1 grid max-w-sm gap-1">
              <ProgressBar label={tf("backup.source.progressLabel", { name: source.label })} value={progress} />
              <span className="text-xs tabular-nums text-ink-muted">
                {tf("backup.source.progress", {
                  done: formatCount(source.files_done),
                  pending: formatBytes(source.bytes_pending),
                  total: formatCount(source.files_total),
                })}
              </span>
            </div>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1 self-end sm:self-center">
        <IconButton disabled={!source.enabled} icon={<RefreshCw />} label={tf("backup.source.scan", { name: source.label })} onClick={onScan} />
        <IconButton icon={<Trash2 />} label={tf("backup.source.remove", { name: source.label })} onClick={onRemove} />
      </div>
    </div>
  );
}

function sourceStateLabel(source: BackupSource): string {
  switch (source.state) {
    case "uploading":
      return tf("backup.state.uploading", { count: formatCount(source.files_pending) });
    case "scanning":
      return t("backup.state.scanning");
    case "paused":
      return t("backup.state.paused");
    case "error":
      return t("backup.state.error");
    default:
      return t("backup.state.idle");
  }
}
