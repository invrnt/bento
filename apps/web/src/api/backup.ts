import { apiClient } from "./client";
import type { ApiClient } from "./client";

export type BackupSourceState = "idle" | "scanning" | "uploading" | "paused" | "error";

export type BackupSource = {
  bytes_pending: number;
  enabled: boolean;
  error: string | null;
  files_done: number;
  files_pending: number;
  files_total: number;
  id: string;
  label: string;
  last_scan_at: string | null;
  path: string;
  state: BackupSourceState;
};

export type BackupSuggestion = { kind: "pictures" | "documents" | "desktop" | "downloads"; label: string; path: string };

export type BackupPolicy = {
  bandwidth_limit_kbps: number;
  effective_paused: boolean;
  on_battery: boolean;
  pause_on_battery: boolean;
  paused: boolean;
};

export function listBackupSources(client: ApiClient = apiClient): Promise<{ items: BackupSource[] }> {
  return client.request<{ items: BackupSource[] }>("/backup/sources");
}

export function addBackupSource(path: string, label?: string, client: ApiClient = apiClient): Promise<BackupSource> {
  return client.request<BackupSource>("/backup/sources", { body: label ? { label, path } : { path }, method: "POST" });
}

export function updateBackupSource(
  id: string,
  patch: { enabled?: boolean; label?: string },
  client: ApiClient = apiClient,
): Promise<BackupSource> {
  return client.request<BackupSource>(`/backup/sources/${encodeURIComponent(id)}`, { body: patch, method: "PATCH" });
}

export function removeBackupSource(id: string, client: ApiClient = apiClient): Promise<{ removed: boolean }> {
  return client.request<{ removed: boolean }>(`/backup/sources/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function scanBackupSource(id: string, client: ApiClient = apiClient): Promise<BackupSource> {
  return client.request<BackupSource>(`/backup/sources/${encodeURIComponent(id)}/scan`, { method: "POST" });
}

export function listBackupSuggestions(client: ApiClient = apiClient): Promise<{ items: BackupSuggestion[] }> {
  return client.request<{ items: BackupSuggestion[] }>("/backup/suggestions");
}

export function getBackupPolicy(client: ApiClient = apiClient): Promise<BackupPolicy> {
  return client.request<BackupPolicy>("/backup/policy");
}

export function updateBackupPolicy(
  patch: Partial<Pick<BackupPolicy, "bandwidth_limit_kbps" | "pause_on_battery" | "paused">>,
  client: ApiClient = apiClient,
): Promise<BackupPolicy> {
  return client.request<BackupPolicy>("/backup/policy", { body: patch, method: "PATCH" });
}
