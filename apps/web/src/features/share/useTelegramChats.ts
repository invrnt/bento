import { useEffect, useState } from "react";

import { listTelegramChats } from "../../api/telegram";
import type { TelegramChat } from "../../api/telegram";

export type ListChats = (params: { limit?: number; query?: string }) => Promise<{ items: TelegramChat[] }>;

export const defaultListChats: ListChats = (params) => listTelegramChats(params);

export type TelegramChatsState = {
  chats: TelegramChat[];
  error: unknown;
  retry: () => void;
  status: "loading" | "ready" | "error";
};

const debounceMs = 250;

/** Recent chats matching `query` (debounced), with Saved Messages always first. */
export function useTelegramChats(query: string, listChats: ListChats = defaultListChats): TelegramChatsState {
  const [state, setState] = useState<Omit<TelegramChatsState, "retry">>({ chats: [], error: null, status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const trimmed = query.trim();

  useEffect(() => {
    let active = true;
    setState((previous) => ({ ...previous, error: null, status: "loading" }));

    const timer = setTimeout(
      () => {
        listChats({ limit: 30, query: trimmed || undefined })
          .then((response) => {
            if (active) {
              setState({ chats: savedFirst(response.items), error: null, status: "ready" });
            }
          })
          .catch((error: unknown) => {
            if (active) {
              setState({ chats: [], error, status: "error" });
            }
          });
      },
      trimmed ? debounceMs : 0,
    );

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [attempt, listChats, trimmed]);

  return { ...state, retry: () => setAttempt((value) => value + 1) };
}

export function savedFirst(chats: TelegramChat[]): TelegramChat[] {
  return [...chats.filter((chat) => chat.kind === "saved"), ...chats.filter((chat) => chat.kind !== "saved")];
}
