import { absoluteApiPath, apiClient } from "./client";

export type PhotoAssetKind = "image" | "video";

export type PhotoProcessingState =
  | "created"
  | "blob_stored"
  | "metadata_extracted"
  | "thumbnail_pending"
  | "thumbnail_ready"
  | "ocr_pending"
  | "ocr_ready"
  | "embedding_pending"
  | "embedding_ready"
  | "indexed"
  | "failed_partial"
  | "failed";

export type PhotoAsset = {
  created_at: string;
  favorite: boolean;
  filename: string;
  id: string;
  kind: PhotoAssetKind;
  mime_type: string;
  processing_state: PhotoProcessingState;
  preview_url?: string | null;
  size_bytes: number;
  taken_at?: string | null;
  thumbnail_url?: string | null;
  updated_at: string;
};

export type PhotoTimelineGroup = {
  assets: PhotoAsset[];
  date: string;
};

export type PhotoTimelineResponse = {
  groups: PhotoTimelineGroup[];
  next_cursor: string | null;
};

export type SearchPhotoResult = {
  asset_id: string | null;
  id: string;
  processing_state: PhotoProcessingState | null;
  reason: string;
  subtitle: string | null;
  thumbnail_url: string | null;
  title: string;
  type: string;
};

export type SearchPhotosResponse = {
  items: SearchPhotoResult[];
  next_cursor: string | null;
};

export type PhotosApi = {
  getPhoto(assetId: string): Promise<PhotoAsset>;
  getTimeline(options?: { cursor?: string | null; limit?: number }): Promise<PhotoTimelineResponse>;
  searchPhotos(query: string, options?: { cursor?: string | null; limit?: number }): Promise<SearchPhotosResponse>;
  toggleFavorite(assetId: string, favorite: boolean): Promise<PhotoAsset>;
  uploadPhoto(file: File): Promise<PhotoAsset>;
};

type ApiRequest = <TResponse>(path: string, options?: { body?: BodyInit | Record<string, unknown>; method?: string }) => Promise<TResponse>;

const assetKinds = new Set(["image", "video"]);
const fallbackDate = "1970-01-01";

export function createPhotosApi(request: ApiRequest = apiClient.request): PhotosApi {
  return {
    async getPhoto(assetId) {
      const raw = await request<unknown>(`/photos/${encodeURIComponent(assetId)}`);
      return normalizePhotoAsset(raw);
    },

    async getTimeline(options = {}) {
      const params = new URLSearchParams();
      params.set("limit", String(options.limit ?? 60));
      if (options.cursor) {
        params.set("cursor", options.cursor);
      }

      const raw = await request<unknown>(`/photos/timeline?${params.toString()}`);
      return normalizeTimelineResponse(raw);
    },

    async searchPhotos(query, options = {}) {
      const params = new URLSearchParams();
      params.set("q", query);
      params.set("type", "photo");
      params.set("limit", String(options.limit ?? 30));
      if (options.cursor) {
        params.set("cursor", options.cursor);
      }

      return request<SearchPhotosResponse>(`/search?${params.toString()}`);
    },

    async toggleFavorite(assetId, favorite) {
      const raw = await request<unknown>(`/photos/${encodeURIComponent(assetId)}/favorite`, {
        body: { favorite },
        method: "POST",
      });
      return normalizePhotoAsset(raw);
    },

    async uploadPhoto(file) {
      const formData = new FormData();
      formData.set("file", file);
      formData.set("mode", "photos");

      const raw = await request<unknown>("/assets/upload", {
        body: formData,
        method: "POST",
      });
      return normalizePhotoAsset(raw);
    },
  };
}

export const photosApi = createPhotosApi();

export function assetThumbnailUrl(asset: Pick<PhotoAsset, "id" | "thumbnail_url">): string {
  return asset.thumbnail_url
    ? absoluteApiPath(asset.thumbnail_url)
    : `${apiClient.baseUrl}/assets/${encodeURIComponent(asset.id)}/thumbnail`;
}

export function assetPreviewUrl(asset: Pick<PhotoAsset, "id" | "preview_url">): string {
  return asset.preview_url
    ? absoluteApiPath(asset.preview_url)
    : `${apiClient.baseUrl}/assets/${encodeURIComponent(asset.id)}/preview`;
}

export function assetDownloadUrl(asset: Pick<PhotoAsset, "id">): string {
  return `${apiClient.baseUrl}/assets/${encodeURIComponent(asset.id)}/download`;
}

function normalizeTimelineResponse(raw: unknown): PhotoTimelineResponse {
  if (!isRecord(raw)) {
    return { groups: [], next_cursor: null };
  }

  if (Array.isArray(raw.groups)) {
    return {
      groups: raw.groups.map(normalizeTimelineGroup).filter((group) => group.assets.length > 0),
      next_cursor: typeof raw.next_cursor === "string" ? raw.next_cursor : null,
    };
  }

  if (Array.isArray(raw.items)) {
    return {
      groups: groupAssetsByDate(raw.items.map(normalizePhotoAsset)),
      next_cursor: typeof raw.next_cursor === "string" ? raw.next_cursor : null,
    };
  }

  return { groups: [], next_cursor: null };
}

function normalizeTimelineGroup(raw: unknown): PhotoTimelineGroup {
  if (!isRecord(raw)) {
    return { assets: [], date: fallbackDate };
  }

  const rawAssets = Array.isArray(raw.assets) ? raw.assets : [];
  return {
    assets: rawAssets.map(normalizePhotoAsset),
    date: typeof raw.date === "string" ? raw.date : typeof raw.day === "string" ? raw.day : fallbackDate,
  };
}

function groupAssetsByDate(assets: PhotoAsset[]): PhotoTimelineGroup[] {
  const groups = new Map<string, PhotoAsset[]>();

  for (const asset of assets) {
    const date = (asset.taken_at ?? asset.created_at).slice(0, 10) || fallbackDate;
    groups.set(date, [...(groups.get(date) ?? []), asset]);
  }

  return Array.from(groups, ([date, groupAssets]) => ({ assets: groupAssets, date }));
}

function normalizePhotoAsset(raw: unknown): PhotoAsset {
  if (!isRecord(raw)) {
    throw new TypeError("Invalid photo asset response");
  }

  const id = stringValue(raw.id, "asset");
  const kind = assetKinds.has(stringValue(raw.kind, "image")) ? (stringValue(raw.kind, "image") as PhotoAssetKind) : "image";

  return {
    created_at: stringValue(raw.created_at, new Date(0).toISOString()),
    favorite: Boolean(raw.favorite),
    filename: stringValue(raw.filename, stringValue(raw.title, id)),
    id,
    kind,
    mime_type: stringValue(raw.mime_type, kind === "video" ? "video/mp4" : "image/jpeg"),
    preview_url: optionalString(raw.preview_url),
    processing_state: stringValue(raw.processing_state, "created") as PhotoProcessingState,
    size_bytes: numberValue(raw.size_bytes),
    taken_at: optionalString(raw.taken_at),
    thumbnail_url: optionalString(raw.thumbnail_url),
    updated_at: stringValue(raw.updated_at, stringValue(raw.created_at, new Date(0).toISOString())),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
