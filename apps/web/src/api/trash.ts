import { apiClient } from "./client";
import type { ApiClient } from "./client";

export type TrashItem = {
  deleted_at: string;
  id: string;
  name: string;
  purge_at: string;
  size_bytes: number;
  thumbnail_url: string | null;
  type: "asset" | "folder";
};

export function listTrash(
  params: { cursor?: string | null; limit?: number } = {},
  client: ApiClient = apiClient,
): Promise<{ items: TrashItem[]; next_cursor: string | null }> {
  return client.request<{ items: TrashItem[]; next_cursor: string | null }>("/trash", { query: params });
}

export function restoreTrash(ids: string[], client: ApiClient = apiClient): Promise<{ restored: number }> {
  return client.request<{ restored: number }>("/trash/restore", { body: { ids }, method: "POST" });
}

export function purgeTrash(ids: string[], client: ApiClient = apiClient): Promise<{ purged: number }> {
  return client.request<{ purged: number }>("/trash/purge", { body: { ids }, method: "POST" });
}

export function emptyTrash(client: ApiClient = apiClient): Promise<{ purged: number }> {
  return client.request<{ purged: number }>("/trash/empty", { method: "POST" });
}
