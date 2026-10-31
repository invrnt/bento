import { useCallback, useEffect, useState } from "react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { getVault, isRemovedDevice } from "../../api/vault";
import type { VaultStatus } from "../../api/vault";
import { hasChosenLocalMode } from "./localMode";

export type Gate =
  | { kind: "loading" }
  | { kind: "first-run" }
  /** `removed`: another device removed this one; it can join again with a new identity. */
  | { kind: "locked"; removed?: true }
  | { kind: "app"; vault: VaultStatus | null };

const cacheKey = "bento:gate";

/** Decides what the window shows from the vault state and the local-mode choice. */
export function decideGate(vault: VaultStatus | null, localChosen: boolean): Gate {
  switch (vault?.state) {
    case "signed_out":
    case "no_vault":
      return localChosen ? { kind: "app", vault } : { kind: "first-run" };
    case "locked":
      return isRemovedDevice(vault) ? { kind: "locked", removed: true } : { kind: "locked" };
    case "local_only":
    case "bootstrapping":
    case "ready":
      return { kind: "app", vault };
    default:
      // Older backends or a temporarily unreachable API: never block the library.
      return { kind: "app", vault: null };
  }
}

export type AppGate = {
  gate: Gate;
  /** Re-reads the vault and re-decides (used after setup, join or sign-out). */
  refresh: () => Promise<Gate>;
  /** Forces a gate, e.g. to reopen setup from Settings. */
  setGate: (gate: Gate) => void;
};

export function useAppGate(client: ApiClient = apiClient): AppGate {
  const [gate, setGateState] = useState<Gate>(() => (readCachedApp() ? { kind: "app", vault: null } : { kind: "loading" }));

  const setGate = useCallback((next: Gate) => {
    writeCachedApp(next.kind === "app");
    setGateState(next);
  }, []);

  const refresh = useCallback(async () => {
    let vault: VaultStatus | null = null;
    try {
      vault = await getVault(client);
    } catch {
      vault = null;
    }
    const next = decideGate(vault, hasChosenLocalMode());
    setGate(next);
    return next;
  }, [client, setGate]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { gate, refresh, setGate };
}

function readCachedApp(): boolean {
  try {
    return window.localStorage.getItem(cacheKey) === "app";
  } catch {
    return false;
  }
}

function writeCachedApp(isApp: boolean): void {
  try {
    if (isApp) window.localStorage.setItem(cacheKey, "app");
    else window.localStorage.removeItem(cacheKey);
  } catch {
    // The cache only speeds up the next launch.
  }
}
