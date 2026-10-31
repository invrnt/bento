import { apiClient } from "./client";
import type { ApiClient } from "./client";

export type ActivitySummary = "up_to_date" | "uploading" | "downloading" | "syncing" | "paused" | "offline" | "attention";

export type TransferStats = {
  active: number;
  bytes_done: number;
  bytes_total: number;
  eta_seconds: number | null;
  queued: number;
};

export type AttentionKind =
  | "upload_failed"
  | "sync_error"
  | "flood_wait"
  | "recovery_kit"
  | "inbox_failed"
  | "new_device"
  | "device_removed";

export type AttentionAction = "retry" | "open_settings" | "save_recovery_kit" | "open_devices" | "none";

export type AttentionItem = {
  action: AttentionAction;
  id: string;
  kind: AttentionKind;
  params: Record<string, unknown>;
  title_key: string;
};

export type Activity = {
  attention: AttentionItem[];
  downloads: TransferStats;
  summary: ActivitySummary;
  uploads: TransferStats;
};

export function getActivity(client: ApiClient = apiClient): Promise<Activity> {
  return client.request<Activity>("/activity");
}
