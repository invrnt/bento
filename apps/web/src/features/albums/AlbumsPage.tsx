import { useEffect, useState } from "react";
import { Plus, SquareLibrary } from "lucide-react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { Input } from "../../components/Input";
import { PageHeader } from "../../components/PageHeader";
import { albumsApi } from "../../api/albums";
import type { Album, AlbumsApi } from "../../api/albums";
import { assetThumbnailUrl } from "../../api/photos";
import { t } from "../../i18n/dictionary";
import { AlbumCover } from "./AlbumCover";

type LoadState = "idle" | "loading" | "ready" | "error";

export type AlbumsPageProps = {
  api?: AlbumsApi;
  onOpenAlbum?: (albumId: string) => void;
};

export function AlbumsPage({ api = albumsApi, onOpenAlbum }: AlbumsPageProps) {
  const [albums, setAlbums] = useState<Album[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;

    async function loadAlbums() {
      setLoadState("loading");
      setError(null);
      try {
        const response = await api.listAlbums();
        if (active) {
          setAlbums(response.albums);
          setLoadState("ready");
        }
      } catch (caught) {
        if (active) {
          setError(caught instanceof Error ? caught.message : t("albums.loadError"));
          setLoadState("error");
        }
      }
    }

    void loadAlbums();

    return () => {
      active = false;
    };
  }, [api, refreshKey]);

  async function createAlbum() {
    const trimmed = title.trim();
    if (!trimmed) {
      return;
    }

    setCreating(true);
    try {
      const album = await api.createAlbum(trimmed);
      setAlbums((current) => [album, ...current.filter((item) => item.id !== album.id)]);
      setTitle("");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="grid w-full content-start gap-8">
      <PageHeader description={t("albums.subtitle")} title={t("albums.title")}>
        <form
          className="flex w-full max-w-md items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void createAlbum();
          }}
        >
          <Input
            hideLabel
            label={t("albums.createLabel")}
            onChange={(event) => setTitle(event.currentTarget.value)}
            placeholder={t("albums.createPlaceholder")}
            value={title}
            wrapperClassName="flex-1"
          />
          <Button disabled={!title.trim()} leadingIcon={<Plus />} loading={creating} type="submit" variant="primary">
            {creating ? t("albums.creating") : t("albums.create")}
          </Button>
        </form>
      </PageHeader>

      {loadState === "loading" ? <LoadingState label={t("albums.loading")} /> : null}
      {loadState === "error" ? (
        <ErrorState body={error ?? t("albums.loadError")} onRetry={() => setRefreshKey((value) => value + 1)} />
      ) : null}
      {loadState === "ready" && albums.length === 0 ? (
        <EmptyState body={t("albums.emptyBody")} icon={<SquareLibrary />} title={t("albums.emptyTitle")} />
      ) : null}
      {albums.length > 0 ? (
        <section
          aria-label={t("albums.listLabel")}
          className="grid grid-cols-[repeat(auto-fill,minmax(13.5rem,1fr))] gap-4"
        >
          {albums.map((album) => (
            <AlbumCard album={album} key={album.id} onOpenAlbum={onOpenAlbum} />
          ))}
        </section>
      ) : null}
    </div>
  );
}

function AlbumCard({ album, onOpenAlbum }: { album: Album; onOpenAlbum?: (albumId: string) => void }) {
  const count = album.asset_ids.length;

  return (
    <article className="group/album relative overflow-hidden rounded-lg border border-line bg-raised shadow-xs transition-[border-color,box-shadow] duration-200 hover:border-line-strong hover:shadow-md">
      <AlbumCover
        className="aspect-[4/3] transition-transform duration-500 ease-out group-hover/album:scale-[1.03]"
        src={album.cover_asset ? assetThumbnailUrl(album.cover_asset) : undefined}
      />
      <div className="flex items-center justify-between gap-3 border-t border-line px-3.5 py-3">
        <h2 className="min-w-0 truncate text-base font-semibold text-ink">{album.title}</h2>
        <Badge>
          {count} {count === 1 ? t("photos.item") : t("photos.items")}
        </Badge>
      </div>
      <button
        aria-label={`${t("albums.open")} ${album.title}`}
        className="focus-ring absolute inset-0 rounded-lg focus-visible:outline-offset-[-2px]"
        onClick={() => onOpenAlbum?.(album.id)}
        type="button"
      />
    </article>
  );
}
