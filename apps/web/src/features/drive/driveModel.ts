import { absoluteApiPath } from "../../api/drive";
import type { DriveAsset, DriveFolder, DriveItem, DriveSearchItem } from "../../api/drive";

export type DriveEntryKind = "asset" | "folder";

export type DriveEntry = {
  asset?: DriveAsset;
  folder?: DriveFolder;
  id: string;
  kind: DriveEntryKind;
  mimeType?: string;
  name: string;
  processingState?: string | null;
  reason?: string;
  sizeBytes?: number;
  thumbnailUrl?: string | null;
  updatedAt: string;
};

export function entryFromItem(item: DriveItem): DriveEntry {
  if (item.type === "folder") {
    const folder = item.folder;

    return {
      folder,
      id: folder.id,
      kind: "folder",
      name: folder.name,
      updatedAt: folder.updated_at,
    };
  }

  const asset = item.asset;

  return {
    asset,
    id: asset.id,
    kind: "asset",
    mimeType: asset.mime_type,
    name: asset.filename,
    processingState: asset.processing_state,
    sizeBytes: asset.size_bytes,
    thumbnailUrl:
      asset.thumbnail_url && asset.processing_state !== "thumbnail_pending"
        ? absoluteApiPath(asset.thumbnail_url)
        : null,
    updatedAt: asset.updated_at,
  };
}

export function entryFromSearchItem(item: DriveSearchItem): DriveEntry {
  if (item.type === "folder") {
    return {
      id: item.id,
      kind: "folder",
      name: item.title,
      processingState: item.processing_state,
      reason: item.reason,
      thumbnailUrl: item.thumbnail_url,
      updatedAt: "",
    };
  }

  return {
    id: item.asset_id ?? item.id,
    kind: "asset",
    name: item.title,
    processingState: item.processing_state,
    reason: item.reason,
    thumbnailUrl: item.thumbnail_url ? absoluteApiPath(item.thumbnail_url) : null,
    updatedAt: "",
  };
}

export function isIndexingState(state: string | null | undefined): boolean {
  return Boolean(
    state &&
      !["indexed", "failed", "failed_partial"].includes(state) &&
      (state.endsWith("_pending") || state === "created" || state === "blob_stored" || state === "metadata_extracted"),
  );
}

export function isPartialFailureState(state: string | null | undefined): boolean {
  return state === "failed_partial";
}

/** Sizes use the shared, locale-aware formatter. */
export { formatBytes } from "../../lib/format";
