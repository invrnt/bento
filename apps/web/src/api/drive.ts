import { absoluteApiPath, apiClient } from "./client";

export type DriveAsset = {
  created_at: string;
  duplicate?: boolean;
  favorite: boolean;
  filename: string;
  folder_id: string | null;
  id: string;
  kind: string;
  mime_type: string;
  mode: string;
  preview_url?: string | null;
  processing_state: string;
  sha256: string;
  size_bytes: number;
  thumbnail_url?: string | null;
  updated_at: string;
};

export type DriveFolder = {
  created_at: string;
  deleted_at?: string | null;
  id: string;
  name: string;
  parent_id: string | null;
  updated_at: string;
};

export type DriveItem =
  | {
      folder: DriveFolder;
      id?: string;
      name?: string;
      type: "folder";
      updated_at?: string;
    }
  | {
      asset: DriveAsset;
      id?: string;
      name?: string;
      type: "asset";
      updated_at?: string;
    };

export type DriveBreadcrumb = {
  folder_id: string | null;
  name: string;
};

export type DriveItemsResponse = {
  breadcrumbs?: DriveBreadcrumb[];
  items: DriveItem[];
  next_cursor: string | null;
};

export type DriveSearchItem = {
  asset_id: string | null;
  id: string;
  processing_state: string | null;
  reason: string;
  score: number;
  subtitle: string | null;
  thumbnail_url: string | null;
  title: string;
  type: string;
};

export type DriveSearchResponse = {
  facets: Array<{ count: number; type: string }>;
  items: DriveSearchItem[];
  next_cursor: string | null;
};

export type DriveApi = {
  createFolder: (input: { name: string; parentId: string | null }) => Promise<DriveFolder>;
  deleteAsset: (assetId: string) => Promise<DriveAsset>;
  deleteFolder: (folderId: string) => Promise<DriveFolder>;
  downloadUrl: (assetId: string) => string;
  listItems: (input: { cursor?: string | null; folderId: string | null; limit?: number }) => Promise<DriveItemsResponse>;
  moveAsset: (input: { assetId: string; folderId: string | null }) => Promise<DriveAsset>;
  moveFolder: (input: { folderId: string; parentId: string | null }) => Promise<DriveFolder>;
  previewUrl: (assetId: string) => string;
  renameAsset: (input: { assetId: string; name: string }) => Promise<DriveAsset>;
  renameFolder: (input: { folderId: string; name: string }) => Promise<DriveFolder>;
  search: (input: { cursor?: string | null; folderId: string | null; limit?: number; query: string }) => Promise<DriveSearchResponse>;
  thumbnailUrl: (assetId: string) => string;
  uploadFiles: (input: { files: File[]; folderId: string | null }) => Promise<DriveAsset[]>;
};

export const driveApi: DriveApi = {
  createFolder({ name, parentId }) {
    return apiClient.request<DriveFolder>("/drive/folders", {
      body: { name, parent_id: parentId },
      method: "POST",
    });
  },
  deleteAsset(assetId) {
    return apiClient.request<DriveAsset>(`/assets/${encodeURIComponent(assetId)}`, { method: "DELETE" });
  },
  deleteFolder(folderId) {
    return apiClient.request<DriveFolder>(`/drive/folders/${encodeURIComponent(folderId)}`, { method: "DELETE" });
  },
  downloadUrl(assetId) {
    return absoluteApiPath(`/assets/${encodeURIComponent(assetId)}/download`);
  },
  listItems({ cursor, folderId, limit = 100 }) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (folderId) {
      params.set("folder_id", folderId);
    }
    if (cursor) {
      params.set("cursor", cursor);
    }

    return apiClient.request<DriveItemsResponse>(`/drive/items?${params.toString()}`);
  },
  moveAsset({ assetId, folderId }) {
    return apiClient.request<DriveAsset>(`/drive/items/${encodeURIComponent(assetId)}/move`, {
      body: { folder_id: folderId },
      method: "POST",
    });
  },
  moveFolder({ folderId, parentId }) {
    return apiClient.request<DriveFolder>(`/drive/folders/${encodeURIComponent(folderId)}`, {
      body: { parent_id: parentId },
      method: "PATCH",
    });
  },
  previewUrl(assetId) {
    return absoluteApiPath(`/assets/${encodeURIComponent(assetId)}/preview`);
  },
  renameAsset({ assetId, name }) {
    return apiClient.request<DriveAsset>(`/drive/items/${encodeURIComponent(assetId)}`, {
      body: { name },
      method: "PATCH",
    });
  },
  renameFolder({ folderId, name }) {
    return apiClient.request<DriveFolder>(`/drive/folders/${encodeURIComponent(folderId)}`, {
      body: { name },
      method: "PATCH",
    });
  },
  search({ cursor, folderId, limit = 50, query }) {
    const params = new URLSearchParams({ limit: String(limit), q: query });
    if (folderId) {
      params.set("folder_id", folderId);
    }
    if (cursor) {
      params.set("cursor", cursor);
    }

    return apiClient.request<DriveSearchResponse>(`/search?${params.toString()}`);
  },
  thumbnailUrl(assetId) {
    return absoluteApiPath(`/assets/${encodeURIComponent(assetId)}/thumbnail`);
  },
  async uploadFiles({ files, folderId }) {
    const uploads = files.map((file) => {
      const body = new FormData();
      body.set("file", file);
      body.set("mode", "drive");
      if (folderId) {
        body.set("folder_id", folderId);
      }

      return apiClient.request<DriveAsset>("/assets/upload", {
        body,
        method: "POST",
      });
    });

    return Promise.all(uploads);
  },
};

export { absoluteApiPath };
