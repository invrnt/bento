import { useState } from "react";
import type { FormEvent } from "react";
import { KeyRound, MonitorSmartphone, PencilLine, Plus, Trash2 } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { listDevices, removeDevice, renameDevice } from "../../api/devices";
import type { Device, DeviceRemoval } from "../../api/devices";
import type { VaultStatus } from "../../api/vault";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Card } from "../../components/Card";
import { Dialog } from "../../components/Dialog";
import { IconButton } from "../../components/IconButton";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { t } from "../../i18n/dictionary";
import { usePolledResource } from "../../lib/usePolledResource";
import { formatDate, formatRelativeTime, tf } from "../onboarding/format";
import { AddDeviceDialog } from "../pairing/AddDeviceDialog";
import { RecoveryKit } from "../recovery/RecoveryKit";
import { platformIcon, platformLabel } from "./deviceLabels";

export type DevicesSectionProps = {
  accountName?: string | null;
  client?: ApiClient;
  onChanged?: () => void;
  onConnect?: () => void;
  pairingPollIntervalMs?: number;
  vault: VaultStatus | null;
};

/** Ajustes › Dispositivos: every device in the vault, rename, remove (new kit), add. */
export function DevicesSection({ accountName, client = apiClient, onChanged, onConnect, pairingPollIntervalMs, vault }: DevicesSectionProps) {
  const cloud = vault?.state === "ready" || vault?.state === "bootstrapping";
  const devices = usePolledResource(() => (cloud ? listDevices(client) : Promise.resolve({ items: [] as Device[] })), null, cloud);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Device | null>(null);
  const [removal, setRemoval] = useState<DeviceRemoval | null>(null);

  if (!cloud) {
    return (
      <EmptyState
        action={
          onConnect ? (
            <Button onClick={onConnect} variant="primary">
              {t("devices.connect")}
            </Button>
          ) : undefined
        }
        body={t("devices.localBody")}
        icon={<MonitorSmartphone />}
        title={t("devices.localTitle")}
      />
    );
  }

  const items = sortDevices((devices.data?.items ?? []).filter((device) => !device.removed_at));

  return (
    <section aria-labelledby="devices-title" className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-ink" id="devices-title">
            {t("devices.title")}
          </h2>
          <p className="mt-0.5 text-base text-ink-muted">{t("devices.body")}</p>
        </div>
        <Button leadingIcon={<Plus />} onClick={() => setAdding(true)} variant="primary">
          {t("devices.add")}
        </Button>
      </div>

      {devices.isLoading && !devices.data ? <LoadingState /> : null}
      {devices.error && !devices.data ? <ErrorState body={t("devices.loadFailed")} onRetry={() => void devices.refresh()} /> : null}

      {items.length ? (
        <Card as="section" padding="none">
          <ul className="divide-y divide-line">
            {items.map((device) => (
              <DeviceRow client={client} device={device} key={device.id} onRemove={() => setRemoving(device)} onRenamed={() => void devices.refresh()} />
            ))}
          </ul>
        </Card>
      ) : null}

      <AddDeviceDialog
        client={client}
        onAdded={() => {
          void devices.refresh();
          onChanged?.();
        }}
        onOpenChange={setAdding}
        open={adding}
        pollIntervalMs={pairingPollIntervalMs}
      />

      {removing ? (
        <RemoveDeviceDialog
          client={client}
          device={removing}
          onClose={() => setRemoving(null)}
          onRemoved={(result) => {
            setRemoving(null);
            setRemoval(result);
            void devices.refresh();
            onChanged?.();
          }}
        />
      ) : null}

      <Dialog
        description={t("devices.newKit.body")}
        icon={<KeyRound />}
        onOpenChange={(open) => !open && setRemoval(null)}
        open={removal !== null}
        size="lg"
        title={t("devices.newKit.title")}
      >
        {removal ? (
          <div className="grid gap-4">
            <Callout role="status" tone="success">
              {tf("devices.removed", { name: removal.device.name })}
            </Callout>
            {!removal.telegram_session_closed ? (
              <Callout role="status" tone="warning">
                {tf("devices.sessionOpen", { name: removal.device.name })}
              </Callout>
            ) : null}
            <RecoveryKit
              accountName={accountName}
              client={client}
              code={removal.recovery_code}
              createdAt={vault?.created_at}
              onConfirmed={() => {
                setRemoval(null);
                onChanged?.();
              }}
            />
          </div>
        ) : null}
      </Dialog>
    </section>
  );
}

function sortDevices(devices: Device[]): Device[] {
  return [...devices].sort((left, right) => {
    if (left.current !== right.current) return left.current ? -1 : 1;
    return (right.last_seen_at ?? "").localeCompare(left.last_seen_at ?? "");
  });
}

function DeviceRow({ client, device, onRemove, onRenamed }: { client: ApiClient; device: Device; onRemove: () => void; onRenamed: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(device.name);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const Icon = platformIcon(device.platform);
  const trimmed = name.trim();

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!trimmed || trimmed === device.name) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setFailed(false);
    try {
      await renameDevice(device.id, trimmed, client);
      setEditing(false);
      onRenamed();
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setName(device.name);
    setEditing(false);
    setFailed(false);
  }

  const seen = device.current
    ? t("devices.activeNow")
    : device.last_seen_at
      ? tf("devices.lastSeen", { time: formatRelativeTime(device.last_seen_at) })
      : tf("devices.addedOn", { date: formatDate(device.added_at) });

  return (
    <li className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:px-5">
      <div className="flex min-w-0 flex-1 items-center gap-3.5">
        <span aria-hidden="true" className="grid size-10 shrink-0 place-items-center rounded-md bg-sunken text-ink-muted">
          <Icon className="size-5" strokeWidth={1.75} />
        </span>
        {editing ? (
          <form
            className="flex min-w-0 flex-1 flex-wrap items-center gap-2"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                cancel();
              }
            }}
            onSubmit={(event) => void save(event)}
          >
            <input
              aria-invalid={failed || undefined}
              aria-label={t("devices.rename.label")}
              autoFocus
              className="field min-w-0 flex-1 px-3"
              maxLength={64}
              onChange={(event) => setName(event.target.value)}
              value={name}
            />
            <Button disabled={!trimmed} loading={saving} size="sm" type="submit" variant="primary">
              {t("devices.rename.save")}
            </Button>
            <Button onClick={cancel} size="sm" variant="ghost">
              {t("setup.cancel")}
            </Button>
            {failed ? (
              <p className="w-full text-xs font-medium text-danger-ink" role="alert">
                {t("devices.rename.failed")}
              </p>
            ) : null}
          </form>
        ) : (
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-base font-semibold text-ink">{device.name}</h3>
              {device.current ? <Badge tone="accent">{t("devices.thisDevice")}</Badge> : null}
            </div>
            <p className="mt-0.5 text-sm text-ink-muted">
              {platformLabel(device.platform)} · {seen}
            </p>
          </div>
        )}
      </div>
      {editing ? null : (
        <div className="flex shrink-0 items-center gap-1 self-end sm:self-center">
          <IconButton icon={<PencilLine />} label={tf("devices.rename.action", { name: device.name })} onClick={() => setEditing(true)} />
          {device.current ? null : (
            <IconButton icon={<Trash2 />} label={tf("devices.remove.action", { name: device.name })} onClick={onRemove} />
          )}
        </div>
      )}
    </li>
  );
}

function RemoveDeviceDialog({
  client,
  device,
  onClose,
  onRemoved,
}: {
  client: ApiClient;
  device: Device;
  onClose: () => void;
  onRemoved: (removal: DeviceRemoval) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function remove() {
    setBusy(true);
    setFailed(false);
    try {
      onRemoved(await removeDevice(device.id, client));
    } catch {
      setFailed(true);
      setBusy(false);
    }
  }

  return (
    <Dialog
      actions={
        <>
          <Button disabled={busy} onClick={onClose} variant="ghost">
            {t("setup.cancel")}
          </Button>
          <Button leadingIcon={<Trash2 />} loading={busy} onClick={() => void remove()} variant="danger">
            {t("devices.remove.confirm")}
          </Button>
        </>
      }
      icon={<Trash2 />}
      onOpenChange={(open) => !open && !busy && onClose()}
      open
      title={tf("devices.remove.title", { name: device.name })}
      tone="danger"
    >
      <ul className="grid list-disc gap-2 pl-5">
        <li>{t("devices.remove.consequence.sync")}</li>
        <li>{t("devices.remove.consequence.local")}</li>
        <li>{t("devices.remove.consequence.kit")}</li>
      </ul>
      {failed ? (
        <Callout className="mt-4" role="alert" tone="danger">
          {t("devices.remove.failed")}
        </Callout>
      ) : null}
    </Dialog>
  );
}
