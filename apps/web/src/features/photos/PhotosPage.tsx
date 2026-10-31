import { useEffect, useMemo, useState } from "react";
import { Heart, Images, Search, Sparkles, X } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { IconButton } from "../../components/IconButton";
import { Input } from "../../components/Input";
import { PageHeader } from "../../components/PageHeader";
import { Thumbnail } from "../../components/Thumbnail";
import { photosApi } from "../../api/photos";
import type { PhotoAsset, PhotoTimelineGroup, PhotosApi, SearchPhotoResult } from "../../api/photos";
import { t } from "../../i18n/dictionary";
import { PhotoLightbox } from "./PhotoLightbox";
import { PhotoTimeline } from "./PhotoTimeline";
import { PhotoUploadButton } from "./PhotoUploadButton";

export type PhotosPageProps = {
  api?: PhotosApi;
  favoritesOnly?: boolean;
  initialQuery?: string;
};

type LoadState = "idle" | "loading" | "ready" | "error";

export function PhotosPage({ api = photosApi, favoritesOnly = false, initialQuery = "" }: PhotosPageProps) {
  const [groups, setGroups] = useState<PhotoTimelineGroup[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedAsset, setSelectedAsset] = useState<PhotoAsset | null>(null);
  const [query, setQuery] = useState(initialQuery);
  const [searchResults, setSearchResults] = useState<SearchPhotoResult[]>([]);
  const [searchState, setSearchState] = useState<LoadState>("idle");

  useEffect(() => {
    let active = true;

    async function loadTimeline() {
      setLoadState("loading");
      setError(null);
      try {
        const response = await api.getTimeline();
        if (active) {
          setGroups(response.groups);
          setLoadState("ready");
        }
      } catch (caught) {
        if (active) {
          setError(caught instanceof Error ? caught.message : t("photos.loadError"));
          setLoadState("error");
        }
      }
    }

    void loadTimeline();

    return () => {
      active = false;
    };
  }, [api, refreshKey]);

  useEffect(() => {
    let active = true;
    const trimmed = query.trim();

    if (!trimmed) {
      setSearchResults([]);
      setSearchState("idle");
      return () => {
        active = false;
      };
    }

    async function loadSearch() {
      setSearchState("loading");
      try {
        const response = await api.searchPhotos(trimmed);
        if (active) {
          setSearchResults(response.items);
          setSearchState("ready");
        }
      } catch {
        if (active) {
          setSearchResults([]);
          setSearchState("error");
        }
      }
    }

    void loadSearch();

    return () => {
      active = false;
    };
  }, [api, query]);

  const visibleGroups = useMemo(() => {
    if (!favoritesOnly) {
      return groups;
    }

    return groups
      .map((group) => ({ ...group, assets: group.assets.filter((asset) => asset.favorite) }))
      .filter((group) => group.assets.length > 0);
  }, [favoritesOnly, groups]);

  const visibleAssets = useMemo(() => visibleGroups.flatMap((group) => group.assets), [visibleGroups]);
  const selectedIndex = selectedAsset ? visibleAssets.findIndex((asset) => asset.id === selectedAsset.id) : -1;
  const nextAsset = selectedIndex >= 0 && selectedIndex < visibleAssets.length - 1 ? visibleAssets[selectedIndex + 1] : null;
  const previousAsset = selectedIndex > 0 ? visibleAssets[selectedIndex - 1] : null;

  async function toggleFavorite(asset: PhotoAsset) {
    const updated = await api.toggleFavorite(asset.id, !asset.favorite);
    setGroups((current) => updateAssetInGroups(current, updated));
    setSelectedAsset((current) => (current?.id === updated.id ? updated : current));
  }

  async function openSearchResult(result: SearchPhotoResult) {
    if (!result.asset_id) {
      return;
    }

    const asset = await api.getPhoto(result.asset_id);
    setSelectedAsset(asset);
  }

  const emptyTitle = favoritesOnly ? t("favorites.emptyTitle") : t("photos.emptyTitle");
  const emptyBody = favoritesOnly ? t("favorites.emptyBody") : t("photos.emptyBody");
  const refresh = () => setRefreshKey((value) => value + 1);

  return (
    <div className="grid w-full content-start gap-8">
      <PageHeader
        actions={!favoritesOnly ? <PhotoUploadButton api={api} onUploaded={refresh} /> : null}
        description={favoritesOnly ? t("favorites.subtitle") : t("photos.subtitle")}
        title={favoritesOnly ? t("favorites.title") : t("photos.title")}
      >
        <Input
          hideLabel
          label={t("photos.searchLabel")}
          leadingIcon={<Search />}
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder={t("photos.searchPlaceholder")}
          trailing={
            query ? <IconButton icon={<X />} label={t("photos.searchClear")} onClick={() => setQuery("")} size="sm" /> : null
          }
          type="search"
          value={query}
          wrapperClassName="max-w-md"
        />
      </PageHeader>

      {query.trim() ? <SearchResults items={searchResults} onOpen={openSearchResult} state={searchState} /> : null}

      {loadState === "loading" ? <LoadingState label={t("photos.loading")} /> : null}
      {loadState === "error" ? <ErrorState body={error ?? t("photos.loadError")} onRetry={refresh} /> : null}
      {loadState === "ready" && visibleGroups.length === 0 ? (
        <EmptyState
          action={
            !favoritesOnly ? (
              <PhotoUploadButton api={api} label={t("photos.uploadFirst")} onUploaded={refresh} variant="secondary" />
            ) : null
          }
          body={emptyBody}
          icon={favoritesOnly ? <Heart /> : <Images />}
          title={emptyTitle}
        />
      ) : null}
      {loadState === "ready" && visibleGroups.length > 0 ? (
        <PhotoTimeline groups={visibleGroups} onOpen={setSelectedAsset} showFavoriteMarkers={!favoritesOnly} />
      ) : null}

      <PhotoLightbox
        asset={selectedAsset}
        onClose={() => setSelectedAsset(null)}
        onNext={nextAsset ? () => setSelectedAsset(nextAsset) : undefined}
        onPrevious={previousAsset ? () => setSelectedAsset(previousAsset) : undefined}
        onToggleFavorite={toggleFavorite}
      />
    </div>
  );
}

function SearchResults({
  items,
  onOpen,
  state,
}: {
  items: SearchPhotoResult[];
  onOpen: (result: SearchPhotoResult) => void;
  state: LoadState;
}) {
  if (state === "loading") {
    return <LoadingState className="min-h-24" label={t("photos.searching")} />;
  }

  if (state === "error") {
    return <ErrorState body={t("photos.searchError")} />;
  }

  if (state === "ready" && items.length === 0) {
    return (
      <EmptyState body={t("photos.searchEmptyBody")} icon={<Search />} size="sm" title={t("photos.searchEmptyTitle")} />
    );
  }

  if (items.length === 0) {
    return null;
  }

  return (
    <section aria-label={t("photos.searchResultsLabel")} className="grid gap-3">
      <div className="flex items-baseline gap-2">
        <h2 className="text-base font-semibold text-ink">{t("photos.searchResults")}</h2>
        <span className="text-sm tabular-nums text-ink-subtle">{items.length}</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <button
            className="focus-ring group/result grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-3 rounded-lg border border-line bg-raised p-2 text-left shadow-xs transition-[border-color,box-shadow] duration-150 hover:border-line-strong hover:shadow-md"
            key={item.id}
            onClick={() => onOpen(item)}
            type="button"
          >
            <Thumbnail alt={item.title} className="rounded-sm" src={item.thumbnail_url ?? undefined}>
              <Images aria-hidden="true" className="size-5" />
            </Thumbnail>
            <span className="min-w-0">
              <span className="block truncate text-base font-medium text-ink">{item.title}</span>
              <span className="mt-0.5 flex gap-1.5 text-sm text-ink-muted">
                <Sparkles aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-accent-ink" />
                <span className="line-clamp-2">{item.reason}</span>
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function updateAssetInGroups(groups: PhotoTimelineGroup[], updated: PhotoAsset): PhotoTimelineGroup[] {
  return groups.map((group) => ({
    ...group,
    assets: group.assets.map((asset) => (asset.id === updated.id ? updated : asset)),
  }));
}
