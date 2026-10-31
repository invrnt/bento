import { useEffect, useState } from "react";
import { ChevronRight, Folder, FolderOpen, HardDrive, RotateCw, Upload } from "lucide-react";

import type { DriveApi, DriveBreadcrumb, DriveFolder } from "../../api/drive";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { t } from "../../i18n/dictionary";

type FolderTreeProps = {
  api: DriveApi;
  breadcrumbs: DriveBreadcrumb[];
  currentFolderId: string | null;
  onNavigate: (folderId: string | null) => void;
  reloadKey: number;
};

export function FolderTree({ api, breadcrumbs, currentFolderId, onNavigate, reloadKey }: FolderTreeProps) {
  const [children, setChildren] = useState<Record<string, DriveFolder[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([rootKey]));
  const [loading, setLoading] = useState<Set<string>>(() => new Set());
  const [failed, setFailed] = useState<Set<string>>(() => new Set());

  async function loadChildren(folderId: string | null) {
    const key = folderKey(folderId);
    setLoading((current) => new Set(current).add(key));
    setFailed((current) => without(current, key));
    try {
      const folders: DriveFolder[] = [];
      let cursor: string | null = null;
      do {
        const page = await api.listItems({ cursor, folderId, limit: 100 });
        folders.push(...page.items.filter((item) => item.type === "folder").map((item) => item.folder));
        cursor = page.next_cursor;
      } while (cursor);
      folders.sort((left, right) => left.name.localeCompare(right.name, "es", { sensitivity: "base" }));
      setChildren((current) => ({ ...current, [key]: folders }));
    } catch {
      setFailed((current) => new Set(current).add(key));
    } finally {
      setLoading((current) => without(current, key));
    }
  }

  useEffect(() => {
    const ancestorIds = breadcrumbs.map((item) => item.folder_id).filter((id): id is string => id !== null);
    const openKeys = new Set([rootKey, ...ancestorIds.map(folderKey)]);
    setExpanded(openKeys);
    setChildren({});
    setFailed(new Set());
    void Promise.all([loadChildren(null), ...ancestorIds.map((id) => loadChildren(id))]);
    // loadChildren intentionally reads the current API implementation for this refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, breadcrumbs, reloadKey]);

  function toggle(folderId: string | null) {
    const key = folderKey(folderId);
    const isOpen = expanded.has(key);
    setExpanded((current) => {
      const next = new Set(current);
      if (isOpen) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
    if (!isOpen && !children[key] && !loading.has(key)) {
      void loadChildren(folderId);
    }
  }

  return (
    <aside
      aria-label={t("drive.tree.label")}
      className="hidden w-60 shrink-0 flex-col overflow-hidden rounded-lg border border-line bg-subtle lg:flex"
    >
      <h2 className="flex h-11 shrink-0 items-center px-4 text-xs font-medium text-ink-subtle">{t("drive.tree.title")}</h2>
      <div className="relative min-h-0 flex-1">
        <div className="absolute inset-0 overflow-auto px-2 pb-2" role="tree">
          <FolderNode
            ancestorIds={new Set()}
            childrenByParent={children}
            currentFolderId={currentFolderId}
            depth={0}
            expanded={expanded}
            failed={failed}
            folder={null}
            label={t("drive.root")}
            loading={loading}
            onLoad={loadChildren}
            onNavigate={onNavigate}
            onToggle={toggle}
          />
        </div>
      </div>
      <p className="flex shrink-0 gap-2 border-t border-line px-4 py-3 text-xs text-ink-subtle">
        <Upload aria-hidden="true" className="mt-px size-3.5 shrink-0" />
        <span>{t("drive.upload.dropHint")}</span>
      </p>
    </aside>
  );
}

type FolderNodeProps = {
  ancestorIds: Set<string>;
  childrenByParent: Record<string, DriveFolder[]>;
  currentFolderId: string | null;
  depth: number;
  expanded: Set<string>;
  failed: Set<string>;
  folder: DriveFolder | null;
  label: string;
  loading: Set<string>;
  onLoad: (folderId: string | null) => Promise<void>;
  onNavigate: (folderId: string | null) => void;
  onToggle: (folderId: string | null) => void;
};

function FolderNode(props: FolderNodeProps) {
  const { ancestorIds, childrenByParent, currentFolderId, depth, expanded, failed, folder, label, loading, onLoad, onNavigate, onToggle } = props;
  const folderId = folder?.id ?? null;
  const key = folderKey(folderId);
  const isExpanded = expanded.has(key);
  const isCurrent = folderId === currentFolderId;
  const childFolders = childrenByParent[key];
  const isLoading = loading.has(key);
  const hasKnownChildren = Boolean(childFolders?.length);
  const indent = Math.min(depth, 8) * 14;

  return (
    <div aria-expanded={isExpanded} aria-selected={isCurrent} role="treeitem">
      <div
        className={cx(
          "flex h-8 min-w-0 items-center gap-0.5 rounded-sm pr-1 transition-[background-color,color,box-shadow] duration-150",
          isCurrent ? "bg-raised text-ink shadow-xs ring-1 ring-line" : "text-ink-muted hover:bg-hover hover:text-ink",
        )}
        style={{ paddingLeft: `${indent + 2}px` }}
      >
        <button
          aria-label={`${isExpanded ? t("drive.tree.collapse") : t("drive.tree.expand")} ${label}`}
          className="focus-ring grid size-6 shrink-0 place-items-center rounded-xs text-ink-subtle hover:bg-hover hover:text-ink"
          onClick={() => onToggle(folderId)}
          type="button"
        >
          <ChevronRight
            aria-hidden="true"
            className={cx("size-3.5 transition-transform duration-150", isExpanded ? "rotate-90" : undefined)}
          />
        </button>
        <button
          className="focus-ring flex h-7 min-w-0 flex-1 items-center gap-2 rounded-xs px-1 text-left text-base font-medium"
          onClick={() => onNavigate(folderId)}
          type="button"
        >
          <FolderGlyph open={isExpanded} root={folderId === null} />
          <span className="truncate">{label}</span>
          {isLoading ? <Spinner className="ml-auto size-3 border-[1.5px] text-ink-subtle" /> : null}
        </button>
      </div>
      {isExpanded ? (
        <div role="group">
          {failed.has(key) ? (
            <button
              className="focus-ring my-0.5 inline-flex h-7 items-center gap-1.5 rounded-xs px-2 text-xs font-medium text-danger-ink hover:bg-danger-soft"
              onClick={() => void onLoad(folderId)}
              style={{ marginLeft: `${indent + 30}px` }}
              type="button"
            >
              <RotateCw aria-hidden="true" className="size-3" />
              {t("drive.tree.retry")}
            </button>
          ) : null}
          {!isLoading && childFolders && !hasKnownChildren ? (
            <p className="py-1 pr-2 text-xs text-ink-subtle" style={{ paddingLeft: `${indent + 48}px` }}>
              {t("drive.tree.empty")}
            </p>
          ) : null}
          {childFolders?.filter((child) => child.id !== folderId && !ancestorIds.has(child.id)).map((child) => (
            <FolderNode
              {...props}
              ancestorIds={new Set([...ancestorIds, ...(folderId ? [folderId] : [])])}
              depth={depth + 1}
              folder={child}
              key={child.id}
              label={child.name}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FolderGlyph({ open, root }: { open: boolean; root: boolean }) {
  if (root) {
    return <HardDrive aria-hidden="true" className="size-4 shrink-0 text-ink-muted" strokeWidth={1.75} />;
  }

  const Icon = open ? FolderOpen : Folder;

  return (
    <Icon
      aria-hidden="true"
      className="size-4 shrink-0 text-kind-folder"
      fill="currentColor"
      fillOpacity={0.22}
      strokeWidth={1.75}
    />
  );
}

const rootKey = "__root__";

function folderKey(folderId: string | null): string {
  return folderId ?? rootKey;
}

function without(values: Set<string>, value: string): Set<string> {
  const next = new Set(values);
  next.delete(value);
  return next;
}
