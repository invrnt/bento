import { absoluteApiPath, apiClient } from "./client";
import type { ApiClient } from "./client";

// `orchestration/api/smart-search-contract.md` (Stage 23) is the source of truth for these shapes.

export type SmartSearchState = "off" | "downloading" | "paused" | "verifying" | "starting" | "indexing" | "ready" | "error";
export type SmartSearchErrorCode = "download" | "checksum" | "space" | "runtime";

/** Worker job types added by Stage 24 (`model_download`) and the vector index migration (`reembed`). */
export type SmartSearchJobType = "model_download" | "reembed";

export type SmartSearchModelOffer = {
  dims: number;
  display_name: string;
  download_host: string;
  license_spdx: string;
  /** API-relative path of the shipped license text (`text/plain`). */
  license_url: string;
  model_id: string;
  size_bytes: number;
};

export type SmartSearchStatus = {
  download: { bytes_done: number; bytes_total: number };
  error_code: SmartSearchErrorCode | null;
  failed_step: SmartSearchState | null;
  free_bytes: number | null;
  indexing: { done: number; total: number };
  /** An environment override controls the feature: the switch is read-only. */
  locked: boolean;
  model: SmartSearchModelOffer | null;
  search_available: boolean;
  space_id: string | null;
  state: SmartSearchState;
  update_available: { revision: string; size_bytes: number } | null;
  /** Only ever `true` during `downloading`. */
  waiting_network: boolean;
};

export type SmartSearchActivation = { dims?: number; model_id?: string };

/** `409 smart_search_no_space` details. */
export type SmartSearchNoSpaceDetails = { free_bytes: number; required_bytes: number };

export const smartSearchErrorCodes = {
  invalidModelSpec: "invalid_model_spec",
  locked: "settings_source_locked",
  noSpace: "smart_search_no_space",
  stateConflict: "smart_search_state_conflict",
} as const;

export function getSmartSearchStatus(client: ApiClient = apiClient): Promise<SmartSearchStatus> {
  return client.request<SmartSearchStatus>("/smart-search");
}

/** `off → downloading`; both fields default to the manifest's recommendation. */
export function activateSmartSearch(activation: SmartSearchActivation = {}, client: ApiClient = apiClient): Promise<SmartSearchStatus> {
  return client.request<SmartSearchStatus>("/smart-search/activate", { body: activation, method: "POST" });
}

export function pauseSmartSearch(client: ApiClient = apiClient): Promise<SmartSearchStatus> {
  return client.request<SmartSearchStatus>("/smart-search/pause", { method: "POST" });
}

export function resumeSmartSearch(client: ApiClient = apiClient): Promise<SmartSearchStatus> {
  return client.request<SmartSearchStatus>("/smart-search/resume", { method: "POST" });
}

/** `error → failed step`; after a checksum error the download restarts from zero. */
export function retrySmartSearch(client: ApiClient = apiClient): Promise<SmartSearchStatus> {
  return client.request<SmartSearchStatus>("/smart-search/retry", { method: "POST" });
}

/** Stops the work, deletes partial files and returns to `off`. */
export function cancelSmartSearch(client: ApiClient = apiClient): Promise<SmartSearchStatus> {
  return client.request<SmartSearchStatus>("/smart-search/cancel", { method: "POST" });
}

/** Downloads the manifest's newer revision; the installed one keeps serving search until the flip. */
export function updateSmartSearchModel(client: ApiClient = apiClient): Promise<SmartSearchStatus> {
  return client.request<SmartSearchStatus>("/smart-search/update", { method: "POST" });
}

/** Stops the runtime, deletes the model files and this space's vectors, returns to `off`. */
export function removeSmartSearchModel(client: ApiClient = apiClient): Promise<SmartSearchStatus> {
  return client.request<SmartSearchStatus>("/smart-search/model", { method: "DELETE" });
}

/** Absolute URL of the shipped license text, for a link that opens outside the app. */
export function smartSearchLicenseHref(model: Pick<SmartSearchModelOffer, "license_url">, client: Pick<ApiClient, "baseUrl"> = apiClient): string {
  return absoluteApiPath(model.license_url, client);
}

// EmbeddingGemma's model card asks deployments to follow Google's use policy (decision D2).
const usePolicies: Array<{ prefix: string; url: string }> = [
  { prefix: "embeddinggemma", url: "https://ai.google.dev/gemma/prohibited_use_policy" },
];

/** The publisher's use policy for a model, when its card names one. */
export function smartSearchUsePolicyUrl(modelId: string): string | null {
  return usePolicies.find((policy) => modelId.startsWith(policy.prefix))?.url ?? null;
}
