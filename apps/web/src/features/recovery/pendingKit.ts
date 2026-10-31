import { useSyncExternalStore } from "react";

/**
 * The newest recovery code that has not been confirmed yet, kept in memory only
 * (never in storage) so "Guardar kit" later in this session shows the same code.
 */
let pendingCode: string | null = null;
const listeners = new Set<() => void>();

export function setPendingRecoveryCode(code: string | null): void {
  pendingCode = code;
  listeners.forEach((listener) => listener());
}

export function getPendingRecoveryCode(): string | null {
  return pendingCode;
}

export function usePendingRecoveryCode(): string | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => pendingCode,
    () => null,
  );
}
