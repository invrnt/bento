import type { ReactNode } from "react";
import { File, FileStack, FileText, Film, Folder, Image, ScanText, Sparkles, SquareLibrary } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "../../components/Badge";
import type { BadgeTone } from "../../components/Badge";
import { Card } from "../../components/Card";
import { ProgressBar } from "../../components/ProgressBar";
import { Thumbnail } from "../../components/Thumbnail";
import { VirtualList } from "../../components/VirtualList";
import type { SearchHit, SearchProcessingState, SearchResultType } from "../../api/search";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { groupSearchHits } from "./searchFilters";

export type SearchResultsListProps = {
  className?: string;
  items: SearchHit[];
  /** Makes each row open on click, Enter or Space (e.g. into Quick Look). */
  onOpenItem?: (item: SearchHit) => void;
  /** Controls at the end of each row, such as an actions menu. */
  renderItemActions?: (item: SearchHit) => ReactNode;
};

const rowHeight = 128;
const maxGroupHeight = rowHeight * 4;

const typeLabels: Record<SearchResultType, MessageKey> = {
  album: "search.type.album",
  asset: "search.type.asset",
  document: "search.type.document",
  folder: "search.type.folder",
  ocr_block: "search.type.ocr_block",
  pdf_page: "search.type.pdf_page",
  photo: "search.type.photo",
  video: "search.type.video",
};

const typeIcons: Record<SearchResultType, LucideIcon> = {
  album: SquareLibrary,
  asset: File,
  document: FileText,
  folder: Folder,
  ocr_block: ScanText,
  pdf_page: FileStack,
  photo: Image,
  video: Film,
};

const stateLabels: Record<SearchProcessingState, MessageKey> = {
  disabled: "search.state.disabled",
  failed: "search.state.failed",
  indexed: "search.state.indexed",
  indexing: "search.state.indexing",
  partial: "search.state.partial",
  pending: "search.state.pending",
};

const stateTones: Record<SearchProcessingState, { pulse: boolean; tone: BadgeTone }> = {
  disabled: { pulse: false, tone: "neutral" },
  failed: { pulse: false, tone: "danger" },
  indexed: { pulse: false, tone: "success" },
  indexing: { pulse: true, tone: "warning" },
  partial: { pulse: false, tone: "warning" },
  pending: { pulse: true, tone: "warning" },
};

export function SearchResultsList({ className, items, onOpenItem, renderItemActions }: SearchResultsListProps) {
  const groups = groupSearchHits(items);

  return (
    <section aria-label={t("search.results.label")} className={cx("grid gap-8", className)}>
      {groups.map((group) => (
        <section aria-labelledby={`search-group-${group.type}`} className="grid gap-3" key={group.type}>
          <div className="flex items-center gap-2.5">
            <h2 className="text-base font-semibold text-ink" id={`search-group-${group.type}`}>
              {t(typeLabels[group.type])}
            </h2>
            <Badge>
              {group.items.length} {t(group.items.length === 1 ? "search.resultCount.one" : "search.resultCount.many")}
            </Badge>
          </div>
          <Card className="overflow-hidden" padding="none">
            <VirtualList
              estimateSize={rowHeight}
              getKey={(item) => item.id}
              height={Math.min(maxGroupHeight, group.items.length * rowHeight)}
              items={group.items}
              renderItem={(item, index) => (
                <SearchResultItem actions={renderItemActions?.(item)} first={index === 0} item={item} onOpen={onOpenItem} />
              )}
            />
          </Card>
        </section>
      ))}
    </section>
  );
}

function SearchResultItem({
  actions,
  first,
  item,
  onOpen,
}: {
  actions?: ReactNode;
  first: boolean;
  item: SearchHit;
  onOpen?: (item: SearchHit) => void;
}) {
  const state = stateTones[item.processing_state] ?? stateTones.partial;
  const stateKey = stateLabels[item.processing_state] ?? "search.state.partial";
  const TypeIcon = typeIcons[item.type] ?? File;
  const percent = scorePercent(item.score);

  return (
    <article
      aria-label={`${item.title}. ${t(typeLabels[item.type])}. ${item.reason}`}
      className={cx(
        "relative grid h-full grid-cols-[4rem_minmax(0,1fr)] gap-4 p-4 transition-colors duration-150 hover:bg-hover",
        !first && "border-t border-line",
      )}
    >
      <Thumbnail alt={item.title} className="size-16 rounded-md" src={item.thumbnail_url ?? undefined}>
        <TypeIcon aria-hidden="true" className="size-6 text-ink-subtle" strokeWidth={1.75} />
      </Thumbnail>
      <div className="min-w-0">
        <div className="flex min-w-0 items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="truncate text-base font-medium text-ink">
              {onOpen ? (
                // The stretched button makes the whole row open; actions sit above it.
                <button
                  className="focus-ring rounded-xs text-left after:absolute after:inset-0 after:content-['']"
                  onClick={() => onOpen(item)}
                  type="button"
                >
                  {item.title}
                </button>
              ) : (
                item.title
              )}
            </h3>
            {item.subtitle ? <p className="truncate text-sm text-ink-muted">{item.subtitle}</p> : null}
          </div>
          <div className="flex shrink-0 items-center gap-2 pt-1" title={t("search.relevance")}>
            {percent === null ? null : <ProgressBar className="w-16" value={percent} />}
            <span className="min-w-9 whitespace-nowrap text-right text-xs tabular-nums text-ink-muted">{formatScore(percent)}</span>
            {actions ? <div className="relative z-10 -my-1.5">{actions}</div> : null}
          </div>
        </div>
        <p className="mt-1.5 flex min-w-0 items-center gap-1.5 text-sm text-ink">
          <Sparkles aria-hidden="true" className="size-3.5 shrink-0 text-accent-ink" />
          <span className="truncate">{item.reason}</span>
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Badge icon={<TypeIcon aria-hidden="true" />} tone="accent">
            {t(typeLabels[item.type])}
          </Badge>
          <Badge dot pulse={state.pulse} tone={state.tone}>
            {t(stateKey)}
          </Badge>
        </div>
      </div>
    </article>
  );
}

function scorePercent(score: number | null | undefined): number | null {
  return Number.isFinite(score) ? Math.round(Number(score) * 100) : null;
}

function formatScore(percent: number | null): string {
  return percent === null ? t("search.scoreUnavailable") : `${percent} %`;
}
