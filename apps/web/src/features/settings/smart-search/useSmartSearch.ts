import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiClient } from "../../../api/client";
import type { ApiClient } from "../../../api/client";
import {
  activateSmartSearch,
  cancelSmartSearch,
  getSmartSearchStatus,
  pauseSmartSearch,
  removeSmartSearchModel,
  resumeSmartSearch,
  retrySmartSearch,
  updateSmartSearchModel,
} from "../../../api/smartSearch";
import type { SmartSearchActivation, SmartSearchStatus } from "../../../api/smartSearch";
import { usePolledResource } from "../../../lib/usePolledResource";
import { busyStates } from "./model";

export type SmartSearchStatusOptions = {
  /** `false` skips every request (the onboarding suggestion on a small machine). */
  enabled?: boolean;
  /** Poll interval while nothing runs (`off`, `paused`, `ready`, `error`): catches a new backlog or a restored network. */
  idlePollIntervalMs?: number | null;
  /** Poll interval while downloading, verifying, starting or indexing. */
  pollIntervalMs?: number;
};

export type SmartSearchStatusResource = {
  error: Error | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
  /** Shows a status a mutation just returned, until the next poll answers. */
  setStatus: (status: SmartSearchStatus) => void;
  status: SmartSearchStatus | null;
};

/** `GET /api/smart-search`, polled every second while work runs and slowly otherwise. */
export function useSmartSearchStatus(client: ApiClient = apiClient, options: SmartSearchStatusOptions = {}): SmartSearchStatusResource {
  const { enabled = true, idlePollIntervalMs = 10_000, pollIntervalMs = 1000 } = options;
  const [busy, setBusy] = useState(false);
  const resource = usePolledResource<SmartSearchStatus | null>(
    () => (enabled ? getSmartSearchStatus(client) : Promise.resolve(null)),
    enabled ? (busy ? pollIntervalMs : idlePollIntervalMs) : null,
    enabled,
  );
  const [override, setOverride] = useState<{ base: SmartSearchStatus | null; status: SmartSearchStatus } | null>(null);
  // A fresher poll (a new `resource.data` object) always wins over a mutation's answer.
  const status = override && override.base === resource.data ? override.status : resource.data;
  const state = status?.state;

  useEffect(() => {
    setBusy(state ? busyStates.has(state) : false);
  }, [state]);

  const baseRef = useRef(resource.data);
  baseRef.current = resource.data;
  const setStatus = useCallback((next: SmartSearchStatus) => setOverride({ base: baseRef.current, status: next }), []);

  return { error: status ? null : resource.error, isLoading: resource.isLoading && !status, refresh: resource.refresh, setStatus, status };
}

export type SmartSearchAction = "activate" | "pause" | "resume" | "retry" | "cancel" | "update" | "remove";

export type SmartSearchMutations = {
  activate: (activation?: SmartSearchActivation) => Promise<SmartSearchStatus | null>;
  cancel: () => Promise<SmartSearchStatus | null>;
  clearError: () => void;
  error: { action: SmartSearchAction; error: unknown } | null;
  pause: () => Promise<SmartSearchStatus | null>;
  pending: SmartSearchAction | null;
  remove: () => Promise<SmartSearchStatus | null>;
  resume: () => Promise<SmartSearchStatus | null>;
  retry: () => Promise<SmartSearchStatus | null>;
  update: () => Promise<SmartSearchStatus | null>;
};

/**
 * The smart search actions. Each one shows the status the API answers right away; a refused
 * request (a state conflict, no space, an env lock) re-reads the status so the screen is truthful.
 * Resolves to the new status, or `null` when the request failed (see `error`).
 */
export function useSmartSearchMutations(
  client: ApiClient = apiClient,
  target: Pick<SmartSearchStatusResource, "refresh" | "setStatus">,
): SmartSearchMutations {
  const [pending, setPending] = useState<SmartSearchAction | null>(null);
  const [error, setError] = useState<SmartSearchMutations["error"]>(null);
  const pendingRef = useRef<SmartSearchAction | null>(null);
  const targetRef = useRef(target);
  targetRef.current = target;

  const run = useCallback(async (action: SmartSearchAction, request: () => Promise<SmartSearchStatus | undefined>) => {
    if (pendingRef.current) return null;
    pendingRef.current = action;
    setPending(action);
    setError(null);
    try {
      const next = await request();
      if (next && typeof next === "object") targetRef.current.setStatus(next);
      else await targetRef.current.refresh();
      return next ?? null;
    } catch (caught) {
      setError({ action, error: caught });
      void targetRef.current.refresh();
      return null;
    } finally {
      pendingRef.current = null;
      setPending(null);
    }
  }, []);

  return useMemo(
    () => ({
      activate: (activation: SmartSearchActivation = {}) => run("activate", () => activateSmartSearch(activation, client)),
      cancel: () => run("cancel", () => cancelSmartSearch(client)),
      clearError: () => setError(null),
      error,
      pause: () => run("pause", () => pauseSmartSearch(client)),
      pending,
      remove: () => run("remove", () => removeSmartSearchModel(client)),
      resume: () => run("resume", () => resumeSmartSearch(client)),
      retry: () => run("retry", () => retrySmartSearch(client)),
      update: () => run("update", () => updateSmartSearchModel(client)),
    }),
    [client, error, pending, run],
  );
}
