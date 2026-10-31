import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { getSyncStatus } from "../../api/sync";
import type { SyncStatus } from "../../api/sync";
import { usePolledResource } from "../../lib/usePolledResource";

export type BootstrapStatus = {
  done: number;
  /** True once the first snapshot has been applied. */
  finished: boolean;
  /** 0–100, or null while the total is unknown. */
  percent: number | null;
  status: SyncStatus | null;
  total: number;
};

/** "Descargando tu biblioteca… 1.240 de 3.000" from `GET /sync/status`, polled while it runs. */
export function useBootstrapStatus(client: ApiClient = apiClient, pollIntervalMs = 1000, enabled = true): BootstrapStatus {
  const resource = usePolledResource(() => getSyncStatus(client), enabled ? pollIntervalMs : null, enabled);
  return summarizeBootstrap(enabled ? resource.data : null);
}

export function summarizeBootstrap(status: SyncStatus | null): BootstrapStatus {
  const done = Math.max(0, status?.bootstrap?.done ?? 0);
  const total = Math.max(0, status?.bootstrap?.total ?? 0);
  const running = status?.state === "bootstrapping" || (total > 0 && done < total);
  return {
    done,
    finished: status !== null && !running,
    percent: total > 0 ? Math.min(100, (done / total) * 100) : null,
    status,
    total,
  };
}
