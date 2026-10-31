import { Trash2 } from "lucide-react";

import { restoreTrash } from "../../api/trash";
import { showToast } from "../../components/Toast";
import { t } from "../../i18n/dictionary";
import { formatPlural } from "../../lib/format";

export type UndoableDeleteOptions = {
  /** Called after the delete and again after an undo, to refresh the visible list. */
  onChange?: () => unknown;
  /** Moves the items to trash and resolves with the ids that actually moved. */
  perform: () => Promise<{ failed: number; trashedIds: string[] }>;
  restore?: (ids: string[]) => Promise<unknown>;
};

/**
 * Reversible delete: moves items to trash at once (no confirmation) and shows
 * "Movido a la papelera · Deshacer". Undo restores them from trash.
 */
export async function deleteWithUndo({ onChange, perform, restore = restoreTrash }: UndoableDeleteOptions): Promise<boolean> {
  let result: { failed: number; trashedIds: string[] };
  try {
    result = await perform();
  } catch {
    showToast({ message: t("trash.toast.moveFailed"), tone: "danger" });
    return false;
  }

  const { failed, trashedIds } = result;
  if (trashedIds.length > 0) {
    await onChange?.();
    showToast({
      action: {
        label: t("trash.toast.undo"),
        onAction: async () => {
          try {
            await restore(trashedIds);
            await onChange?.();
            showToast({ message: t("trash.toast.undone"), tone: "success" });
          } catch {
            showToast({ message: t("trash.toast.restoreFailed"), tone: "danger" });
          }
        },
        undo: true,
      },
      icon: <Trash2 />,
      message: formatPlural(trashedIds.length, { one: "trash.toast.moved.one", other: "trash.toast.moved.other" }),
    });
  }

  if (failed > 0) {
    showToast({
      message:
        trashedIds.length === 0
          ? t("trash.toast.moveFailed")
          : formatPlural(failed, { one: "trash.toast.moveFailedSome.one", other: "trash.toast.moveFailedSome.other" }),
      tone: "danger",
    });
  }

  return trashedIds.length > 0;
}

/** Runs one delete per id and reports which ones moved, so a partial failure stays undoable. */
export async function settleDeletes(ids: string[], remove: (id: string) => Promise<unknown>) {
  const results = await Promise.allSettled(ids.map((id) => remove(id)));
  const trashedIds = ids.filter((_, index) => results[index].status === "fulfilled");
  return { failed: ids.length - trashedIds.length, trashedIds };
}
