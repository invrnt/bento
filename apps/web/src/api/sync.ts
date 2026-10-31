import { apiClient } from "./client";
import type { ApiClient } from "./client";
import type { ApiErrorBody } from "./qr";

export type SyncState = "disabled" | "idle" | "syncing" | "bootstrapping" | "offline" | "paused" | "waiting" | "error";

export type SyncStatus = {
  bootstrap: { done: number; total: number } | null;
  error: ApiErrorBody | null;
  last_pull_at: string | null;
  last_push_at: string | null;
  pending_ops: number;
  state: SyncState;
  waiting_until: string | null;
};

export function getSyncStatus(client: ApiClient = apiClient): Promise<SyncStatus> {
  return client.request<SyncStatus>("/sync/status");
}

export function requestSyncNow(client: ApiClient = apiClient): Promise<{ accepted: boolean }> {
  return client.request<{ accepted: boolean }>("/sync/now", { method: "POST" });
}
