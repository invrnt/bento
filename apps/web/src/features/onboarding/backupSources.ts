import { Download, FileText, Folder, Images, Monitor } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { BackupSuggestion } from "../../api/backup";
import type { MessageKey } from "../../i18n/dictionary";
import { apiErrorBody } from "./apiErrors";

const kindIcons: Record<BackupSuggestion["kind"], LucideIcon> = {
  desktop: Monitor,
  documents: FileText,
  downloads: Download,
  pictures: Images,
};

export function backupKindIcon(kind: BackupSuggestion["kind"] | null | undefined): LucideIcon {
  return (kind && kindIcons[kind]) || Folder;
}

const reasonKeys: Array<[RegExp, MessageKey]> = [
  [/root/, "backup.error.root"],
  [/data|bento/, "backup.error.dataDir"],
  [/duplicate|overlap|exists|nested|inside/, "backup.error.overlap"],
  [/missing|not_found|not_exist|not_dir|directory/, "backup.error.missing"],
  [/read|permission|access/, "backup.error.unreadable"],
];

/** Human message for a rejected folder (`backup_source_invalid` with `details.reason`). */
export function backupErrorKey(error: unknown): MessageKey {
  const body = apiErrorBody(error);
  const reason = String(body?.details?.reason ?? body?.code ?? "").toLowerCase();
  return reasonKeys.find(([pattern]) => pattern.test(reason))?.[1] ?? "backup.error.generic";
}

/** Folder name to use as a label for a typed or picked path. */
export function folderLabel(path: string): string {
  const parts = path.replace(/[\\/]+$/, "").split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? path;
}
