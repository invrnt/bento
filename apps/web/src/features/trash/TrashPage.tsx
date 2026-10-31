import { useEffect, useMemo, useRef, useState } from "react";
import { ArchiveRestore, MoreHorizontal, Trash2, X } from "lucide-react";

import { absoluteApiPath } from "../../api/client";
import type { TrashItem } from "../../api/trash";
import { Button } from "../../components/Button";
import { CheckboxBox } from "../../components/Checkbox";
import { Dialog } from "../../components/Dialog";
import { IconButton } from "../../components/IconButton";
import { Menu } from "../../components/Menu";
import { PageHeader } from "../../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { showToast } from "../../components/Toast";
import { VirtualList } from "../../components/VirtualList";
import { t } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { formatBytes, formatDay, formatMessage, formatPlural } from "../../lib/format";
import { FileTypeIcon } from "../drive/FileTypeIcon";
import { defaultTrashApi, useTrash } from "./useTrash";
import type { TrashApi } from "./useTrash";

export type TrashPageProps = {
  api?: TrashApi;
  /** Clock used for "se borrará pronto" emphasis; injectable for tests. */
  now?: Date;
};

type Confirmation = { ids: string[]; type: "purge" } | { type: "empty" };

const soonMs = 3 * 24 * 60 * 60 * 1000;

export function TrashPage({ api = defaultTrashApi, now }: TrashPageProps) {
  const trash = useTrash(api);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const items = trash.items;
  const selectedIds = useMemo(() => items.filter((item) => selected.has(item.id)).map((item) => item.id), [items, selected]);
  const allSelected = items.length > 0 && selectedIds.length === items.length;
  const someSelected = selectedIds.length > 0 && !allSelected;
  const totalBytes = useMemo(() => items.reduce((sum, item) => sum + (item.size_bytes || 0), 0), [items]);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function nameOf(ids: string[]) {
    return items.find((item) => item.id === ids[0])?.name ?? "";
  }

  async function restore(ids: string[]) {
    const name = nameOf(ids);
    try {
      await trash.restore(ids);
      setSelected((current) => without(current, ids));
      showToast({
        message: formatPlural(ids.length, { one: "trash.toast.restored.one", other: "trash.toast.restored.other" }, { name }),
        tone: "success",
      });
    } catch {
      showToast({ message: t("trash.toast.failed"), tone: "danger" });
    }
  }

  async function confirm() {
    if (!confirmation) {
      return;
    }

    setBusy(true);
    try {
      if (confirmation.type === "empty") {
        await trash.empty();
        setSelected(new Set());
        showToast({ icon: <Trash2 />, message: t("trash.toast.emptied") });
      } else {
        const name = nameOf(confirmation.ids);
        await trash.purge(confirmation.ids);
        setSelected((current) => without(current, confirmation.ids));
        showToast({
          icon: <Trash2 />,
          message: formatPlural(confirmation.ids.length, { one: "trash.toast.purged.one", other: "trash.toast.purged.other" }, { name }),
        });
      }
      setConfirmation(null);
    } catch {
      showToast({ message: t("trash.toast.failed"), tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function loadMore() {
    if (!(await trash.loadMore())) {
      showToast({ message: t("trash.toast.failed"), tone: "danger" });
    }
  }

  return (
    <section aria-labelledby="trash-title" className="flex flex-1 flex-col gap-5">
      <PageHeader
        actions={
          items.length > 0 ? (
            <Button leadingIcon={<Trash2 />} onClick={() => setConfirmation({ type: "empty" })} variant="danger-ghost">
              {t("trash.emptyAction")}
            </Button>
          ) : null
        }
        description={t("trash.subtitle")}
        title={t("trash.title")}
        titleId="trash-title"
      />

      {trash.status === "loading" ? <LoadingState label={t("trash.loading")} /> : null}
      {trash.status === "error" ? <ErrorState body={t("trash.error")} onRetry={() => void trash.reload()} /> : null}

      {trash.status === "ready" && items.length === 0 ? (
        <EmptyState body={t("trash.emptyState.body")} className="flex-1" icon={<Trash2 />} title={t("trash.emptyState.title")} />
      ) : null}

      {trash.status === "ready" && items.length > 0 ? (
        <>
          <SelectAll
            allSelected={allSelected}
            count={items.length}
            onToggle={() => setSelected(allSelected ? new Set() : new Set(items.map((item) => item.id)))}
            someSelected={someSelected}
            totalBytes={totalBytes}
          />
          <div className="relative min-h-[24rem] flex-1 overflow-hidden rounded-lg border border-line bg-raised shadow-xs">
            <VirtualList
              ariaLabel={t("trash.listLabel")}
              estimateSize={64}
              fill
              getKey={(item) => item.id}
              items={items}
              renderItem={(item) => (
                <TrashRow
                  item={item}
                  now={now}
                  onPurge={() => setConfirmation({ ids: [item.id], type: "purge" })}
                  onRestore={() => void restore([item.id])}
                  onToggle={() => toggle(item.id)}
                  selected={selected.has(item.id)}
                />
              )}
            />
          </div>
          {trash.nextCursor ? (
            <div className="flex justify-center">
              <Button loading={trash.loadingMore} onClick={() => void loadMore()} variant="ghost">
                {t("trash.loadMore")}
              </Button>
            </div>
          ) : null}
        </>
      ) : null}

      {selectedIds.length > 0 ? (
        <section
          aria-label={t("trash.selectionLabel")}
          className="fixed bottom-5 left-1/2 z-30 flex max-w-[calc(100vw-1.5rem)] -translate-x-1/2 animate-slide-up items-center gap-1 rounded-xl border border-line bg-raised p-1.5 pl-4 shadow-lg md:left-[calc(50%+7.5rem)]"
        >
          <span className="whitespace-nowrap text-base font-medium tabular-nums text-ink">
            {formatPlural(selectedIds.length, { one: "trash.selection.one", other: "trash.selection.other" })}
          </span>
          <span aria-hidden="true" className="mx-2 h-5 w-px shrink-0 bg-line" />
          <Button leadingIcon={<ArchiveRestore />} onClick={() => void restore(selectedIds)} size="sm" variant="ghost">
            {t("trash.restore")}
          </Button>
          <Button
            leadingIcon={<Trash2 />}
            onClick={() => setConfirmation({ ids: selectedIds, type: "purge" })}
            size="sm"
            variant="danger-ghost"
          >
            {t("trash.purge")}
          </Button>
          <IconButton icon={<X />} label={t("trash.clearSelection")} onClick={() => setSelected(new Set())} />
        </section>
      ) : null}

      <Dialog
        actions={
          <>
            <Button onClick={() => setConfirmation(null)} variant="ghost">
              {t("trash.cancel")}
            </Button>
            <Button data-autofocus leadingIcon={<Trash2 />} loading={busy} onClick={() => void confirm()} variant="danger">
              {confirmation?.type === "empty" ? t("trash.emptyAction") : t("trash.purge")}
            </Button>
          </>
        }
        description={
          confirmation?.type === "purge"
            ? confirmation.ids.length === 1
              ? nameOf(confirmation.ids)
              : formatPlural(confirmation.ids.length, { one: "trash.count.one", other: "trash.count.other" })
            : formatPlural(items.length, { one: "trash.count.one", other: "trash.count.other" })
        }
        icon={<Trash2 />}
        onOpenChange={(open) => {
          if (!open && !busy) {
            setConfirmation(null);
          }
        }}
        open={confirmation !== null}
        title={confirmation?.type === "empty" ? t("trash.emptyDialog.title") : t("trash.purgeDialog.title")}
        tone="danger"
      >
        <p>{confirmation?.type === "empty" ? t("trash.emptyDialog.body") : t("trash.purgeDialog.body")}</p>
      </Dialog>
    </section>
  );
}

function SelectAll({
  allSelected,
  count,
  onToggle,
  someSelected,
  totalBytes,
}: {
  allSelected: boolean;
  count: number;
  onToggle: () => void;
  someSelected: boolean;
  totalBytes: number;
}) {
  const ref = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.indeterminate = someSelected;
    }
  }, [someSelected]);

  return (
    <div className="-mb-2 flex h-8 items-center justify-between gap-3 px-3">
      <label className="inline-flex cursor-pointer select-none items-center gap-2.5 text-sm font-medium text-ink-muted transition-colors hover:text-ink">
        <CheckboxBox aria-label={t("trash.selectAll")} checked={allSelected} onChange={onToggle} ref={ref} />
        <span>{t("trash.selectAll")}</span>
      </label>
      <span className="text-sm tabular-nums text-ink-subtle">
        {[formatPlural(count, { one: "trash.count.one", other: "trash.count.other" }), formatBytes(totalBytes)].filter(Boolean).join(" · ")}
      </span>
    </div>
  );
}

function TrashRow({
  item,
  now,
  onPurge,
  onRestore,
  onToggle,
  selected,
}: {
  item: TrashItem;
  now?: Date;
  onPurge: () => void;
  onRestore: () => void;
  onToggle: () => void;
  selected: boolean;
}) {
  const purgeTime = new Date(item.purge_at).getTime();
  const purgeSoon = Number.isFinite(purgeTime) && purgeTime - (now ?? new Date()).getTime() < soonMs;
  const purgeText = formatMessage("trash.purgeOn", { date: formatDay(item.purge_at, now) });
  const meta = [
    item.type === "folder" ? t("drive.item.folder") : formatBytes(item.size_bytes),
    formatMessage("trash.deletedOn", { date: formatDay(item.deleted_at, now) }),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <article
      className={cx(
        "grid h-full grid-cols-[1rem_2.25rem_minmax(0,1fr)_auto] items-center gap-3 border-b border-line px-3 transition-colors duration-150 sm:grid-cols-[1rem_2.25rem_minmax(0,1fr)_12rem_auto]",
        selected ? "bg-accent-soft" : "hover:bg-hover",
      )}
    >
      <CheckboxBox
        aria-label={formatMessage(selected ? "trash.unselect" : "trash.select", { name: item.name })}
        checked={selected}
        onChange={onToggle}
      />
      <FileTypeIcon
        name={item.name}
        previewSrc={item.thumbnail_url ? absoluteApiPath(item.thumbnail_url) : null}
        size="list"
        type={item.type === "folder" ? "folder" : "asset"}
      />
      <div className="grid min-w-0 gap-0.5">
        <span className="truncate text-base font-medium text-ink">{item.name}</span>
        <span className="truncate text-xs tabular-nums text-ink-subtle">
          {meta}
          <span className="sm:hidden"> · {purgeText}</span>
        </span>
      </div>
      <span className={cx("hidden truncate text-sm sm:block", purgeSoon ? "font-medium text-warning-ink" : "text-ink-muted")}>{purgeText}</span>
      <div className="flex items-center gap-1">
        <Button
          aria-label={formatMessage("trash.restoreItem", { name: item.name })}
          className="max-sm:px-2"
          leadingIcon={<ArchiveRestore />}
          onClick={onRestore}
          size="sm"
          variant="ghost"
        >
          <span className="hidden sm:inline">{t("trash.restore")}</span>
        </Button>
        <Menu
          items={[
            { icon: <ArchiveRestore />, id: "restore", label: t("trash.restore"), onSelect: onRestore },
            { icon: <Trash2 />, id: "purge", label: t("trash.purge"), onSelect: onPurge, separatorBefore: true, tone: "danger" },
          ]}
          label={formatMessage("trash.actions", { name: item.name })}
          trigger={<MoreHorizontal aria-hidden="true" />}
          triggerVariant="ghost"
        />
      </div>
    </article>
  );
}

function without(set: Set<string>, ids: string[]): Set<string> {
  const next = new Set(set);
  for (const id of ids) {
    next.delete(id);
  }
  return next;
}
