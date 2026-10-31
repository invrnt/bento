import { useState } from "react";
import { SquareLibrary } from "lucide-react";

import { t } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";

export type AlbumCoverProps = {
  className?: string;
  compact?: boolean;
  src?: string;
};

/** Album cover with a branded fallback tile; decorative because the album title is always next to it. */
export function AlbumCover({ className, compact = false, src }: AlbumCoverProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showImage = Boolean(src) && src !== failedSrc;

  return (
    <div className={cx("relative overflow-hidden bg-sunken", className)}>
      {showImage ? (
        <img
          alt=""
          className="size-full select-none object-cover"
          draggable={false}
          loading="lazy"
          onError={() => setFailedSrc(src ?? null)}
          src={src}
        />
      ) : (
        <div className="grid size-full place-items-center bg-kind-image-soft text-kind-image">
          <div className="flex flex-col items-center gap-1.5">
            <SquareLibrary aria-hidden="true" className={compact ? "size-6" : "size-7"} strokeWidth={1.5} />
            {compact ? null : <span className="text-xs font-medium">{t("albums.emptyCover")}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
