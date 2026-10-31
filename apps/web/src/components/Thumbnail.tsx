import { useState } from "react";
import type { ReactNode } from "react";

import { cx } from "../lib/cx";
import { t } from "../i18n/dictionary";

export type ThumbnailProps = {
  alt?: string;
  children?: ReactNode;
  className?: string;
  src?: string;
};

export function Thumbnail({ alt = t("common.thumbnail"), children, className, src }: ThumbnailProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showImage = Boolean(src) && src !== failedSrc;

  return (
    <div
      className={cx(
        "relative flex aspect-square w-full items-center justify-center overflow-hidden rounded-md bg-sunken",
        className,
      )}
    >
      {showImage ? (
        <img
          alt={alt}
          className="size-full select-none object-cover"
          draggable={false}
          loading="lazy"
          onError={() => setFailedSrc(src ?? null)}
          src={src}
        />
      ) : (
        <div className="grid size-full select-none place-items-center p-2 text-center text-xs font-medium text-ink-subtle">
          {children ?? alt}
        </div>
      )}
    </div>
  );
}
