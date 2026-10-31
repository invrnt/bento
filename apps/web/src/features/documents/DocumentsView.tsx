import { useMemo, useState } from "react";
import { Download, Eye, MoreHorizontal, Send } from "lucide-react";

import type { SearchHit } from "../../api/search";
import { IconButton } from "../../components/IconButton";
import { Menu } from "../../components/Menu";
import { t } from "../../i18n/dictionary";
import { formatMessage } from "../../lib/format";
import { QuickLook } from "../quicklook/QuickLook";
import { downloadUrl, quickLookKind, useQuickLook } from "../quicklook/quickLookModel";
import type { QuickLookItem } from "../quicklook/quickLookModel";
import { SearchView } from "../search";
import type { SearchViewProps } from "../search";
import { SearchResultsList } from "../search/SearchResultsList";
import { ShareToTelegramDialog } from "../share/ShareToTelegramDialog";
import type { ShareApi, ShareTarget } from "../share/ShareToTelegramDialog";

export type DocumentsViewProps = Omit<SearchViewProps, "renderResults" | "scope"> & {
  shareApi?: ShareApi;
};

export function DocumentsView({ shareApi, ...props }: DocumentsViewProps) {
  return <SearchView {...props} renderResults={(items) => <DocumentResults items={items} shareApi={shareApi} />} scope="documents" />;
}

/** Results open in Quick Look (click, Enter or Space) and can be sent by Telegram. */
function DocumentResults({ items, shareApi }: { items: SearchHit[]; shareApi?: ShareApi }) {
  const quickLookItems = useMemo(() => documentQuickLookItems(items), [items]);
  const quickLook = useQuickLook(quickLookItems);
  const [shareTarget, setShareTarget] = useState<ShareTarget | null>(null);

  function itemFor(hit: SearchHit): QuickLookItem | undefined {
    return quickLookItems.find((item) => item.id === hit.asset_id);
  }

  return (
    <>
      <SearchResultsList
        items={items}
        onOpenItem={(hit) => {
          if (hit.asset_id) {
            quickLook.open(hit.asset_id);
          }
        }}
        renderItemActions={(hit) => {
          const item = itemFor(hit);
          return item ? (
            <Menu
              items={[
                { icon: <Eye />, id: "quicklook", label: t("quicklook.action"), onSelect: () => quickLook.open(item.id) },
                { icon: <Send />, id: "share", label: t("share.action"), onSelect: () => setShareTarget({ id: item.id, name: item.name }) },
                {
                  icon: <Download />,
                  id: "download",
                  label: t("quicklook.download"),
                  onSelect: () => window.open(downloadUrl(item), "_blank", "noopener,noreferrer"),
                },
              ]}
              label={formatMessage("documents.actions", { name: hit.title })}
              trigger={<MoreHorizontal aria-hidden="true" />}
              triggerVariant="ghost"
            />
          ) : null;
        }}
      />
      <QuickLook
        actions={(item) => (
          <IconButton
            icon={<Send />}
            label={t("share.action")}
            onClick={() => setShareTarget({ id: item.id, name: item.name })}
            size="lg"
            tooltipSide="bottom"
            variant="overlay"
          />
        )}
        controller={quickLook}
      />
      <ShareToTelegramDialog api={shareApi} onClose={() => setShareTarget(null)} target={shareTarget} />
    </>
  );
}

/** One Quick Look item per asset (several PDF pages of one file collapse into it). */
export function documentQuickLookItems(hits: SearchHit[]): QuickLookItem[] {
  const seen = new Set<string>();
  const items: QuickLookItem[] = [];

  for (const hit of hits) {
    if (!hit.asset_id || seen.has(hit.asset_id)) {
      continue;
    }
    seen.add(hit.asset_id);
    items.push({
      id: hit.asset_id,
      kind: hit.type === "pdf_page" ? "pdf" : hit.type === "photo" ? "image" : hit.type === "video" ? "video" : quickLookKind(hit.title),
      name: hit.title,
    });
  }

  return items;
}
