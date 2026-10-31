import { useCallback, useEffect, useRef, useState } from "react";

import { emptyTrash, listTrash, purgeTrash, restoreTrash } from "../../api/trash";
import type { TrashItem } from "../../api/trash";

export type TrashApi = {
  empty: () => Promise<{ purged: number }>;
  list: (params: { cursor?: string | null; limit?: number }) => Promise<{ items: TrashItem[]; next_cursor: string | null }>;
  purge: (ids: string[]) => Promise<{ purged: number }>;
  restore: (ids: string[]) => Promise<{ restored: number }>;
};

export const defaultTrashApi: TrashApi = {
  empty: () => emptyTrash(),
  list: (params) => listTrash(params),
  purge: (ids) => purgeTrash(ids),
  restore: (ids) => restoreTrash(ids),
};

const pageSize = 100;

export type TrashState = {
  error: Error | null;
  items: TrashItem[];
  loadingMore: boolean;
  nextCursor: string | null;
  status: "loading" | "ready" | "error";
};

export function useTrash(api: TrashApi) {
  const [state, setState] = useState<TrashState>({ error: null, items: [], loadingMore: false, nextCursor: null, status: "loading" });
  const generation = useRef(0);

  const reload = useCallback(async () => {
    const current = ++generation.current;
    setState((previous) => ({ ...previous, error: null, status: previous.status === "ready" ? "ready" : "loading" }));
    try {
      const page = await api.list({ limit: pageSize });
      if (current === generation.current) {
        setState({ error: null, items: page.items, loadingMore: false, nextCursor: page.next_cursor, status: "ready" });
      }
    } catch (caught) {
      if (current === generation.current) {
        setState((previous) => ({ ...previous, error: asError(caught), status: "error" }));
      }
    }
  }, [api]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** Appends the next page; resolves `false` when it could not be loaded. */
  async function loadMore(): Promise<boolean> {
    if (!state.nextCursor || state.loadingMore) {
      return true;
    }

    const current = generation.current;
    setState((previous) => ({ ...previous, loadingMore: true }));
    try {
      const page = await api.list({ cursor: state.nextCursor, limit: pageSize });
      if (current === generation.current) {
        setState((previous) => ({
          ...previous,
          items: [...previous.items, ...page.items.filter((item) => !previous.items.some((known) => known.id === item.id))],
          loadingMore: false,
          nextCursor: page.next_cursor,
        }));
      }
      return true;
    } catch {
      setState((previous) => ({ ...previous, loadingMore: false }));
      return false;
    }
  }

  function removeLocally(ids: string[]) {
    const removed = new Set(ids);
    setState((previous) => ({ ...previous, items: previous.items.filter((item) => !removed.has(item.id)) }));
  }

  async function restore(ids: string[]) {
    await api.restore(ids);
    removeLocally(ids);
  }

  async function purge(ids: string[]) {
    await api.purge(ids);
    removeLocally(ids);
  }

  async function empty() {
    await api.empty();
    generation.current += 1;
    setState({ error: null, items: [], loadingMore: false, nextCursor: null, status: "ready" });
  }

  return { ...state, empty, loadMore, purge, reload, restore };
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}
