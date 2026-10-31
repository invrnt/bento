import { useState } from "react";
import { Heart, Play } from "lucide-react";

import { assetPreviewUrl, assetThumbnailUrl } from "../../api/photos";
import type { PhotoAsset } from "../../api/photos";
import type { MenuItem } from "../../components/Menu";
import { t } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { formatMessage } from "../../lib/format";
import { ActionContextMenu } from "../drive/ActionContextMenu";

export type PhotoCardProps = {
  asset: PhotoAsset;
  /** Right-click actions (Vista rápida, Enviar por Telegram…, Eliminar). */
  menuItems?: MenuItem[];
  onOpen: (asset: PhotoAsset) => void;
  showFavoriteMarker?: boolean;
};

/** Space, Enter or a click open the photo in Quick Look (the native button activation). */
export function PhotoCard({ asset, menuItems, onOpen, showFavoriteMarker = true }: PhotoCardProps) {
  const isVideo = asset.kind === "video";
  const src = isVideo ? assetThumbnailUrl(asset) : assetPreviewUrl(asset);
  // Justified rows: each tile grows in proportion to its aspect ratio, read once the image loads.
  const [ratio, setRatio] = useState(isVideo ? 16 / 9 : 4 / 3);

  const card = (
    <button
      aria-label={asset.filename}
      className="group/photo focus-ring relative block h-(--row-h) overflow-hidden rounded-md bg-sunken"
      onClick={() => onOpen(asset)}
      style={{ flexBasis: `calc(var(--row-h) * ${ratio})`, flexGrow: ratio }}
      type="button"
    >
      <img
        alt={asset.filename}
        className={cx(
          "block size-full select-none object-cover transition-transform duration-300 ease-out group-hover/photo:scale-[1.02]",
          isVideo ? "bg-media" : undefined,
        )}
        draggable={false}
        loading="lazy"
        onLoad={(event) => {
          const { naturalHeight, naturalWidth } = event.currentTarget;
          if (naturalWidth > 0 && naturalHeight > 0) {
            setRatio(Math.min(3, Math.max(0.5, naturalWidth / naturalHeight)));
          }
        }}
        src={src}
      />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-linear-to-t from-black/35 via-black/0 to-black/0 opacity-0 transition-opacity duration-200 group-hover/photo:opacity-100 group-focus-visible/photo:opacity-100"
      />
      {showFavoriteMarker && asset.favorite ? (
        <Heart
          aria-hidden="true"
          className="absolute right-2 top-2 size-4 fill-shu text-shu drop-shadow-[0_1px_2px_oklch(0_0_0/0.45)]"
        />
      ) : null}
      {isVideo ? (
        <span
          aria-hidden="true"
          className="absolute bottom-2 left-2 inline-flex h-5 items-center gap-1 rounded-full bg-black/50 px-2 text-2xs font-medium text-white backdrop-blur-sm"
        >
          <Play className="size-2.5 fill-current" />
          {t("photos.video")}
        </span>
      ) : null}
    </button>
  );

  return menuItems?.length ? (
    <ActionContextMenu items={menuItems} label={formatMessage("photos.actions", { name: asset.filename })}>
      {card}
    </ActionContextMenu>
  ) : (
    card
  );
}
