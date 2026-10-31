import { useEffect, useState } from "react";

import { ApiError, apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { getPairing, terminalPairingStates } from "../../api/pairing";
import type { Pairing } from "../../api/pairing";

export type PairingSession = {
  pairing: Pairing | null;
  setPairing: (pairing: Pairing | null) => void;
  terminal: boolean;
};

/** Follows a pairing with `GET /pairing/{id}` until it reaches a terminal state. */
export function usePairingSession(
  initial: Pairing | null,
  { client = apiClient, pollIntervalMs = 1000 }: { client?: ApiClient; pollIntervalMs?: number } = {},
): PairingSession {
  const [pairing, setPairing] = useState<Pairing | null>(initial);

  useEffect(() => {
    setPairing(initial);
  }, [initial]);

  const id = pairing?.id ?? null;
  const terminal = pairing ? terminalPairingStates.has(pairing.state) : false;

  useEffect(() => {
    if (!id || terminal) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      try {
        const next = await getPairing(id!, client);
        // A late poll must never undo a local decision (approve/reject/cancel) that already ended it.
        if (!cancelled) setPairing((current) => (current && current.id === next.id && terminalPairingStates.has(current.state) ? current : next));
      } catch (caught) {
        // Sessions live in API memory; a restart forgets them.
        if (!cancelled && caught instanceof ApiError && caught.status === 404) {
          setPairing((current) => (current ? { ...current, error: { code: "pairing_not_found", message: "" }, state: "failed" } : current));
          return;
        }
      }
      if (!cancelled) timer = setTimeout(() => void tick(), pollIntervalMs);
    }

    timer = setTimeout(() => void tick(), pollIntervalMs);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [client, id, pollIntervalMs, terminal]);

  return { pairing, setPairing, terminal };
}
