import { apiClient } from "./client";
import type { ApiClient } from "./client";

export type TelegramChat = { id: number; kind: "saved" | "user" | "group" | "channel"; title: string };

export type TelegramMediaKind = "photo" | "video" | "audio" | "document";

export type TelegramMediaItem = {
  date: string;
  filename: string;
  kind: TelegramMediaKind;
  message_id: number;
  size_bytes: number | null;
};

export function listTelegramChats(
  params: { limit?: number; query?: string } = {},
  client: ApiClient = apiClient,
): Promise<{ items: TelegramChat[] }> {
  return client.request<{ items: TelegramChat[] }>("/telegram/chats", { query: params });
}

export function shareAssetToTelegram(
  assetId: string,
  chatId: number,
  caption?: string,
  client: ApiClient = apiClient,
): Promise<{ sent: boolean }> {
  return client.request<{ sent: boolean }>(`/assets/${encodeURIComponent(assetId)}/share/telegram`, {
    body: caption ? { caption, chat_id: chatId } : { chat_id: chatId },
    method: "POST",
  });
}

export function listTelegramMedia(
  params: { chat_id: number; cursor?: string | null; kind?: TelegramMediaKind | "all" },
  client: ApiClient = apiClient,
): Promise<{ items: TelegramMediaItem[]; next_cursor: string | null }> {
  return client.request<{ items: TelegramMediaItem[]; next_cursor: string | null }>("/telegram/import/media", {
    query: params,
  });
}

export function importFromTelegram(
  request: { all?: boolean; chat_id: number; message_ids?: number[] },
  client: ApiClient = apiClient,
): Promise<{ job_id: string; queued: number }> {
  return client.request<{ job_id: string; queued: number }>("/telegram/import", { body: request, method: "POST" });
}

export function assetContentPath(assetId: string): string {
  return `/api/assets/${encodeURIComponent(assetId)}/content`;
}
