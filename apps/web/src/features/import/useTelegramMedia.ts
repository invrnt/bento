import { useEffect, useRef, useState } from "react";

import { listTelegramMedia } from "../../api/telegram";
import type { TelegramMediaItem, TelegramMediaKind } from "../../api/telegram";

export type MediaFilter = "all" | Exclude<TelegramMediaKind, "audio">;

export type ListMedia = (params: {
  chat_id: number;
  cursor?: string | null;
  kind?: TelegramMediaKind | "all";
}) => Promise<{ items: TelegramMediaItem[]; next_cursor: string | null }>;

export const defaultListMedia: ListMedia = (params) => listTelegramMedia(params);

type MediaState = {
  error: unknown;
  items: TelegramMediaItem[];
  loadingMore: boolean;
  nextCursor: string | null;
  status: "idle" | "loading" | "ready" | "error";
};

const idle: MediaState = { error: null, items: [], loadingMore: false, nextCursor: null, status: "idle" };

/** Pages through a chat's media for one kind filter. `chatId = null` stays idle. */
export function useTelegramMedia(chatId: number | null, kind: MediaFilter, listMedia: ListMedia = defaultListMedia) {
  const [state, setState] = useState<MediaState>(idle);
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);

  useEffect(() => {
    const current = ++generation.current;
    if (chatId === null) {
      setState(idle);
      return;
    }

    setState({ ...idle, status: "loading" });
    listMedia({ chat_id: chatId, kind })
      .then((page) => {
        if (current === generation.current) {
          setState({ error: null, items: page.items, loadingMore: false, nextCursor: page.next_cursor, status: "ready" });
        }
      })
      .catch((error: unknown) => {
        if (current === generation.current) {
          setState({ ...idle, error, status: "error" });
        }
      });
  }, [attempt, chatId, kind, listMedia]);

  async function loadMore() {
    if (chatId === null || !state.nextCursor || state.loadingMore) {
      return;
    }

    const current = generation.current;
    setState((previous) => ({ ...previous, loadingMore: true }));
    try {
      const page = await listMedia({ chat_id: chatId, cursor: state.nextCursor, kind });
      if (current === generation.current) {
        setState((previous) => {
          const known = new Set(previous.items.map((item) => item.message_id));
          return {
            ...previous,
            items: [...previous.items, ...page.items.filter((item) => !known.has(item.message_id))],
            loadingMore: false,
            nextCursor: page.next_cursor,
          };
        });
      }
    } catch (error) {
      if (current === generation.current) {
        setState((previous) => ({ ...previous, error, loadingMore: false }));
      }
    }
  }

  return { ...state, loadMore, retry: () => setAttempt((value) => value + 1) };
}
