import { useEffect, useState } from "react";
import { ArrowLeft, Image as ImageIcon, Plus, SquareLibrary, Trash2 } from "lucide-react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { Input } from "../../components/Input";
import { PageHeader } from "../../components/PageHeader";
import { albumsApi } from "../../api/albums";
import type { AlbumsApi, Album } from "../../api/albums";
import { assetThumbnailUrl } from "../../api/photos";
import { t } from "../../i18n/dictionary";
import { AlbumCover } from "./AlbumCover";

type LoadState = "idle" | "loading" | "ready" | "error";

export type AlbumDetailPageProps = {
  albumId: string;
  api?: AlbumsApi;
  onBack?: () => void;
};

export function AlbumDetailPage({ albumId, api = albumsApi, onBack = backToAlbums }: AlbumDetailPageProps) {
  const [album, setAlbum] = useState<Album | null>(null);
  const [assetId, setAssetId] = useState("");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;

    async function loadAlbum() {
      setLoadState("loading");
      setError(null);
      try {
        const response = await api.getAlbum(albumId);
        if (active) {
          setAlbum(response);
          setLoadState("ready");
        }
      } catch (caught) {
        if (active) {
          setError(caught instanceof Error ? caught.message : t("albums.loadError"));
          setLoadState("error");
        }
      }
    }

    void loadAlbum();

    return () => {
      active = false;
    };
  }, [albumId, api, refreshKey]);

  async function addItem() {
    const trimmed = assetId.trim();
    if (!trimmed) {
      return;
    }

    setMutating(true);
    try {
      const updated = await api.addAlbumItem(albumId, trimmed);
      setAlbum(updated);
      setAssetId("");
    } finally {
      setMutating(false);
    }
  }

  async function removeItem(itemAssetId: string) {
    setMutating(true);
    try {
      const updated = await api.removeAlbumItem(albumId, itemAssetId);
      setAlbum(updated);
    } finally {
      setMutating(false);
    }
  }

  if (loadState === "loading") {
    return <LoadingState label={t("albums.loading")} />;
  }

  if (loadState === "error") {
    return <ErrorState body={error ?? t("albums.loadError")} onRetry={() => setRefreshKey((value) => value + 1)} />;
  }

  if (!album) {
    return (
      <EmptyState body={t("albums.detailEmptyBody")} icon={<SquareLibrary />} title={t("albums.detailEmptyTitle")} />
    );
  }

  const count = album.asset_ids.length;

  return (
    <div className="grid w-full content-start gap-8">
      <div className="flex items-end gap-5">
        <AlbumCover
          className="hidden size-24 shrink-0 rounded-xl border border-line shadow-sm sm:block"
          compact
          src={album.cover_asset ? assetThumbnailUrl(album.cover_asset) : undefined}
        />
        <PageHeader
          className="min-w-0 flex-1"
          description={
            <Badge size="md">
              {count} {count === 1 ? t("photos.item") : t("photos.items")}
            </Badge>
          }
          eyebrow={
            <a
              className="focus-ring -ml-1 inline-flex items-center gap-1 rounded-xs px-1 transition-colors hover:text-ink"
              href="/albums"
              onClick={(event) => {
                event.preventDefault();
                onBack();
              }}
            >
              <ArrowLeft aria-hidden="true" className="size-3.5" />
              {t("albums.back")}
            </a>
          }
          title={album.title}
        />
      </div>

      <form
        className="flex w-full max-w-lg items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void addItem();
        }}
      >
        <Input
          className="font-mono"
          hideLabel
          label={t("albums.addItemLabel")}
          onChange={(event) => setAssetId(event.currentTarget.value)}
          placeholder={t("albums.addItemPlaceholder")}
          value={assetId}
          wrapperClassName="flex-1"
        />
        <Button disabled={mutating || !assetId.trim()} leadingIcon={<Plus />} type="submit" variant="primary">
          {t("albums.addItem")}
        </Button>
      </form>

      {count === 0 ? (
        <EmptyState
          body={t("albums.albumEmptyBody")}
          icon={<ImageIcon />}
          size="sm"
          title={t("albums.albumEmptyTitle")}
        />
      ) : (
        <Card aria-label={t("albums.itemsLabel")} as="section" padding="none">
          <ul className="divide-y divide-line">
            {album.asset_ids.map((itemAssetId) => (
              <li className="flex min-h-14 items-center gap-3 px-4 py-2 transition-colors hover:bg-subtle" key={itemAssetId}>
                <span
                  aria-hidden="true"
                  className="grid size-9 shrink-0 place-items-center rounded-sm bg-kind-image-soft text-kind-image"
                >
                  <ImageIcon className="size-4" />
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-sm text-ink">{itemAssetId}</span>
                <Button
                  aria-label={`${t("albums.removeItem")} ${itemAssetId}`}
                  disabled={mutating}
                  leadingIcon={<Trash2 />}
                  onClick={() => void removeItem(itemAssetId)}
                  size="sm"
                  variant="danger-ghost"
                >
                  {t("albums.removeItem")}
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function backToAlbums() {
  window.history.pushState({}, "", "/albums");
  window.dispatchEvent(new PopStateEvent("popstate"));
}
