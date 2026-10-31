import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent, FormEvent, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  CornerDownLeft,
  Download,
  Eye,
  FolderInput,
  FolderOpen,
  FolderPlus,
  FolderUp,
  HardDrive,
  LayoutGrid,
  List,
  MoreHorizontal,
  PencilLine,
  Search,
  SearchX,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import type { DriveApi, DriveBreadcrumb } from "../../api/drive";
import { driveApi } from "../../api/drive";
import { Badge } from "../../components/Badge";
import { Breadcrumb } from "../../components/Breadcrumb";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { CheckboxBox } from "../../components/Checkbox";
import { Dialog } from "../../components/Dialog";
import { IconButton } from "../../components/IconButton";
import { Input } from "../../components/Input";
import { Menu } from "../../components/Menu";
import type { MenuItem } from "../../components/Menu";
import { PageHeader } from "../../components/PageHeader";
import { ProgressBar } from "../../components/ProgressBar";
import { SegmentedControl } from "../../components/SegmentedControl";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { VirtualGrid } from "../../components/VirtualGrid";
import { VirtualList } from "../../components/VirtualList";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "../../components/ui/context-menu";
import { cx } from "../../lib/cx";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { entryFromItem, entryFromSearchItem, formatBytes, isIndexingState, isPartialFailureState } from "./driveModel";
import type { DriveEntry } from "./driveModel";
import { FileTypeIcon } from "./FileTypeIcon";
import { getFileTypeKind } from "./fileType";
import type { FileTypeKind } from "./fileType";
import { FolderTree } from "./FolderTree";
import { selectionFromDataTransfer, selectionFromFiles, uploadSelection } from "./folderUpload";
import type { UploadProgress, UploadSummary } from "./folderUpload";
import { deleteDriveEntries, downloadDriveEntries, downloadableDriveEntries, moveDriveEntries } from "./bulkOperations";
import { useDriveItems, useDriveSearch } from "./useDriveQueries";

type LayoutMode = "grid" | "list";

type PendingAction =
  | { type: "create-folder" }
  | { entries: DriveEntry[]; type: "bulk-delete" }
  | { entries: DriveEntry[]; type: "bulk-move" }
  | { entry: DriveEntry; type: "delete" }
  | { entry: DriveEntry; type: "move" }
  | { entry: DriveEntry; type: "rename" }
  | { entry: DriveEntry; type: "preview" };

const kindLabels: Record<FileTypeKind, MessageKey> = {
  archive: "drive.kind.archive",
  audio: "drive.kind.audio",
  docx: "drive.kind.docx",
  folder: "drive.kind.folder",
  image: "drive.kind.image",
  other: "drive.kind.other",
  pdf: "drive.kind.pdf",
  presentation: "drive.kind.presentation",
  spreadsheet: "drive.kind.spreadsheet",
  text: "drive.kind.text",
  video: "drive.kind.video",
};

const listColumns =
  "grid-cols-[1rem_minmax(0,1fr)_2rem] sm:grid-cols-[1rem_minmax(0,1fr)_8.5rem_5.5rem_2rem] lg:grid-cols-[1rem_minmax(0,1fr)_8.5rem_5.5rem_8rem_2rem]";

export type DriveBrowserProps = {
  api?: DriveApi;
  initialFolderId?: string | null;
  onNavigate?: (folderId: string | null) => void;
};

export function DriveBrowser({ api = driveApi, initialFolderId = null, onNavigate }: DriveBrowserProps) {
  const [folderId, setFolderId] = useState<string | null>(initialFolderId);
  const [layout, setLayout] = useState<LayoutMode>("grid");
  const [reloadKey, setReloadKey] = useState(0);
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [uploadSummary, setUploadSummary] = useState<UploadSummary | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [dialogValue, setDialogValue] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const dragDepthRef = useRef(0);
  const uploading = uploadProgress !== null;

  const itemsState = useDriveItems(api, folderId, reloadKey);
  const searchState = useDriveSearch(api, folderId, submittedQuery, reloadKey);
  const entries = useMemo(() => (itemsState.data?.items ?? []).map(entryFromItem), [itemsState.data]);
  const searchEntries = useMemo(() => (searchState.data?.items ?? []).map(entryFromSearchItem), [searchState.data]);
  const showingSearch = submittedQuery.trim().length > 0;
  const visibleEntries = showingSearch ? searchEntries : entries;
  const selectedEntries = useMemo(
    () => visibleEntries.filter((entry) => selectedKeys.has(entryKey(entry))),
    [selectedKeys, visibleEntries],
  );
  const downloadableEntries = useMemo(() => downloadableDriveEntries(selectedEntries), [selectedEntries]);
  const allVisibleSelected = visibleEntries.length > 0 && selectedEntries.length === visibleEntries.length;
  const someVisibleSelected = selectedEntries.length > 0 && !allVisibleSelected;
  const selectionMode = selectedEntries.length > 0;
  const canSubmitSearch = query.trim().length > 0 && query.trim() !== submittedQuery.trim();
  const breadcrumbs = useMemo(
    () => normalizeBreadcrumbs(itemsState.data?.breadcrumbs, folderId),
    [folderId, itemsState.data?.breadcrumbs],
  );

  const closeAction = useCallback((open: boolean) => {
    if (!open) {
      setPendingAction(null);
      setActionError(null);
    }
  }, []);

  function navigate(nextFolderId: string | null) {
    setFolderId(nextFolderId);
    setSubmittedQuery("");
    setQuery("");
    setSelectedKeys(new Set());
    onNavigate?.(nextFolderId);
  }

  function toggleSelection(entry: DriveEntry) {
    setSelectedKeys((current) => {
      const next = new Set(current);
      const key = entryKey(entry);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function toggleAllVisible() {
    setSelectedKeys(allVisibleSelected ? new Set() : new Set(visibleEntries.map(entryKey)));
  }

  function clearSelection() {
    setSelectedKeys(new Set());
  }

  function submitSearch() {
    clearSelection();
    setSubmittedQuery(query);
  }

  function clearSearch() {
    setQuery("");
    setSubmittedQuery("");
    clearSelection();
  }

  async function reload() {
    setReloadKey((current) => current + 1);
    await itemsState.refetch();
    if (submittedQuery) {
      await searchState.refetch();
    }
  }

  async function startUpload(selection: ReturnType<typeof selectionFromFiles>) {
    if (selection.files.length === 0 && selection.directories.length === 0) {
      return;
    }

    setUploadSummary(null);
    setUploadError(null);
    setUploadProgress({
      completedFiles: 0,
      currentPath: null,
      phase: "preparing",
      totalDirectories: selection.directories.length,
      totalFiles: selection.files.length,
    });
    try {
      const summary = await uploadSelection({
        api,
        destinationFolderId: folderId,
        onProgress: setUploadProgress,
        selection,
      });
      setUploadSummary(summary);
      await reload();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : t("drive.error.action"));
    } finally {
      setUploadProgress(null);
    }
  }

  async function onDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    dragDepthRef.current = 0;
    setDragActive(false);
    setUploadError(null);
    try {
      const selection = await selectionFromDataTransfer(event.dataTransfer);
      await startUpload(selection);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : t("drive.upload.readError"));
    }
  }

  function openAction(action: PendingAction) {
    setPendingAction(action);
    setActionError(null);
    if (action.type === "rename") {
      setDialogValue(action.entry.name);
    } else {
      setDialogValue("");
    }
  }

  async function submitAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!pendingAction) {
      return;
    }

    const value = dialogValue.trim();
    setActionError(null);

    try {
      if (pendingAction.type === "rename") {
        if (!value) {
          setActionError(t("drive.validation.nameRequired"));
          return;
        }
        if (pendingAction.entry.kind === "folder") {
          await api.renameFolder({ folderId: pendingAction.entry.id, name: value });
        } else {
          await api.renameAsset({ assetId: pendingAction.entry.id, name: value });
        }
      }

      if (pendingAction.type === "create-folder") {
        if (!value) {
          setActionError(t("drive.validation.nameRequired"));
          return;
        }
        await api.createFolder({ name: value, parentId: folderId });
      }

      if (pendingAction.type === "move") {
        const targetId = value || null;
        if (pendingAction.entry.kind === "folder") {
          await api.moveFolder({ folderId: pendingAction.entry.id, parentId: targetId });
        } else {
          await api.moveAsset({ assetId: pendingAction.entry.id, folderId: targetId });
        }
      }

      if (pendingAction.type === "delete") {
        if (pendingAction.entry.kind === "folder") {
          await api.deleteFolder(pendingAction.entry.id);
        } else {
          await api.deleteAsset(pendingAction.entry.id);
        }
      }

      if (pendingAction.type === "bulk-move") {
        await moveDriveEntries(api, pendingAction.entries, value || null);
        clearSelection();
      }

      if (pendingAction.type === "bulk-delete") {
        await deleteDriveEntries(api, pendingAction.entries);
        clearSelection();
      }

      setPendingAction(null);
      await reload();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : t("drive.error.action"));
    }
  }

  const uploadButtons = (
    <>
      <Button
        disabled={uploading}
        leadingIcon={<FolderUp />}
        onClick={() => folderInputRef.current?.click()}
        variant="secondary"
      >
        {t("drive.upload.pickFolder")}
      </Button>
      <Button disabled={uploading} leadingIcon={<Upload />} onClick={() => fileInputRef.current?.click()} variant="primary">
        {t("drive.upload.pick")}
      </Button>
    </>
  );

  return (
    <section
      aria-labelledby="drive-title"
      className="relative flex flex-1 flex-col gap-5"
      onDragLeave={(event) => {
        event.preventDefault();
        dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
        if (dragDepthRef.current === 0) {
          setDragActive(false);
        }
      }}
      onDragEnter={(event) => {
        event.preventDefault();
        dragDepthRef.current += 1;
        setDragActive(true);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={(event) => void onDrop(event)}
    >
      {dragActive ? <DropOverlay /> : null}

      <PageHeader
        actions={uploadButtons}
        description={
          <Breadcrumb
            className="-ml-1.5"
            items={breadcrumbs.map((item) => ({
              current: item.folder_id === folderId,
              href: item.folder_id ? `/drive/folders/${item.folder_id}` : "/drive",
              icon: item.folder_id === null ? <HardDrive /> : undefined,
              label: item.name,
              onNavigate: () => navigate(item.folder_id),
            }))}
            label={t("drive.breadcrumb.label")}
          />
        }
        title={t("drive.title")}
        titleId="drive-title"
      >
        <div className="flex flex-wrap items-center gap-2">
          <form
            className="min-w-0 max-w-md flex-1 basis-64"
            onSubmit={(event) => {
              event.preventDefault();
              submitSearch();
            }}
            role="search"
          >
            <Input
              hideLabel
              label={t("drive.search.label")}
              leadingIcon={<Search />}
              onChange={(event) => setQuery(event.currentTarget.value)}
              onKeyDown={(event: ReactKeyboardEvent<HTMLInputElement>) => {
                if (event.key === "Escape" && (query || showingSearch)) {
                  event.preventDefault();
                  clearSearch();
                }
              }}
              placeholder={t("drive.search.placeholder")}
              trailing={
                canSubmitSearch ? (
                  <IconButton icon={<CornerDownLeft />} label={t("drive.search.submit")} onClick={submitSearch} size="sm" />
                ) : showingSearch ? (
                  <IconButton icon={<X />} label={t("drive.search.clear")} onClick={clearSearch} size="sm" />
                ) : null
              }
              type="search"
              value={query}
            />
          </form>
          <div className="ml-auto flex items-center gap-2">
            <Button
              leadingIcon={<FolderPlus />}
              onClick={() => {
                setDialogValue("");
                setPendingAction({ type: "create-folder" });
              }}
              variant="ghost"
            >
              {t("drive.folder.new")}
            </Button>
            <SegmentedControl
              ariaLabel={t("drive.layout.label")}
              iconOnly
              onChange={setLayout}
              options={[
                { icon: <LayoutGrid />, label: t("drive.layout.grid"), value: "grid" },
                { icon: <List />, label: t("drive.layout.list"), value: "list" },
              ]}
              value={layout}
            />
          </div>
        </div>
      </PageHeader>

      <input
        aria-hidden="true"
        className="hidden"
        data-testid="drive-file-input"
        disabled={uploading}
        multiple
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = "";
          void startUpload(selectionFromFiles(files));
        }}
        ref={fileInputRef}
        tabIndex={-1}
        type="file"
      />
      <input
        aria-hidden="true"
        className="hidden"
        data-testid="drive-folder-input"
        disabled={uploading}
        multiple
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = "";
          void startUpload(selectionFromFiles(files));
        }}
        ref={(element) => {
          folderInputRef.current = element;
          element?.setAttribute("webkitdirectory", "");
          element?.setAttribute("directory", "");
        }}
        tabIndex={-1}
        type="file"
      />

      <div className="flex min-h-0 flex-1 gap-5">
        <FolderTree
          api={api}
          breadcrumbs={breadcrumbs}
          currentFolderId={folderId}
          onNavigate={navigate}
          reloadKey={reloadKey}
        />

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          {itemsState.loading && !itemsState.data ? <LoadingState label={t("drive.loading")} /> : null}
          {itemsState.error ? (
            <ErrorState body={itemsState.error.message} onRetry={() => void itemsState.refetch()} title={t("drive.error.title")} />
          ) : null}
          {searchState.loading ? <LoadingState label={t("drive.search.loading")} /> : null}
          {searchState.error ? (
            <ErrorState
              body={searchState.error.message}
              onRetry={() => void searchState.refetch()}
              title={t("drive.error.title")}
            />
          ) : null}

          {!itemsState.loading && !itemsState.error && visibleEntries.length === 0 ? (
            <EmptyState
              action={
                showingSearch ? (
                  <Button leadingIcon={<X />} onClick={clearSearch}>
                    {t("drive.search.clear")}
                  </Button>
                ) : (
                  uploadButtons
                )
              }
              body={showingSearch ? t("drive.empty.searchBody") : t("drive.empty.body")}
              className="flex-1"
              icon={showingSearch ? <SearchX /> : <FolderOpen />}
              title={showingSearch ? t("drive.empty.searchTitle") : t("drive.empty.title")}
            />
          ) : null}

          {visibleEntries.length > 0 ? (
            <>
              <SelectAllBar
                allVisibleSelected={allVisibleSelected}
                count={visibleEntries.length}
                onToggleAll={toggleAllVisible}
                someVisibleSelected={someVisibleSelected}
              />
              {layout === "list" ? <ListHeader /> : null}
              <div className="relative min-h-[26rem] flex-1">
                {layout === "grid" ? (
                  <VirtualGrid
                    fill
                    gap={12}
                    getKey={(entry) => `${entry.kind}-${entry.id}`}
                    items={visibleEntries}
                    minColumnWidth={168}
                    renderItem={(entry) => (
                      <DriveGridCard
                        api={api}
                        entry={entry}
                        onNavigate={navigate}
                        onOpenAction={openAction}
                        onToggleSelection={toggleSelection}
                        searchMode={showingSearch}
                        selected={selectedKeys.has(entryKey(entry))}
                        selectionMode={selectionMode}
                      />
                    )}
                    rowHeight={204}
                  />
                ) : (
                  <VirtualList
                    estimateSize={56}
                    fill
                    getKey={(entry) => `${entry.kind}-${entry.id}`}
                    items={visibleEntries}
                    renderItem={(entry) => (
                      <DriveListRow
                        api={api}
                        entry={entry}
                        onNavigate={navigate}
                        onOpenAction={openAction}
                        onToggleSelection={toggleSelection}
                        searchMode={showingSearch}
                        selected={selectedKeys.has(entryKey(entry))}
                        selectionMode={selectionMode}
                      />
                    )}
                  />
                )}
              </div>
            </>
          ) : null}
        </div>
      </div>

      {selectionMode ? (
        <SelectionBar
          downloadableCount={downloadableEntries.length}
          onBulkDelete={() => openAction({ entries: selectedEntries, type: "bulk-delete" })}
          onBulkDownload={() => downloadDriveEntries(api, selectedEntries, openInNewTab)}
          onBulkMove={() => openAction({ entries: selectedEntries, type: "bulk-move" })}
          onClear={clearSelection}
          selectedCount={selectedEntries.length}
        />
      ) : null}

      <UploadStatusPanel
        error={uploadError}
        onDismiss={() => {
          setUploadError(null);
          setUploadSummary(null);
        }}
        progress={uploadProgress}
        summary={uploadSummary}
      />

      <ActionDialog
        action={pendingAction}
        api={api}
        error={actionError}
        onOpenChange={closeAction}
        onSubmit={submitAction}
        setValue={setDialogValue}
        value={dialogValue}
      />
    </section>
  );
}

function DropOverlay() {
  return (
    <div
      aria-live="assertive"
      className="pointer-events-none absolute inset-0 z-40 grid animate-fade-in place-items-center rounded-xl border-2 border-dashed border-accent bg-accent-soft/90 p-8 text-center backdrop-blur-sm"
      role="status"
    >
      <div className="flex max-w-sm animate-pop-in flex-col items-center">
        <span className="grid size-16 place-items-center rounded-xl bg-accent text-on-accent shadow-lg">
          <Upload aria-hidden="true" className="size-7" />
        </span>
        <p className="mt-5 text-xl font-semibold tracking-tight text-ink">{t("drive.upload.dropTitle")}</p>
        <p className="mt-1.5 text-base text-ink-muted">{t("drive.upload.dropBody")}</p>
      </div>
    </div>
  );
}

function UploadStatusPanel({
  error,
  onDismiss,
  progress,
  summary,
}: {
  error: string | null;
  onDismiss: () => void;
  progress: UploadProgress | null;
  summary: UploadSummary | null;
}) {
  if (!progress && !summary && !error) {
    return null;
  }

  const percent = progress
    ? progress.phase === "preparing"
      ? 8
      : progress.totalFiles > 0
        ? Math.round((progress.completedFiles / progress.totalFiles) * 100)
        : 100
    : 100;
  const failed = Boolean(error || summary?.failures.length);
  const title = progress
    ? progress.phase === "preparing"
      ? t("drive.upload.preparing")
      : t("drive.upload.uploading")
    : error
      ? t("drive.upload.failed")
      : t("drive.upload.complete");

  return (
    <section
      aria-live="polite"
      className="fixed inset-x-3 bottom-3 z-30 animate-slide-up rounded-xl border border-line bg-raised p-4 shadow-lg sm:inset-x-auto sm:bottom-5 sm:right-5 sm:w-80"
      role={error ? "alert" : "status"}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className={cx(
            "grid size-8 shrink-0 place-items-center rounded-md [&_svg]:size-4",
            failed ? "bg-danger-soft text-danger-ink" : progress ? "bg-accent-soft text-accent-ink" : "bg-success-soft text-success-ink",
          )}
        >
          <Upload />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <h2 className="truncate text-base font-semibold text-ink">{title}</h2>
            {progress ? <span className="text-sm font-medium tabular-nums text-accent-ink">{percent}%</span> : null}
          </div>
          {progress ? (
            <>
              <ProgressBar className="mt-2.5" label={t("drive.upload.progressLabel")} value={percent} />
              <p className="mt-2 truncate font-mono text-xs text-ink-subtle">
                {progress.phase === "preparing"
                  ? `${progress.totalDirectories} ${t("drive.upload.foldersToCreate")}`
                  : `${progress.completedFiles} ${t("drive.upload.of")} ${progress.totalFiles} · ${progress.currentPath ?? ""}`}
              </p>
            </>
          ) : null}
          {summary ? (
            <p className="mt-1 text-sm text-ink-muted">
              {summary.uploaded} {t("drive.upload.uploadedCount")} · {summary.skippedDuplicates} {t("drive.upload.duplicateCount")} ·{" "}
              {summary.failures.length} {t("drive.upload.failedCount")}
            </p>
          ) : null}
          {error ? <p className="mt-1 text-sm text-danger-ink">{error}</p> : null}
          {summary?.failures.slice(0, 3).map((failure) => (
            <p className="mt-1 truncate font-mono text-xs text-danger-ink" key={failure.relativePath}>
              {failure.relativePath}: {failure.error.message}
            </p>
          ))}
        </div>
        {!progress ? (
          <IconButton className="-mr-1.5 -mt-1" icon={<X />} label={t("common.close")} onClick={onDismiss} size="sm" />
        ) : null}
      </div>
    </section>
  );
}

function SelectAllBar({
  allVisibleSelected,
  count,
  onToggleAll,
  someVisibleSelected,
}: {
  allVisibleSelected: boolean;
  count: number;
  onToggleAll: () => void;
  someVisibleSelected: boolean;
}) {
  const selectAllRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected]);

  return (
    <div className="flex h-8 items-center justify-between gap-3 px-3">
      <label className="inline-flex cursor-pointer select-none items-center gap-2.5 text-sm font-medium text-ink-muted transition-colors hover:text-ink">
        <CheckboxBox
          aria-label={t("drive.selection.all")}
          checked={allVisibleSelected}
          onChange={onToggleAll}
          ref={selectAllRef}
        />
        <span>{t("drive.selection.all")}</span>
      </label>
      <span className="text-sm tabular-nums text-ink-subtle">
        {count} {t(count === 1 ? "drive.count.one" : "drive.count.many")}
      </span>
    </div>
  );
}

function ListHeader() {
  return (
    <div
      aria-hidden="true"
      className={cx(
        "hidden h-9 items-center gap-3 border-b border-line px-3 text-xs font-medium text-ink-subtle sm:grid",
        listColumns,
      )}
    >
      <span />
      <span className="pl-12">{t("drive.column.name")}</span>
      <span className="hidden sm:block">{t("drive.column.kind")}</span>
      <span className="hidden text-right sm:block">{t("drive.column.size")}</span>
      <span className="hidden lg:block">{t("drive.column.modified")}</span>
      <span />
    </div>
  );
}

function SelectionBar({
  downloadableCount,
  onBulkDelete,
  onBulkDownload,
  onBulkMove,
  onClear,
  selectedCount,
}: {
  downloadableCount: number;
  onBulkDelete: () => void;
  onBulkDownload: () => void;
  onBulkMove: () => void;
  onClear: () => void;
  selectedCount: number;
}) {
  return (
    <section
      aria-label={t("drive.selection.label")}
      className="fixed bottom-5 left-1/2 z-30 flex max-w-[calc(100vw-1.5rem)] -translate-x-1/2 animate-slide-up items-center gap-1 rounded-xl border border-line bg-raised p-1.5 pl-4 shadow-lg md:left-[calc(50%+7.5rem)]"
    >
      <span className="whitespace-nowrap text-base font-medium tabular-nums text-ink">
        {`${selectedCount} ${t(selectedCount === 1 ? "drive.selection.countOne" : "drive.selection.count")}`}
      </span>
      <span aria-hidden="true" className="mx-2 h-5 w-px shrink-0 bg-line" />
      <Button aria-label={t("drive.action.bulkMove")} leadingIcon={<FolderInput />} onClick={onBulkMove} size="sm" variant="ghost">
        {t("drive.action.move")}
      </Button>
      {downloadableCount > 0 ? (
        <Button
          aria-label={t("drive.action.bulkDownload")}
          leadingIcon={<Download />}
          onClick={onBulkDownload}
          size="sm"
          variant="ghost"
        >
          {t("drive.action.download")}
        </Button>
      ) : null}
      <Button
        aria-label={t("drive.action.bulkDelete")}
        leadingIcon={<Trash2 />}
        onClick={onBulkDelete}
        size="sm"
        variant="danger-ghost"
      >
        {t("drive.action.delete")}
      </Button>
      <IconButton icon={<X />} label={t("drive.selection.clear")} onClick={onClear} />
    </section>
  );
}

type EntryCardProps = {
  api: DriveApi;
  entry: DriveEntry;
  onNavigate: (folderId: string | null) => void;
  onOpenAction: (action: PendingAction) => void;
  onToggleSelection: (entry: DriveEntry) => void;
  searchMode: boolean;
  selected: boolean;
  selectionMode: boolean;
};

function DriveGridCard({
  api,
  entry,
  onNavigate,
  onOpenAction,
  onToggleSelection,
  searchMode,
  selected,
  selectionMode,
}: EntryCardProps) {
  return (
    <DriveContextMenu api={api} entry={entry} onOpenAction={onOpenAction}>
      <article
        className={cx(
          "group/card relative flex h-full min-h-0 flex-col rounded-lg p-1.5 transition-colors duration-150",
          selected ? "bg-accent-soft ring-2 ring-inset ring-accent" : "hover:bg-hover",
        )}
      >
        <button
          aria-label={`${t("drive.action.open")} ${entry.name}`}
          className="focus-ring flex min-h-0 min-w-0 flex-1 flex-col rounded-md text-left"
          onClick={() => openEntry({ api, entry, onNavigate, onOpenAction })}
          type="button"
        >
          <span className="relative grid min-h-0 w-full flex-1 place-items-center overflow-hidden rounded-md bg-sunken">
            <FileTypeIcon mimeType={entry.mimeType} name={entry.name} previewSrc={entry.thumbnailUrl} type={entry.kind} />
            <EntryStateBadge className="absolute bottom-2 left-2" entry={entry} />
          </span>
          <span className="grid min-w-0 gap-0.5 px-1 pb-0.5 pr-9 pt-2">
            <span className="truncate text-sm font-medium text-ink">{entry.name}</span>
            <span className="truncate text-xs text-ink-subtle">
              {searchMode && entry.reason ? entry.reason : entryMeta(entry)}
            </span>
          </span>
        </button>
        <EntrySelectionCheckbox
          className={cx(
            "absolute left-3 top-3 transition-opacity duration-150",
            selected || selectionMode
              ? "opacity-100"
              : "opacity-0 focus-within:opacity-100 group-hover/card:opacity-100 [@media(hover:none)]:opacity-100",
          )}
          entry={entry}
          onToggle={onToggleSelection}
          selected={selected}
        />
        <div className="absolute bottom-2 right-1.5">
          <DriveEntryMenu api={api} entry={entry} onOpenAction={onOpenAction} />
        </div>
      </article>
    </DriveContextMenu>
  );
}

function DriveListRow({ api, entry, onNavigate, onOpenAction, onToggleSelection, searchMode, selected }: EntryCardProps) {
  const meta = [entryKindLabel(entry), formatBytes(entry.sizeBytes)].filter(Boolean).join(" · ");

  return (
    <DriveContextMenu api={api} entry={entry} onOpenAction={onOpenAction}>
      <article
        className={cx(
          "grid h-full items-center gap-3 border-b border-line px-3 transition-colors duration-150",
          listColumns,
          selected ? "bg-accent-soft" : "hover:bg-hover",
        )}
      >
        <EntrySelectionCheckbox entry={entry} onToggle={onToggleSelection} selected={selected} />
        <button
          aria-label={`${t("drive.action.open")} ${entry.name}`}
          className="focus-ring flex h-11 min-w-0 items-center gap-3 rounded-sm text-left"
          onClick={() => openEntry({ api, entry, onNavigate, onOpenAction })}
          type="button"
        >
          <FileTypeIcon mimeType={entry.mimeType} name={entry.name} previewSrc={entry.thumbnailUrl} size="list" type={entry.kind} />
          <span className="grid min-w-0 gap-0.5">
            <span className="truncate text-base font-medium text-ink">{entry.name}</span>
            <span className="flex min-w-0 items-center gap-2 text-xs text-ink-subtle">
              {searchMode && entry.reason ? <span className="truncate">{entry.reason}</span> : null}
              {!searchMode || !entry.reason ? <span className="truncate sm:hidden">{meta}</span> : null}
              <EntryStateBadge entry={entry} />
            </span>
          </span>
        </button>
        <span className="hidden truncate text-sm text-ink-muted sm:block">{entryKindLabel(entry)}</span>
        <span className="hidden text-right text-sm tabular-nums text-ink-muted sm:block">{formatBytes(entry.sizeBytes) || "—"}</span>
        <span className="hidden truncate text-sm text-ink-muted lg:block">{formatDate(entry.updatedAt)}</span>
        <DriveEntryMenu api={api} entry={entry} onOpenAction={onOpenAction} />
      </article>
    </DriveContextMenu>
  );
}

function EntrySelectionCheckbox({
  className,
  entry,
  onToggle,
  selected,
}: {
  className?: string;
  entry: DriveEntry;
  onToggle: (entry: DriveEntry) => void;
  selected: boolean;
}) {
  return (
    <span className={cx("z-10 inline-flex", className)} onClick={(event) => event.stopPropagation()}>
      <CheckboxBox
        aria-label={`${selected ? t("drive.selection.unselect") : t("drive.selection.select")} ${entry.name}`}
        boxClassName="rounded-[5px] shadow-sm"
        checked={selected}
        onChange={() => onToggle(entry)}
      />
    </span>
  );
}

function EntryStateBadge({ className, entry }: { className?: string; entry: DriveEntry }) {
  if (isPartialFailureState(entry.processingState)) {
    return (
      <Badge className={className} dot tone="warning">
        {t("drive.state.partialFailure")}
      </Badge>
    );
  }

  if (isIndexingState(entry.processingState)) {
    return (
      <Badge className={className} dot pulse tone="warning">
        {t("drive.state.indexing")}
      </Badge>
    );
  }

  return null;
}

function entryKindLabel(entry: DriveEntry): string {
  return t(kindLabels[getFileTypeKind(entry.kind, entry.name, entry.mimeType)]);
}

function entryMeta(entry: DriveEntry): string {
  if (entry.kind === "folder") {
    return t("drive.item.folder");
  }

  return [entryKindLabel(entry), formatBytes(entry.sizeBytes)].filter(Boolean).join(" · ");
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (!value || Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat(t("app.locale"), { dateStyle: "medium" }).format(date);
}

function entryKey(entry: DriveEntry): string {
  return `${entry.kind}:${entry.id}`;
}

function isInlinePreviewable(entry: DriveEntry): boolean {
  if (entry.kind !== "asset") {
    return false;
  }

  const kind = getFileTypeKind("asset", entry.name, entry.mimeType);
  return kind === "pdf" || kind === "text";
}

function isPreviewable(entry: DriveEntry): boolean {
  if (entry.kind !== "asset") {
    return false;
  }

  return ["image", "pdf", "text", "video"].includes(getFileTypeKind("asset", entry.name, entry.mimeType));
}

function openEntry({
  api,
  entry,
  onNavigate,
  onOpenAction,
}: {
  api: DriveApi;
  entry: DriveEntry;
  onNavigate: (folderId: string | null) => void;
  onOpenAction: (action: PendingAction) => void;
}) {
  if (entry.kind === "folder") {
    onNavigate(entry.id);
  } else if (isPreviewable(entry)) {
    onOpenAction({ entry, type: "preview" });
  } else {
    openInNewTab(api.downloadUrl(entry.id));
  }
}

function openInNewTab(url: string) {
  window.open(url, "_blank", "noopener,noreferrer");
}

function getDriveEntryActions({
  api,
  entry,
  onOpenAction,
}: {
  api: DriveApi;
  entry: DriveEntry;
  onOpenAction: (action: PendingAction) => void;
}): MenuItem[] {
  return [
    {
      icon: <PencilLine />,
      id: "rename",
      label: t("drive.action.rename"),
      onSelect: () => onOpenAction({ entry, type: "rename" }),
    },
    {
      icon: <FolderInput />,
      id: "move",
      label: t("drive.action.move"),
      onSelect: () => onOpenAction({ entry, type: "move" }),
    },
    ...(entry.kind === "asset" && isPreviewable(entry)
      ? [
          {
            icon: <Eye />,
            id: "preview",
            label: t("drive.action.preview"),
            onSelect: () => onOpenAction({ entry, type: "preview" }),
          },
        ]
      : []),
    ...(entry.kind === "asset"
      ? [
          {
            icon: <Download />,
            id: "download",
            label: t("drive.action.download"),
            onSelect: () => openInNewTab(api.downloadUrl(entry.id)),
          },
        ]
      : []),
    {
      icon: <Trash2 />,
      id: "delete",
      label: t("drive.action.delete"),
      onSelect: () => onOpenAction({ entry, type: "delete" }),
      separatorBefore: true,
      tone: "danger",
    },
  ];
}

function DriveContextMenu({
  api,
  children,
  entry,
  onOpenAction,
}: {
  api: DriveApi;
  children: ReactNode;
  entry: DriveEntry;
  onOpenAction: (action: PendingAction) => void;
}) {
  const items = getDriveEntryActions({ api, entry, onOpenAction });

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent aria-label={`${t("drive.action.menu")} ${entry.name}`}>
        {items.map((item) => (
          <div className="contents" key={item.id}>
            {item.separatorBefore ? <ContextMenuSeparator /> : null}
            <ContextMenuItem onSelect={item.onSelect} variant={item.tone === "danger" ? "destructive" : "default"}>
              {item.icon}
              {item.label}
            </ContextMenuItem>
          </div>
        ))}
      </ContextMenuContent>
    </ContextMenu>
  );
}

function DriveEntryMenu({
  api,
  entry,
  onOpenAction,
}: {
  api: DriveApi;
  entry: DriveEntry;
  onOpenAction: (action: PendingAction) => void;
}) {
  return (
    <Menu
      items={getDriveEntryActions({ api, entry, onOpenAction })}
      label={`${t("drive.action.menu")} ${entry.name}`}
      trigger={<MoreHorizontal aria-hidden="true" />}
      triggerVariant="ghost"
    />
  );
}

type ActionDialogProps = {
  action: PendingAction | null;
  api: DriveApi;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  setValue: (value: string) => void;
  value: string;
};

function ActionDialog({ action, api, error, onOpenChange, onSubmit, setValue, value }: ActionDialogProps) {
  if (!action) {
    return null;
  }

  if (action.type === "preview" && action.entry.kind === "asset") {
    if (getFileTypeKind("asset", action.entry.name, action.entry.mimeType) === "image") {
      return <ImageViewerDialog api={api} entry={action.entry} onOpenChange={onOpenChange} />;
    }

    if (isInlinePreviewable(action.entry)) {
      return <AssetPreviewDialog api={api} entry={action.entry} onOpenChange={onOpenChange} />;
    }

    return (
      <Dialog
        actions={<DownloadAction api={api} entry={action.entry} />}
        icon={<Eye />}
        onOpenChange={onOpenChange}
        open
        size="xl"
        title={action.entry.name}
      >
        <img
          alt={action.entry.name}
          className="max-h-[64vh] w-full rounded-lg bg-sunken object-contain"
          src={api.previewUrl(action.entry.id)}
        />
      </Dialog>
    );
  }

  const isBulkDelete = action.type === "bulk-delete";
  const isDelete = isBulkDelete || action.type === "delete";
  const isBulkMove = action.type === "bulk-move";
  const isMove = isBulkMove || action.type === "move";
  const titleKey: MessageKey =
    action.type === "create-folder"
      ? "drive.dialog.createFolderTitle"
      : action.type === "rename"
        ? "drive.dialog.renameTitle"
        : isBulkMove
          ? "drive.dialog.bulkMoveTitle"
          : isMove
            ? "drive.dialog.moveTitle"
            : isBulkDelete
              ? "drive.dialog.bulkDeleteTitle"
              : "drive.dialog.deleteTitle";
  const icon =
    action.type === "create-folder" ? <FolderPlus /> : action.type === "rename" ? <PencilLine /> : isMove ? <FolderInput /> : <Trash2 />;
  const description =
    action.type === "bulk-move" || action.type === "bulk-delete"
      ? `${action.entries.length} ${t(action.entries.length === 1 ? "drive.count.one" : "drive.count.many")}`
      : action.type === "move" || action.type === "delete"
        ? action.entry.name
        : undefined;

  return (
    <Dialog
      actions={
        <>
          <Button onClick={() => onOpenChange(false)} variant="ghost">
            {t("drive.dialog.cancel")}
          </Button>
          <Button form="drive-action-form" type="submit" variant={isDelete ? "danger" : "primary"}>
            {isDelete ? t("drive.dialog.deleteConfirm") : t("drive.dialog.save")}
          </Button>
        </>
      }
      description={description}
      icon={icon}
      onOpenChange={onOpenChange}
      open
      title={t(titleKey)}
      tone={isDelete ? "danger" : "default"}
    >
      <form className="grid gap-3" id="drive-action-form" onSubmit={onSubmit}>
        {action.type === "rename" || action.type === "create-folder" ? (
          <Input
            data-autofocus
            label={t("drive.dialog.nameLabel")}
            onChange={(event) => setValue(event.currentTarget.value)}
            onFocus={(event) => {
              const input = event.currentTarget;
              const dot = action.type === "rename" && action.entry.kind === "asset" ? input.value.lastIndexOf(".") : -1;
              input.setSelectionRange(0, dot > 0 ? dot : input.value.length);
            }}
            value={value}
          />
        ) : null}
        {isMove ? (
          <Input
            data-autofocus
            hint={t("drive.dialog.moveHint")}
            label={t("drive.dialog.folderIdLabel")}
            onChange={(event) => setValue(event.currentTarget.value)}
            placeholder={t("drive.dialog.folderIdPlaceholder")}
            value={value}
          />
        ) : null}
        {isDelete ? <p>{t(isBulkDelete ? "drive.dialog.bulkDeleteBody" : "drive.dialog.deleteBody")}</p> : null}
        {error ? (
          <Callout role="alert" tone="danger">
            {error}
          </Callout>
        ) : null}
      </form>
    </Dialog>
  );
}

function DownloadAction({ api, entry }: { api: DriveApi; entry: DriveEntry }) {
  return (
    <Button leadingIcon={<Download />} onClick={() => openInNewTab(api.downloadUrl(entry.id))}>
      {t("drive.action.download")}
    </Button>
  );
}

const viewerFocusable = "button:not(:disabled)";

function ImageViewerDialog({
  api,
  entry,
  onOpenChange,
}: {
  api: DriveApi;
  entry: DriveEntry;
  onOpenChange: (open: boolean) => void;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onOpenChange(false);
      }

      if (event.key === "Tab") {
        const focusable = Array.from(rootRef.current?.querySelectorAll<HTMLElement>(viewerFocusable) ?? []);
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, [onOpenChange]);

  function closeOnBackdrop(event: React.MouseEvent<HTMLElement>) {
    if (event.target === event.currentTarget) {
      onOpenChange(false);
    }
  }

  return createPortal(
    <div
      aria-labelledby="drive-image-viewer-title"
      aria-modal="true"
      className="fixed inset-0 z-50 flex animate-fade-in flex-col bg-media/95 backdrop-blur-sm"
      onClick={closeOnBackdrop}
      ref={rootRef}
      role="dialog"
    >
      <div className="flex shrink-0 items-center gap-3 px-4 py-3 text-white sm:px-6 sm:py-4">
        <h2 className="min-w-0 flex-1 truncate text-base font-medium" id="drive-image-viewer-title">
          {entry.name}
        </h2>
        <IconButton
          icon={<Download />}
          label={t("drive.action.download")}
          onClick={() => openInNewTab(api.downloadUrl(entry.id))}
          tooltipSide="bottom"
          variant="overlay"
        />
        <IconButton
          icon={<X />}
          label={t("common.close")}
          onClick={() => onOpenChange(false)}
          ref={closeButtonRef}
          tooltipSide="bottom"
          variant="overlay"
        />
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center px-4 pb-4 sm:px-8 sm:pb-8" onClick={closeOnBackdrop}>
        <img
          alt={entry.name}
          className="max-h-full max-w-full animate-pop-in rounded-lg object-contain shadow-xl"
          src={api.previewUrl(entry.id)}
        />
      </div>
    </div>,
    document.body,
  );
}

type AssetPreviewState =
  | { status: "error" }
  | { status: "loading" }
  | { content: string; status: "text" }
  | { status: "pdf"; url: string };

function AssetPreviewDialog({
  api,
  entry,
  onOpenChange,
}: {
  api: DriveApi;
  entry: DriveEntry;
  onOpenChange: (open: boolean) => void;
}) {
  const kind = getFileTypeKind("asset", entry.name, entry.mimeType);
  const [state, setState] = useState<AssetPreviewState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    let cancelled = false;

    setState({ status: "loading" });
    void (async () => {
      try {
        const response = await fetch(api.downloadUrl(entry.id), { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`Preview request failed with status ${response.status}`);
        }

        if (kind === "text") {
          const content = await response.text();
          if (!cancelled) {
            setState({ content, status: "text" });
          }
          return;
        }

        const blob = await response.blob();
        if (typeof URL.createObjectURL !== "function") {
          throw new Error("PDF preview is not supported in this browser");
        }
        objectUrl = URL.createObjectURL(blob);
        if (cancelled) {
          revokeObjectUrl(objectUrl);
          return;
        }
        setState({ status: "pdf", url: objectUrl });
      } catch {
        if (!controller.signal.aborted && !cancelled) {
          setState({ status: "error" });
        }
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) {
        revokeObjectUrl(objectUrl);
      }
    };
  }, [api, entry.id, kind]);

  return (
    <Dialog
      actions={<DownloadAction api={api} entry={entry} />}
      icon={<FileTypeIcon className="size-9 rounded-md" mimeType={entry.mimeType} name={entry.name} size="list" type="asset" />}
      onOpenChange={onOpenChange}
      open
      size="xl"
      title={entry.name}
    >
      {state.status === "loading" ? <LoadingState label={t("drive.preview.loading")} /> : null}
      {state.status === "error" ? <ErrorState body={t("drive.preview.error")} title={t("drive.error.title")} /> : null}
      {state.status === "text" ? (
        <pre
          aria-label={entry.name}
          className="max-h-[62vh] overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-sunken p-4 font-mono text-sm leading-relaxed text-ink"
        >
          {state.content || t("drive.preview.empty")}
        </pre>
      ) : null}
      {state.status === "pdf" ? (
        <iframe
          className="h-[min(68vh,48rem)] w-full rounded-lg border border-line bg-sunken"
          src={state.url}
          title={`${entry.name} · ${t("drive.action.preview")}`}
        />
      ) : null}
    </Dialog>
  );
}

function revokeObjectUrl(url: string) {
  if (typeof URL.revokeObjectURL === "function") {
    URL.revokeObjectURL(url);
  }
}

function normalizeBreadcrumbs(items: DriveBreadcrumb[] | undefined, folderId: string | null): DriveBreadcrumb[] {
  if (items && items.length > 0) {
    return [{ folder_id: null, name: t("drive.root") }, ...items.filter((item) => item.folder_id !== null)];
  }

  return [
    { folder_id: null, name: t("drive.root") },
    ...(folderId ? [{ folder_id: folderId, name: t("drive.currentFolder") }] : []),
  ];
}
