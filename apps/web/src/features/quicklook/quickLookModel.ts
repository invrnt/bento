import { useState } from "react";
import type { KeyboardEvent } from "react";

import { absoluteApiPath } from "../../api/client";
import { assetContentPath } from "../../api/telegram";
import type { MessageKey } from "../../i18n/dictionary";
import { getFileTypeKind } from "../drive/fileType";

export type QuickLookKind = "image" | "video" | "audio" | "pdf" | "text" | "other";

export type QuickLookItem = {
  /** Attachment URL; defaults to `/assets/{id}/download`. */
  downloadUrl?: string;
  id: string;
  kind: QuickLookKind;
  name: string;
  /** Video poster (a thumbnail, never the original). */
  posterUrl?: string | null;
  /** Image preview; defaults to `/assets/{id}/preview`. Originals are never used for images. */
  previewUrl?: string | null;
  sizeBytes?: number | null;
};

export const quickLookKindLabels: Record<QuickLookKind, MessageKey> = {
  audio: "drive.kind.audio",
  image: "drive.kind.image",
  other: "drive.kind.other",
  pdf: "drive.kind.pdf",
  text: "drive.kind.text",
  video: "drive.kind.video",
};

export function quickLookKind(name: string, mimeType?: string | null): QuickLookKind {
  const kind = getFileTypeKind("asset", name, mimeType ?? undefined);
  return kind === "image" || kind === "video" || kind === "audio" || kind === "pdf" || kind === "text" ? kind : "other";
}

/** Decrypted, range-capable stream used for video, audio, PDF and text. */
export function contentUrl(item: Pick<QuickLookItem, "id">): string {
  return absoluteApiPath(assetContentPath(item.id));
}

export function previewUrl(item: Pick<QuickLookItem, "id" | "previewUrl">): string {
  return item.previewUrl ?? absoluteApiPath(`/api/assets/${encodeURIComponent(item.id)}/preview`);
}

export function downloadUrl(item: Pick<QuickLookItem, "downloadUrl" | "id">): string {
  return item.downloadUrl ?? absoluteApiPath(`/api/assets/${encodeURIComponent(item.id)}/download`);
}

export type QuickLookController = {
  close: () => void;
  index: number | null;
  items: QuickLookItem[];
  open: (id: string) => void;
  setIndex: (index: number) => void;
};

/** Tracks the open item by id, so reloading or shrinking the list never shows the wrong file. */
export function useQuickLook(items: QuickLookItem[]): QuickLookController {
  const [openId, setOpenId] = useState<string | null>(null);
  const found = openId === null ? -1 : items.findIndex((item) => item.id === openId);

  return {
    close: () => setOpenId(null),
    index: found >= 0 ? found : null,
    items,
    open: (id) => setOpenId(id),
    setIndex: (index) => {
      const item = items[index];
      if (item) {
        setOpenId(item.id);
      }
    },
  };
}

/** Space opens Quick Look on a focused item. Prevents the native button click that would follow. */
export function quickLookKeyHandlers(open: () => void) {
  return {
    onKeyDown(event: KeyboardEvent<HTMLElement>) {
      if (event.key === " " && !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
        event.preventDefault();
        if (!event.repeat) {
          open();
        }
      }
    },
    onKeyUp(event: KeyboardEvent<HTMLElement>) {
      if (event.key === " ") {
        event.preventDefault();
      }
    },
  };
}
