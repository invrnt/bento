import { apiClient } from "./client";
import type { ApiClient } from "./client";
import type { QrMatrix } from "./qr";

export type DevicePlatform = "linux" | "macos" | "windows" | "other";

export type Device = {
  added_at: string;
  current: boolean;
  /** When this device first learned about it (null when it was added here, e.g. as pairing host). */
  first_seen_at: string | null;
  id: string;
  /** The device whose sync data introduced this one here; null when it was added on this device. */
  introduced_by: string | null;
  last_seen_at: string | null;
  name: string;
  /** Active, first seen through sync and not acknowledged yet ("Nuevo"). */
  needs_review: boolean;
  platform: DevicePlatform;
  removed_at: string | null;
};

export type DeviceRemoval = {
  device: Device;
  recovery_code: string;
  recovery_qr?: QrMatrix;
  /** The removed device first, then every excluded one. */
  removed_device_ids: string[];
  telegram_session_closed: boolean;
};

export type RemovalPreview = {
  /** Active devices that would receive the new keys, this device first. */
  recipients: Device[];
};

export function listDevices(client: ApiClient = apiClient): Promise<{ items: Device[] }> {
  return client.request<{ items: Device[] }>("/devices");
}

export function renameDevice(id: string, name: string, client: ApiClient = apiClient): Promise<Device> {
  return client.request<Device>(`/devices/${encodeURIComponent(id)}`, { body: { name }, method: "PATCH" });
}

export function getRemovalPreview(id: string, client: ApiClient = apiClient): Promise<RemovalPreview> {
  return client.request<RemovalPreview>(`/devices/${encodeURIComponent(id)}/removal-preview`);
}

/** Removes `id`; `excludeDeviceIds` are removed too and get no share of the new keys. */
export function removeDevice(id: string, excludeDeviceIds: readonly string[] = [], client: ApiClient = apiClient): Promise<DeviceRemoval> {
  return client.request<DeviceRemoval>(`/devices/${encodeURIComponent(id)}`, {
    ...(excludeDeviceIds.length ? { body: { exclude_device_ids: [...excludeDeviceIds] } } : {}),
    method: "DELETE",
  });
}

/** "Es mío": the person reviewed a device first seen through sync. */
export function acknowledgeDevice(id: string, client: ApiClient = apiClient): Promise<Device> {
  return client.request<Device>(`/devices/${encodeURIComponent(id)}/acknowledge`, { method: "POST" });
}
