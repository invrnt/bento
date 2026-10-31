import { apiClient } from "./client";
import type { ApiClient } from "./client";

export type DevicePlatform = "linux" | "macos" | "windows" | "other";

export type Device = {
  added_at: string;
  current: boolean;
  id: string;
  last_seen_at: string | null;
  name: string;
  platform: DevicePlatform;
  removed_at: string | null;
};

export type DeviceRemoval = { device: Device; recovery_code: string; telegram_session_closed: boolean };

export function listDevices(client: ApiClient = apiClient): Promise<{ items: Device[] }> {
  return client.request<{ items: Device[] }>("/devices");
}

export function renameDevice(id: string, name: string, client: ApiClient = apiClient): Promise<Device> {
  return client.request<Device>(`/devices/${encodeURIComponent(id)}`, { body: { name }, method: "PATCH" });
}

export function removeDevice(id: string, client: ApiClient = apiClient): Promise<DeviceRemoval> {
  return client.request<DeviceRemoval>(`/devices/${encodeURIComponent(id)}`, { method: "DELETE" });
}
