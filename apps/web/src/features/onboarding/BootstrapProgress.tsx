import { useEffect, useState } from "react";
import { CloudDownload } from "lucide-react";

import type { ApiClient } from "../../api/client";
import { Callout } from "../../components/Callout";
import { ProgressBar } from "../../components/ProgressBar";
import { t } from "../../i18n/dictionary";
import { formatNumber, tf } from "./format";
import type { BootstrapStatus } from "./useBootstrapStatus";
import { useBootstrapStatus } from "./useBootstrapStatus";

export function bootstrapLine(progress: BootstrapStatus): string {
  if (progress.total > 0) {
    return tf("bootstrap.progress", { done: formatNumber(progress.done), total: formatNumber(progress.total) });
  }
  return t("bootstrap.starting");
}

/** Progress block used on the join screen while the library downloads. */
export function BootstrapMeter({ progress }: { progress: BootstrapStatus }) {
  return (
    <div className="grid gap-2.5">
      <ProgressBar className="h-2" label={t("bootstrap.label")} value={progress.finished ? 100 : (progress.percent ?? 4)} />
      <p aria-live="polite" className="text-sm tabular-nums text-ink-muted" role="status">
        {progress.finished ? t("bootstrap.finished") : bootstrapLine(progress)}
      </p>
    </div>
  );
}

/** Slim banner above the library while a newly joined device downloads it; hides when done. */
export function BootstrapBanner({ client, pollIntervalMs = 2000 }: { client?: ApiClient; pollIntervalMs?: number }) {
  const [finished, setFinished] = useState(false);
  const progress = useBootstrapStatus(client, pollIntervalMs, !finished);

  useEffect(() => {
    if (progress.finished) setFinished(true);
  }, [progress.finished]);

  if (finished || !progress.status) return null;

  return (
    <Callout className="mb-5" icon={<CloudDownload />} role="status" title={t("bootstrap.title")} tone="info">
      <div className="grid gap-2 sm:min-w-80">
        <span className="tabular-nums">{bootstrapLine(progress)}</span>
        <ProgressBar label={t("bootstrap.label")} value={progress.percent ?? 4} />
      </div>
    </Callout>
  );
}
