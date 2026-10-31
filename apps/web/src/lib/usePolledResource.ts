import { useCallback, useEffect, useRef, useState } from "react";

export type PolledResource<T> = {
  data: T | null;
  error: Error | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
};

/**
 * Loads `fetcher` on mount and every `intervalMs` while the document is visible.
 * Pass `intervalMs = null` to load once. Changing `key` restarts polling.
 */
export function usePolledResource<T>(
  fetcher: () => Promise<T>,
  intervalMs: number | null,
  key: unknown = null,
): PolledResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    try {
      setData(await fetcherRef.current());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error(String(caught)));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    async function tick() {
      if (cancelled) return;
      if (typeof document === "undefined" || document.visibilityState !== "hidden") await refresh();
      if (!cancelled && intervalMs !== null) timer = setTimeout(() => void tick(), intervalMs);
    }

    setIsLoading(true);
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs, key, refresh]);

  return { data, error, isLoading, refresh };
}
