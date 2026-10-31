import type { PhotoAsset, PhotoTimelineGroup } from "../../api/photos";
import { t } from "../../i18n/dictionary";
import { formatTimelineDate, groupTimelineByMonth } from "./dateGrouping";
import { PhotoGrid } from "./PhotoGrid";

export type PhotoTimelineProps = {
  groups: PhotoTimelineGroup[];
  onOpen: (asset: PhotoAsset) => void;
  showFavoriteMarkers?: boolean;
};

export function PhotoTimeline({ groups, onOpen, showFavoriteMarkers = true }: PhotoTimelineProps) {
  const months = groupTimelineByMonth(groups);

  return (
    <section aria-label={t("photos.timelineLabel")} className="grid gap-10">
      {months.map((month) => (
        <section className="grid gap-2" key={month.monthLabel}>
          <h2 className="text-xl font-semibold tracking-tight text-ink first-letter:uppercase">{month.monthLabel}</h2>
          <div className="grid gap-4">
            {month.days.map((day) => (
              <section key={day.date}>
                <div className="sticky top-0 z-10 -mx-1 flex items-baseline justify-between gap-3 bg-surface/90 px-1 py-2 backdrop-blur-md">
                  <h3 className="text-sm font-medium text-ink-muted first-letter:uppercase">{formatTimelineDate(day.date)}</h3>
                  <span className="text-xs tabular-nums text-ink-subtle">
                    {day.assets.length} {day.assets.length === 1 ? t("photos.item") : t("photos.items")}
                  </span>
                </div>
                <PhotoGrid assets={day.assets} onOpen={onOpen} showFavoriteMarkers={showFavoriteMarkers} />
              </section>
            ))}
          </div>
        </section>
      ))}
    </section>
  );
}
