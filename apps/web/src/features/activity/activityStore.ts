import { useSyncExternalStore } from "react";

import { getActivity } from "../../api/activity";
import type { Activity } from "../../api/activity";
import { activePollMs, activityPollInterval, idlePollMs, normalizeActivity } from "./activityModel";

export type ActivitySnapshot = {
  activity: Activity | null;
  error: Error | null;
  isLoading: boolean;
};

export type ActivityStore = {
  getSnapshot: () => ActivitySnapshot;
  /** Fetches now (after an action) and reschedules polling. */
  refresh: () => Promise<void>;
  subscribe: (listener: () => void) => () => void;
};

const initialSnapshot: ActivitySnapshot = { activity: null, error: null, isLoading: true };

/**
 * One poller shared by every status surface (sidebar footer, top-bar pill, Activity page).
 * Polls every 3 s while transfers are active and 15 s when idle, stops while the window is
 * hidden, refreshes as soon as it is visible again, and stops entirely with no subscribers.
 */
export function createActivityStore(
  fetcher: () => Promise<unknown> = getActivity,
  intervals: { activeMs: number; idleMs: number } = { activeMs: activePollMs, idleMs: idlePollMs },
): ActivityStore {
  const listeners = new Set<() => void>();
  let snapshot = initialSnapshot;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let inFlight: Promise<void> | null = null;
  let inFlightGeneration = -1;
  let generation = 0;

  function emit(next: ActivitySnapshot) {
    snapshot = next;
    for (const listener of listeners) {
      listener();
    }
  }

  function fetchOnce(): Promise<void> {
    // A request started before the last unsubscribe belongs to a dead generation and would be discarded.
    if (inFlight && inFlightGeneration === generation) {
      return inFlight;
    }

    const current = generation;
    inFlightGeneration = current;
    const request = load(current);
    inFlight = request;
    void request.finally(() => {
      if (inFlight === request) {
        inFlight = null;
      }
    });

    return request;
  }

  async function load(current: number): Promise<void> {
    try {
      const activity = normalizeActivity(await fetcher());
      if (current === generation) {
        emit({ activity, error: null, isLoading: false });
      }
    } catch (caught) {
      if (current === generation) {
        emit({ ...snapshot, error: caught instanceof Error ? caught : new Error(String(caught)), isLoading: false });
      }
    }
  }

  function isHidden() {
    return typeof document !== "undefined" && document.visibilityState === "hidden";
  }

  function schedule() {
    clearTimeout(timer);
    if (listeners.size === 0 || isHidden()) {
      return;
    }

    const delay = activityPollInterval(snapshot.activity) === activePollMs ? intervals.activeMs : intervals.idleMs;
    timer = setTimeout(() => void tick(), delay);
  }

  async function tick() {
    if (isHidden()) {
      return;
    }
    await fetchOnce();
    schedule();
  }

  function onVisibilityChange() {
    if (isHidden()) {
      clearTimeout(timer);
    } else {
      void tick();
    }
  }

  return {
    getSnapshot: () => snapshot,
    async refresh() {
      if (inFlight) {
        await inFlight;
      }
      await fetchOnce();
      schedule();
    },
    subscribe(listener) {
      listeners.add(listener);
      if (listeners.size === 1) {
        document.addEventListener("visibilitychange", onVisibilityChange);
        void tick();
      }

      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) {
          clearTimeout(timer);
          document.removeEventListener("visibilitychange", onVisibilityChange);
          generation += 1;
          snapshot = initialSnapshot;
        }
      };
    },
  };
}

export const activityStore = createActivityStore();

export function useActivity(store: ActivityStore = activityStore): ActivitySnapshot & { refresh: () => Promise<void> } {
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  return { ...snapshot, refresh: store.refresh };
}
