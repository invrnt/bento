import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Download, Music, X } from "lucide-react";

import { IconButton } from "../../components/IconButton";
import { Kbd } from "../../components/Kbd";
import { Tooltip } from "../../components/Tooltip";
import { t } from "../../i18n/dictionary";
import { formatBytes, formatMessage } from "../../lib/format";
import { FileTypeIcon } from "../drive/FileTypeIcon";
import { DocumentPreview } from "./DocumentPreview";
import { contentUrl, downloadUrl, previewUrl, quickLookKindLabels } from "./quickLookModel";
import type { QuickLookController, QuickLookItem } from "./quickLookModel";

const focusableSelector = [
  "a[href]",
  "button:not(:disabled)",
  "input:not(:disabled)",
  "iframe",
  "video[controls]",
  "audio[controls]",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

const overlayKbd = "border-white/15 bg-white/10 text-white/80 shadow-none";
const overlayButton =
  "focus-ring inline-flex size-10 items-center justify-center rounded-md border border-white/10 bg-black/35 text-white backdrop-blur-md transition-colors duration-150 hover:bg-white/15";

export type QuickLookViewerProps = {
  /** Overlay buttons shown before Download and Close (favorite, share, delete…). */
  actions?: ReactNode;
  item: QuickLookItem;
  /** Extra line under the title, e.g. a processing badge. */
  meta?: ReactNode;
  onClose: () => void;
  onNext?: () => void;
  onPrevious?: () => void;
  position?: { index: number; total: number };
};

/**
 * Full-screen viewer, always dark. Images use the preview, every other kind streams from
 * `/content`. Esc or Space close, ← → move, focus stays inside and returns to the opener.
 */
export function QuickLookViewer({ actions, item, meta, onClose, onNext, onPrevious, position }: QuickLookViewerProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const handlers = useRef({ onClose, onNext, onPrevious });
  handlers.current = { onClose, onNext, onPrevious };

  useEffect(() => {
    const returnFocus = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      const panel = panelRef.current;
      const target = event.target as Node | null;
      // Another dialog opened above (e.g. share) owns the keyboard.
      if (!panel || (target && !isDocumentLevel(target) && !panel.contains(target))) {
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        handlers.current.onClose();
        return;
      }

      if (event.key === "Tab") {
        trapFocus(event, panel);
        return;
      }

      if (target instanceof HTMLMediaElement || isEditable(target)) {
        return;
      }

      if (event.key === "ArrowRight" && handlers.current.onNext) {
        event.preventDefault();
        handlers.current.onNext();
      } else if (event.key === "ArrowLeft" && handlers.current.onPrevious) {
        event.preventDefault();
        handlers.current.onPrevious();
      } else if (event.key === " " && !isInteractive(target)) {
        event.preventDefault();
        handlers.current.onClose();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      returnFocus?.focus?.();
    };
  }, []);

  const details = [
    t(quickLookKindLabels[item.kind]),
    formatBytes(item.sizeBytes),
    position && position.total > 1
      ? formatMessage("quicklook.position", { current: position.index + 1, total: position.total })
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const navigable = Boolean(onNext || onPrevious);

  return createPortal(
    <div className="fixed inset-0 z-50 animate-fade-in bg-media text-white [color-scheme:dark]" role="presentation">
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
          <QuickLookContent item={item} key={item.id} />
        </div>

        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between gap-4 bg-linear-to-b from-black/65 to-black/0 px-4 pb-12 pt-4 sm:px-6">
          <div className="pointer-events-auto min-w-0">
            <h2 className="truncate text-md font-semibold text-white" id={titleId}>
              {item.name}
            </h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <span className="text-sm tabular-nums text-white/70">{details}</span>
              {meta}
            </div>
          </div>
          <div className="pointer-events-auto flex shrink-0 items-center gap-1.5">
            {actions}
            <Tooltip label={t("quicklook.download")} side="bottom">
              <a aria-label={t("quicklook.download")} className={overlayButton} download={item.name} href={downloadUrl(item)}>
                <Download aria-hidden="true" className="size-5" />
              </a>
            </Tooltip>
            <IconButton icon={<X />} label={t("common.close")} onClick={onClose} size="lg" tooltipSide="bottom" variant="overlay" />
          </div>
        </div>

        {navigable ? (
          <>
            <div className="absolute left-3 top-1/2 z-10 -translate-y-1/2 sm:left-5">
              <IconButton
                className="rounded-full"
                disabled={!onPrevious}
                icon={<ChevronLeft />}
                label={t("quicklook.previous")}
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
                label={t("quicklook.next")}
                onClick={onNext}
                size="lg"
                tooltipSide="left"
                variant="overlay"
              />
            </div>
          </>
        ) : null}

        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 hidden items-center justify-center gap-4 pb-5 text-xs text-white/60 sm:flex"
        >
          {navigable ? (
            <span className="inline-flex items-center gap-1.5">
              <Kbd className={overlayKbd}>←</Kbd>
              <Kbd className={overlayKbd}>→</Kbd>
              {t("quicklook.hint.navigate")}
            </span>
          ) : null}
          <span className="inline-flex items-center gap-1.5">
            <Kbd className={overlayKbd}>Esc</Kbd>
            {t("quicklook.hint.close")}
          </span>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function QuickLookContent({ item }: { item: QuickLookItem }) {
  const [imageFailed, setImageFailed] = useState(false);

  if (item.kind === "image" && !imageFailed) {
    return (
      <img
        alt={item.name}
        className="max-h-full max-w-full animate-fade-in select-none rounded-lg object-contain shadow-xl"
        draggable={false}
        onError={() => setImageFailed(true)}
        src={previewUrl(item)}
      />
    );
  }

  if (item.kind === "video") {
    return (
      <video
        aria-label={item.name}
        className="max-h-full max-w-full animate-fade-in rounded-lg bg-black shadow-xl"
        controls
        playsInline
        poster={item.posterUrl ?? undefined}
        preload="metadata"
        src={contentUrl(item)}
      />
    );
  }

  if (item.kind === "audio") {
    return (
      <div className="flex w-full max-w-md animate-pop-in flex-col items-center gap-5 rounded-xl border border-line bg-raised p-8 text-center shadow-xl">
        <span aria-hidden="true" className="grid size-16 place-items-center rounded-xl bg-kind-audio-soft text-kind-audio">
          <Music className="size-7" strokeWidth={1.75} />
        </span>
        <p className="max-w-full truncate text-base font-medium text-ink">{item.name}</p>
        <audio aria-label={item.name} className="w-full" controls preload="metadata" src={contentUrl(item)} />
      </div>
    );
  }

  if (item.kind === "pdf" || item.kind === "text") {
    return <DocumentPreview item={item} />;
  }

  return (
    <div className="flex max-w-sm animate-pop-in flex-col items-center rounded-xl border border-line bg-raised px-8 py-10 text-center shadow-xl">
      <FileTypeIcon name={item.name} type="asset" />
      <p className="mt-5 text-lg font-semibold text-ink">{t("quicklook.noPreview.title")}</p>
      <p className="mt-1.5 text-base text-ink-muted">{t("quicklook.noPreview.body")}</p>
      <a
        className="focus-ring mt-6 inline-flex h-9 items-center gap-2 rounded-md bg-accent px-3.5 text-base font-medium text-on-accent shadow-sheen-accent transition-colors duration-150 hover:bg-accent-hover"
        download={item.name}
        href={downloadUrl(item)}
      >
        <Download aria-hidden="true" className="size-4" />
        {t("quicklook.download")}
      </a>
    </div>
  );
}

export type QuickLookProps = {
  actions?: (item: QuickLookItem) => ReactNode;
  controller: QuickLookController;
};

/** Quick Look over a list: arrows walk the list, neighbors' previews are warmed up. */
export function QuickLook({ actions, controller }: QuickLookProps) {
  const { close, index, items, setIndex } = controller;
  const item = index === null ? null : items[index];

  useEffect(() => {
    if (index === null || typeof Image === "undefined") {
      return;
    }

    for (const neighbor of [items[index - 1], items[index + 1]]) {
      if (neighbor?.kind === "image") {
        new Image().src = previewUrl(neighbor);
      }
    }
  }, [index, items]);

  if (!item || index === null) {
    return null;
  }

  return (
    <QuickLookViewer
      actions={actions?.(item)}
      item={item}
      onClose={close}
      onNext={index < items.length - 1 ? () => setIndex(index + 1) : undefined}
      onPrevious={index > 0 ? () => setIndex(index - 1) : undefined}
      position={{ index, total: items.length }}
    />
  );
}

function getFocusable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    (element) => !element.hasAttribute("disabled") && element.tabIndex !== -1,
  );
}

function trapFocus(event: KeyboardEvent, root: HTMLElement) {
  const focusable = getFocusable(root);

  if (focusable.length === 0) {
    event.preventDefault();
    root.focus();
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

function isDocumentLevel(target: Node): boolean {
  return target === document || target === document.body || target === document.documentElement;
}

function isEditable(target: Node | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName));
}

function isInteractive(target: Node | null): boolean {
  return target instanceof HTMLElement && Boolean(target.closest("a[href], button, input, select, textarea, video, audio, iframe, [tabindex='0']"));
}
