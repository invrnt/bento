import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { getSettingsValues, patchSettings } from "../../api/settings";
import { desktopBridge } from "../../api/settingsDesktop";

const storageKey = "bento:local-mode";

/** True when the person chose "Usar solo en este equipo" (or skipped Telegram) on this device. */
export function hasChosenLocalMode(): boolean {
  try {
    return window.localStorage.getItem(storageKey) === "1";
  } catch {
    return false;
  }
}

export function rememberLocalMode(): void {
  try {
    window.localStorage.setItem(storageKey, "1");
  } catch {
    // Without storage the choice lasts for this session only.
  }
}

export function forgetLocalMode(): void {
  try {
    window.localStorage.removeItem(storageKey);
  } catch {
    // Nothing to forget.
  }
}

/**
 * Keeps Bento on this device only: remembers the choice and switches the storage
 * backend to `local` through the settings API when it is not already local.
 */
export async function chooseLocalMode(client: ApiClient = apiClient): Promise<void> {
  rememberLocalMode();
  try {
    const snapshot = await getSettingsValues(client);
    const backend = snapshot.values?.storage_backend;
    if (!backend || backend.locked || backend.value === "local") return;
    const bridge = desktopBridge();
    if (bridge) {
      await bridge.settings.apply({ revision: snapshot.revision, runProbes: false, secrets: {}, values: { storage_backend: "local" } });
    } else {
      await patchSettings({ revision: snapshot.revision, values: { storage_backend: "local" } }, client);
    }
  } catch {
    // The local choice is remembered even when settings cannot be changed right now.
  }
}
