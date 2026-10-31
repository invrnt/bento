import { useState } from "react";
import {
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileVideo,
  Folder,
  Play,
  Presentation,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { cx } from "../../lib/cx";
import { getFileTypeKind, type FileTypeKind } from "./fileType";

type FileTypeIconProps = {
  className?: string;
  mimeType?: string;
  name: string;
  previewSrc?: string | null;
  size?: "grid" | "list";
  type: "asset" | "folder";
};

type KindStyle = {
  icon: LucideIcon;
  tile: string;
};

const kindStyles: Record<FileTypeKind, KindStyle> = {
  archive: { icon: FileArchive, tile: "bg-kind-archive-soft text-kind-archive" },
  audio: { icon: FileAudio, tile: "bg-kind-audio-soft text-kind-audio" },
  docx: { icon: FileText, tile: "bg-kind-doc-soft text-kind-doc" },
  folder: { icon: Folder, tile: "bg-kind-folder-soft text-kind-folder" },
  image: { icon: FileImage, tile: "bg-kind-image-soft text-kind-image" },
  other: { icon: File, tile: "bg-kind-text-soft text-kind-text" },
  pdf: { icon: FileText, tile: "bg-kind-pdf-soft text-kind-pdf" },
  presentation: { icon: Presentation, tile: "bg-kind-slides-soft text-kind-slides" },
  spreadsheet: { icon: FileSpreadsheet, tile: "bg-kind-sheet-soft text-kind-sheet" },
  text: { icon: FileCode, tile: "bg-kind-text-soft text-kind-text" },
  video: { icon: FileVideo, tile: "bg-kind-video-soft text-kind-video" },
};

const previewKinds: FileTypeKind[] = ["image", "pdf", "video"];

export function FileTypeIcon({ className, mimeType, name, previewSrc, size = "grid", type }: FileTypeIconProps) {
  const kind = getFileTypeKind(type, name, mimeType);
  const style = kindStyles[kind];
  const Icon = style.icon;
  const [failedPreviewSrc, setFailedPreviewSrc] = useState<string | null>(null);
  const showPreview = previewKinds.includes(kind) && Boolean(previewSrc) && previewSrc !== failedPreviewSrc;
  const grid = size === "grid";

  if (showPreview) {
    return (
      <span
        aria-hidden="true"
        className={cx(
          "relative inline-grid min-h-0 min-w-0 place-items-center overflow-hidden",
          grid ? "h-full w-full rounded-md" : "size-9 rounded-sm",
          className,
        )}
        data-file-type={kind}
      >
        <img
          alt=""
          className={cx("h-full w-full object-cover", kind === "pdf" && "object-top")}
          draggable={false}
          loading="lazy"
          onError={() => setFailedPreviewSrc(previewSrc ?? null)}
          src={previewSrc ?? undefined}
        />
        {kind === "video" ? (
          <span className="absolute grid size-8 place-items-center rounded-full bg-black/45 text-white backdrop-blur-sm">
            <Play className="size-3.5 translate-x-px" fill="currentColor" />
          </span>
        ) : null}
      </span>
    );
  }

  return (
    <span
      aria-hidden="true"
      className={cx(
        "inline-grid shrink-0 place-items-center",
        grid ? "size-14 rounded-lg" : "size-9 rounded-sm",
        style.tile,
        className,
      )}
      data-file-type={kind}
    >
      <Icon
        className={grid ? "size-7" : "size-[1.125rem]"}
        fill={kind === "folder" ? "currentColor" : "none"}
        fillOpacity={kind === "folder" ? 0.22 : undefined}
        strokeWidth={1.75}
      />
    </span>
  );
}
