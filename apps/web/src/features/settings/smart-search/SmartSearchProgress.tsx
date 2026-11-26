import type { SmartSearchStatus } from "../../../api/smartSearch";
import { ProgressBar } from "../../../components/ProgressBar";
import { Spinner } from "../../../components/Spinner";
import { t } from "../../../i18n/dictionary";
import { cx } from "../../../lib/cx";
import { describeSmartSearch, describeUpdate, formatPercent } from "./model";

/**
 * The state line ("Descargando… 100 MB de 296 MB · 33 %") with its progressbar. The visible text
 * is the bar's text equivalent; the bar carries `aria-valuenow`/`aria-valuemax` in percent.
 */
export function SmartSearchProgress({ status }: { status: SmartSearchStatus }) {
  const view = describeSmartSearch(status);
  const danger = status.state === "error";

  return (
    <div className="grid gap-2" data-testid="smart-search-progress">
      <p className={cx("flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm", danger ? "font-medium text-danger-ink" : "text-ink-muted")}>
        <span className="flex items-center gap-2">
          {view.indeterminate ? <Spinner className="text-accent-ink" /> : null}
          <span>{view.text}</span>
        </span>
        {view.progress ? <span className="tabular-nums">{formatPercent(view.progress.percent)}</span> : null}
      </p>
      {view.progress ? (
        <ProgressBar
          label={t(view.progress.kind === "download" ? "smartSearch.progress.download" : "smartSearch.progress.indexing")}
          value={Math.floor(view.progress.percent)}
        />
      ) : null}
    </div>
  );
}

/**
 * The secondary line under "Lista" while a newer model revision downloads. Search keeps using the
 * installed model meanwhile, so this is quieter than the main state line.
 */
export function SmartSearchUpdateProgress({ status }: { status: SmartSearchStatus }) {
  const view = describeUpdate(status);
  if (!view) return null;

  return (
    <div className="grid gap-1.5" data-testid="smart-search-update-progress">
      <p className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-ink-muted">
        <span className="flex items-center gap-2">
          {view.indeterminate ? <Spinner className="text-accent-ink" /> : null}
          <span>{view.text}</span>
        </span>
        {view.indeterminate ? null : <span className="tabular-nums">{formatPercent(view.percent)}</span>}
      </p>
      {view.indeterminate ? null : <ProgressBar label={t("smartSearch.progress.update")} value={Math.floor(view.percent)} />}
    </div>
  );
}
