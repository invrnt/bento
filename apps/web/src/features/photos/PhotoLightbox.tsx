import { Heart, Send, Trash2 } from "lucide-react";

import { IconButton } from "../../components/IconButton";
import { assetDownloadUrl, assetPreviewUrl, assetThumbnailUrl } from "../../api/photos";
import type { PhotoAsset } from "../../api/photos";
import { t } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { QuickLookViewer } from "../quicklook/QuickLook";
import type { QuickLookItem } from "../quicklook/quickLookModel";
import { ProcessingStateBadge } from "./ProcessingStateBadge";

export type PhotoLightboxProps = {
  asset: PhotoAsset | null;
  onClose: () => void;
  onDelete?: (asset: PhotoAsset) => void;
  onNext?: () => void;
  onPrevious?: () => void;
  onShare?: (asset: PhotoAsset) => void;
  onToggleFavorite: (asset: PhotoAsset) => void;
  position?: { index: number; total: number };
};

/** Photos and videos in Quick Look: image previews, streamed videos, favorite/share/delete. */
export function photoQuickLookItem(asset: PhotoAsset): QuickLookItem {
  const isVideo = asset.kind === "video";

  return {
    downloadUrl: assetDownloadUrl(asset),
    id: asset.id,
    kind: isVideo ? "video" : "image",
    name: asset.filename,
    posterUrl: isVideo ? assetThumbnailUrl(asset) : null,
    previewUrl: isVideo ? null : assetPreviewUrl(asset),
    sizeBytes: asset.size_bytes || null,
  };
}

export function PhotoLightbox({ asset, onClose, onDelete, onNext, onPrevious, onShare, onToggleFavorite, position }: PhotoLightboxProps) {
  if (!asset) {
    return null;
  }

  const favoriteLabel = asset.favorite ? t("photos.unfavorite") : t("photos.favorite");

  return (
    <QuickLookViewer
      actions={
        <>
          <IconButton
            aria-pressed={asset.favorite}
            icon={<Heart className={cx(asset.favorite && "fill-shu text-shu")} />}
            label={favoriteLabel}
            onClick={() => onToggleFavorite(asset)}
            size="lg"
            tooltipSide="bottom"
            variant="overlay"
          />
          {onShare ? (
            <IconButton icon={<Send />} label={t("share.action")} onClick={() => onShare(asset)} size="lg" tooltipSide="bottom" variant="overlay" />
          ) : null}
          {onDelete ? (
            <IconButton icon={<Trash2 />} label={t("photos.delete")} onClick={() => onDelete(asset)} size="lg" tooltipSide="bottom" variant="overlay" />
          ) : null}
        </>
      }
      item={photoQuickLookItem(asset)}
      meta={<ProcessingStateBadge state={asset.processing_state} />}
      onClose={onClose}
      onNext={onNext}
      onPrevious={onPrevious}
      position={position}
    />
  );
}
