import type { DriveApi } from "../../api/drive";
import { settleDeletes } from "../trash/undoableDelete";
import type { DriveEntry } from "./driveModel";

/** Moves entries to trash one by one and reports which ids moved (for a partial-failure undo). */
export function trashDriveEntries(api: DriveApi, entries: DriveEntry[]): Promise<{ failed: number; trashedIds: string[] }> {
  const byId = new Map(entries.map((entry) => [entry.id, entry]));

  return settleDeletes(Array.from(byId.keys()), (id) => (byId.get(id)?.kind === "folder" ? api.deleteFolder(id) : api.deleteAsset(id)));
}

export async function moveDriveEntries(api: DriveApi, entries: DriveEntry[], targetFolderId: string | null): Promise<void> {
  await Promise.all(
    entries.map((entry) =>
      entry.kind === "folder"
        ? api.moveFolder({ folderId: entry.id, parentId: targetFolderId })
        : api.moveAsset({ assetId: entry.id, folderId: targetFolderId }),
    ),
  );
}

export function downloadableDriveEntries(entries: DriveEntry[]): DriveEntry[] {
  return entries.filter((entry) => entry.kind === "asset");
}

export function downloadDriveEntries(api: DriveApi, entries: DriveEntry[], open: (url: string) => void): void {
  for (const entry of downloadableDriveEntries(entries)) {
    open(api.downloadUrl(entry.id));
  }
}
