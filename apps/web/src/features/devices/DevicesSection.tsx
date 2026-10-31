import { useId, useState } from "react";
import type { FormEvent } from "react";
import { Check, KeyRound, MonitorSmartphone, PencilLine, Plus, Trash2, Unplug } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { acknowledgeDevice, getRemovalPreview, listDevices, removeDevice, renameDevice } from "../../api/devices";
import type { Device, DeviceRemoval } from "../../api/devices";
import { isRemovedDevice } from "../../api/vault";
import type { VaultStatus } from "../../api/vault";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Card } from "../../components/Card";
import { Checkbox } from "../../components/Checkbox";
import { Dialog } from "../../components/Dialog";
import { IconButton } from "../../components/IconButton";
import { Spinner } from "../../components/Spinner";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { t } from "../../i18n/dictionary";
import { formatPlural } from "../../lib/format";
import { usePolledResource } from "../../lib/usePolledResource";
import { errorCode } from "../onboarding/apiErrors";
import { formatLongDate, formatRelativeTime, tf } from "../onboarding/format";
import { AddDeviceDialog } from "../pairing/AddDeviceDialog";
import { RecoveryKit } from "../recovery/RecoveryKit";
import { recoveryQrFrom } from "../recovery/recoveryCode";
import { platformIcon, platformLabel, sharedNames } from "./deviceLabels";

export type DevicesSectionProps = {
  accountName?: string | null;
  client?: ApiClient;
  /** After a review, a removal or a new device: the vault, account and Activity may have changed. */
  onChanged?: () => void;
  onConnect?: () => void;
  pairingPollIntervalMs?: number;
  vault: VaultStatus | null;
};

/** Ajustes › Dispositivos: every device in the vault, review new ones, rename, remove (new kit), add. */
export function DevicesSection({ accountName, client = apiClient, onChanged, onConnect, pairingPollIntervalMs, vault }: DevicesSectionProps) {
  const cloud = vault?.state === "ready" || vault?.state === "bootstrapping";
  const devices = usePolledResource(() => (cloud ? listDevices(client) : Promise.resolve({ items: [] as Device[] })), null, cloud);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Device | null>(null);
  const [removal, setRemoval] = useState<DeviceRemoval | null>(null);

  if (!cloud) {
    const removed = isRemovedDevice(vault);
    return (
      <EmptyState
        action={
          onConnect ? (
            <Button onClick={onConnect} variant="primary">
              {removed ? t("join.removed.rejoin") : t("devices.connect")}
            </Button>
          ) : undefined
        }
        body={removed ? t("account.removed.body") : t("devices.localBody")}
        icon={removed ? <Unplug /> : <MonitorSmartphone />}
        title={removed ? t("join.removed.title") : t("devices.localTitle")}
      />
    );
  }

  const items = sortDevices((devices.data?.items ?? []).filter((device) => !device.removed_at));
  const isShared = sharedNames(items);
  const alsoRemoved = removal ? (removal.removed_device_ids ?? []).filter((id) => id !== removal.device.id).length : 0;

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
              <DeviceRow
                client={client}
                device={device}
                key={device.id}
                onRemove={() => setRemoving(device)}
                onRenamed={() => void devices.refresh()}
                onReviewed={() => {
                  void devices.refresh();
                  onChanged?.();
                }}
                showAdded={isShared(device.name)}
              />
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
          knownDevices={items}
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
              {alsoRemoved > 0
                ? formatPlural(alsoRemoved, { one: "devices.removedMore.one", other: "devices.removedMore.other" }, { name: removal.device.name })
                : tf("devices.removed", { name: removal.device.name })}
            </Callout>
            {!removal.telegram_session_closed ? (
              <Callout role="status" tone="warning">
                {tf("devices.sessionOpen", { name: removal.device.name })}
              </Callout>
            ) : null}
            {alsoRemoved > 0 ? (
              <Callout role="status" tone="warning">
                {t("devices.excludedSessionsOpen")}
              </Callout>
            ) : null}
            <RecoveryKit
              accountName={accountName}
              client={client}
              code={removal.recovery_code}
              createdAt={vault?.created_at}
              qr={recoveryQrFrom(removal)}
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

/** This device, then the ones waiting for a review, then the most recently seen. */
function sortDevices(devices: Device[]): Device[] {
  return [...devices].sort((left, right) => {
    if (left.current !== right.current) return left.current ? -1 : 1;
    if (Boolean(left.needs_review) !== Boolean(right.needs_review)) return left.needs_review ? -1 : 1;
    return (right.last_seen_at ?? "").localeCompare(left.last_seen_at ?? "");
  });
}

/** "Linux · Visto hace 5 minutos", plus "· Añadido el …" when another device has the same name. */
function deviceDetails(device: Device, showAdded: boolean): string {
  const added = tf("devices.addedOn", { date: formatLongDate(device.added_at) });
  const seen = device.current
    ? t("devices.activeNow")
    : device.last_seen_at
      ? tf("devices.lastSeen", { time: formatRelativeTime(device.last_seen_at) })
      : added;
  return [platformLabel(device.platform), seen, showAdded && seen !== added ? added : null].filter(Boolean).join(" · ");
}

function needsReview(device: Device): boolean {
  return Boolean(device.needs_review) && !device.current;
}

function DeviceRow({
  client,
  device,
  onRemove,
  onRenamed,
  onReviewed,
  showAdded,
}: {
  client: ApiClient;
  device: Device;
  onRemove: () => void;
  onRenamed: () => void;
  onReviewed: () => void;
  showAdded: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(device.name);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const [acknowledging, setAcknowledging] = useState(false);
  const [acknowledgeFailed, setAcknowledgeFailed] = useState(false);
  const Icon = platformIcon(device.platform);
  const trimmed = name.trim();
  const isNew = needsReview(device);

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

  async function acknowledge() {
    setAcknowledging(true);
    setAcknowledgeFailed(false);
    try {
      await acknowledgeDevice(device.id, client);
      onReviewed();
    } catch {
      setAcknowledgeFailed(true);
    } finally {
      setAcknowledging(false);
    }
  }

  return (
    <li className="grid gap-3 px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
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
                {isNew ? (
                  <Badge dot tone="warning">
                    {t("devices.new")}
                  </Badge>
                ) : null}
              </div>
              <p className="mt-0.5 text-sm text-ink-muted">{deviceDetails(device, showAdded)}</p>
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
      </div>
      {isNew && !editing ? (
        <div className="grid gap-2 sm:ml-[3.375rem]">
          <Callout
            action={
              <>
                <Button leadingIcon={<Check />} loading={acknowledging} onClick={() => void acknowledge()} size="sm">
                  {t("devices.review.mine")}
                </Button>
                <Button disabled={acknowledging} onClick={onRemove} size="sm" variant="danger-ghost">
                  {t("devices.review.unknown")}
                </Button>
              </>
            }
            tone="warning"
          >
            {tf("devices.review.body", { date: formatLongDate(device.added_at) })}
          </Callout>
          {acknowledgeFailed ? (
            <p className="text-xs font-medium text-danger-ink" role="alert">
              {t("devices.review.failed")}
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/** This device (always keeps access) first, then the ones waiting for a review, then the rest. */
function orderRecipients(recipients: Device[]): Device[] {
  const rank = (device: Device) => (device.current ? 0 : needsReview(device) ? 1 : 2);
  return [...recipients].sort((left, right) => rank(left) - rank(right));
}

type RemovalProblem = "failed" | "exclusionInvalid";

function RemoveDeviceDialog({
  client,
  device,
  knownDevices,
  onClose,
  onRemoved,
}: {
  client: ApiClient;
  device: Device;
  knownDevices: Device[];
  onClose: () => void;
  onRemoved: (removal: DeviceRemoval) => void;
}) {
  const preview = usePolledResource(() => getRemovalPreview(device.id, client), null, device.id);
  const [unticked, setUnticked] = useState<ReadonlySet<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<RemovalProblem | null>(null);
  const keepTitleId = useId();
  const keepBodyId = useId();
  const recipients = orderRecipients((preview.data?.recipients ?? []).filter((recipient) => recipient.id !== device.id && !recipient.removed_at));
  const isShared = sharedNames([device, ...knownDevices, ...recipients]);
  // Only devices still offered by the preview can be excluded; this device always keeps access.
  const excluded = recipients.filter((recipient) => !recipient.current && unticked.has(recipient.id)).map((recipient) => recipient.id);
  const loadingPreview = preview.isLoading && !preview.data;

  function toggle(id: string, keep: boolean) {
    setProblem(null);
    setUnticked((current) => {
      const next = new Set(current);
      if (keep) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function remove() {
    setBusy(true);
    setProblem(null);
    try {
      onRemoved(await removeDevice(device.id, excluded, client));
    } catch (caught) {
      if (errorCode(caught) === "device_exclusion_invalid") {
        setProblem("exclusionInvalid");
        void preview.refresh();
      } else {
        setProblem("failed");
      }
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
          <Button disabled={loadingPreview} leadingIcon={<Trash2 />} loading={busy} onClick={() => void remove()} variant="danger">
            {excluded.length ? tf("devices.remove.confirmMany", { count: excluded.length + 1 }) : t("devices.remove.confirm")}
          </Button>
        </>
      }
      description={deviceDetails(device, true)}
      icon={<Trash2 />}
      onOpenChange={(open) => !open && !busy && onClose()}
      open
      size="lg"
      title={tf("devices.remove.title", { name: device.name })}
      tone="danger"
    >
      <div className="grid gap-5">
        <ul className="grid list-disc gap-2 pl-5">
          <li>{t("devices.remove.consequence.sync")}</li>
          <li>{t("devices.remove.consequence.local")}</li>
          <li>{t("devices.remove.consequence.kit")}</li>
        </ul>

        <fieldset aria-describedby={keepBodyId} aria-labelledby={keepTitleId} className="grid gap-2">
          <div>
            <h3 className="text-base font-semibold text-ink" id={keepTitleId}>
              {t("devices.remove.keepTitle")}
            </h3>
            <p className="mt-0.5 text-sm text-ink-muted" id={keepBodyId}>
              {t("devices.remove.keepBody")}
            </p>
          </div>
          {loadingPreview ? (
            <p className="flex items-center gap-2 text-sm text-ink-muted" role="status">
              <Spinner className="size-3.5 text-accent-ink" />
              {t("devices.remove.keepLoading")}
            </p>
          ) : null}
          {preview.error && !preview.data ? (
            <Callout
              action={
                <Button onClick={() => void preview.refresh()} size="sm">
                  {t("common.retry")}
                </Button>
              }
              role="alert"
              tone="warning"
            >
              {t("devices.remove.keepFailed")}
            </Callout>
          ) : null}
          {recipients.length ? (
            <ul className="grid gap-1">
              {recipients.map((recipient) => (
                <li key={recipient.id}>
                  <Checkbox
                    checked={recipient.current || !unticked.has(recipient.id)}
                    description={
                      recipient.current ? (
                        t("devices.remove.thisDeviceKeeps")
                      ) : (
                        <span className="flex flex-wrap items-center gap-1.5">
                          {needsReview(recipient) ? (
                            <Badge dot tone="warning">
                              {t("devices.new")}
                            </Badge>
                          ) : null}
                          <span>{deviceDetails(recipient, isShared(recipient.name))}</span>
                        </span>
                      )
                    }
                    disabled={recipient.current || busy}
                    label={recipient.name}
                    onChange={(event) => toggle(recipient.id, event.target.checked)}
                  />
                </li>
              ))}
            </ul>
          ) : null}
        </fieldset>

        {excluded.length ? (
          <Callout
            role="status"
            title={formatPlural(excluded.length, { one: "devices.remove.excluded.one", other: "devices.remove.excluded.other" })}
            tone="warning"
          >
            {t("devices.remove.excluded.body")}
          </Callout>
        ) : null}

        {problem ? (
          <Callout role="alert" tone="danger">
            {t(problem === "exclusionInvalid" ? "devices.remove.exclusionInvalid" : "devices.remove.failed")}
          </Callout>
        ) : null}
      </div>
    </Dialog>
  );
}
