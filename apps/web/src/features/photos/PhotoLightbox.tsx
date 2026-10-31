import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Download, Heart, X } from "lucide-react";

import { IconButton } from "../../components/IconButton";
import { Kbd } from "../../components/Kbd";
import { Tooltip } from "../../components/Tooltip";
import { assetDownloadUrl, assetPreviewUrl } from "../../api/photos";
import type { PhotoAsset } from "../../api/photos";
import { t } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { ProcessingStateBadge } from "./ProcessingStateBadge";

const focusableSelector = [
  "a[href]",
  "button:not(:disabled)",
  "input:not(:disabled)",
  "select:not(:disabled)",
  "textarea:not(:disabled)",
  "video[controls]",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

const overlayKbd = "border-white/15 bg-white/10 text-white/80 shadow-none";

export type PhotoLightboxProps = {
  asset: PhotoAsset | null;
  onClose: () => void;
  onNext?: () => void;
  onPrevious?: () => void;
  onToggleFavorite: (asset: PhotoAsset) => void;
};

export function PhotoLightbox({ asset, onClose, onNext, onPrevious, onToggleFavorite }: PhotoLightboxProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const isOpen = asset !== null;

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    returnFocusRef.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();

    return () => {
      returnFocusRef.current?.focus();
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function onDocumentKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }

      if (event.key === "ArrowRight") {
        onNext?.();
      }

      if (event.key === "ArrowLeft") {
        onPrevious?.();
      }

      if (event.key === "Tab") {
        trapFocus(event, panelRef.current);
      }
    }

    document.addEventListener("keydown", onDocumentKeyDown);

    return () => document.removeEventListener("keydown", onDocumentKeyDown);
  }, [isOpen, onClose, onNext, onPrevious]);

  if (!asset) {
    return null;
  }

  const favoriteLabel = asset.favorite ? t("photos.unfavorite") : t("photos.favorite");

  return createPortal(
    <div className="fixed inset-0 z-50 animate-fade-in bg-media text-white" role="presentation">
      <div
        aria-labelledby={titleId}
        aria-modal="true"
        className="relative h-full outline-none"
        ref={panelRef}
        role="dialog"
        tabIndex={-1}
      >
        <div
          className="absolute inset-0 flex items-center justify-center px-4 pb-16 pt-20 sm:px-20"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              onClose();
            }
          }}
        >
          {asset.kind === "video" ? (
            <video
              aria-label={asset.filename}
              className="max-h-full max-w-full rounded-lg bg-black shadow-xl"
              controls
              key={asset.id}
              src={assetDownloadUrl(asset)}
            />
          ) : (
            <img
              alt={asset.filename}
              className="max-h-full max-w-full animate-fade-in select-none rounded-lg object-contain shadow-xl"
              draggable={false}
              key={asset.id}
              src={assetPreviewUrl(asset)}
            />
          )}
        </div>

        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between gap-4 bg-linear-to-b from-black/65 to-black/0 px-4 pb-12 pt-4 sm:px-6">
          <div className="pointer-events-auto min-w-0">
            <h2 className="truncate text-md font-semibold text-white" id={titleId}>
              {asset.filename}
            </h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <span className="text-sm text-white/70">{asset.kind === "video" ? t("photos.video") : t("photos.photo")}</span>
              <ProcessingStateBadge state={asset.processing_state} />
            </div>
          </div>
          <div className="pointer-events-auto flex shrink-0 items-center gap-1.5">
            <IconButton
              aria-pressed={asset.favorite}
              icon={<Heart className={cx(asset.favorite && "fill-shu text-shu")} />}
              label={favoriteLabel}
              onClick={() => onToggleFavorite(asset)}
              size="lg"
              tooltipSide="bottom"
              variant="overlay"
            />
            <Tooltip label={t("photos.download")} side="bottom">
              <a
                aria-label={t("photos.download")}
                className="focus-ring inline-flex size-10 items-center justify-center rounded-md border border-white/10 bg-black/35 text-white backdrop-blur-md transition-colors duration-150 hover:bg-white/15"
                download={asset.filename}
                href={assetDownloadUrl(asset)}
              >
                <Download aria-hidden="true" className="size-5" />
              </a>
            </Tooltip>
            <IconButton icon={<X />} label={t("common.close")} onClick={onClose} size="lg" tooltipSide="bottom" variant="overlay" />
          </div>
        </div>

        <div className="absolute left-3 top-1/2 z-10 -translate-y-1/2 sm:left-5">
          <IconButton
            className="rounded-full"
            disabled={!onPrevious}
            icon={<ChevronLeft />}
            label={t("photos.previous")}
            onClick={onPrevious}
            size="lg"
            tooltipSide="right"
            variant="overlay"
          />
        </div>
        <div className="absolute right-3 top-1/2 z-10 -translate-y-1/2 sm:right-5">
          <IconButton
            className="rounded-full"
            disabled={!onNext}
            icon={<ChevronRight />}
            label={t("photos.next")}
            onClick={onNext}
            size="lg"
            tooltipSide="left"
            variant="overlay"
          />
        </div>

        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 hidden items-center justify-center gap-4 pb-5 text-xs text-white/60 sm:flex"
        >
          <span className="inline-flex items-center gap-1.5">
            <Kbd className={overlayKbd}>←</Kbd>
            <Kbd className={overlayKbd}>→</Kbd>
            {t("photos.hint.navigate")}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Kbd className={overlayKbd}>Esc</Kbd>
            {t("photos.hint.close")}
          </span>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function getFocusable(root: HTMLElement | null): HTMLElement[] {
  if (!root) {
    return [];
  }

  return Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    (element) => !element.hasAttribute("disabled") && element.tabIndex !== -1,
  );
}

function trapFocus(event: globalThis.KeyboardEvent, root: HTMLElement | null) {
  const focusable = getFocusable(root);

  if (focusable.length === 0) {
    event.preventDefault();
    root?.focus();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  if (event.shiftKey && (document.activeElement === first || document.activeElement === root)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
