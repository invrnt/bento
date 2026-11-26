import type { SmartSearchStatus } from "../../../api/smartSearch";
import { ProgressBar } from "../../../components/ProgressBar";
import { Spinner } from "../../../components/Spinner";
import { t } from "../../../i18n/dictionary";
import { cx } from "../../../lib/cx";
import { describeSmartSearch, formatPercent } from "./model";

/**
 * The state line ("Descargando… 105 MB de 310 MB · 34 %") with its progressbar. The visible text
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
