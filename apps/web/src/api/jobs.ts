import { apiClient } from "./client";
import type { ApiClient } from "./client";

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "retrying";

export type JobType =
  | "thumbnail"
  | "metadata"
  | "ocr"
  | "embedding"
  | "pdf_thumbnail"
  | "video_thumbnail"
  | "reindex"
  | "telegram_import"
  | "journal_export"
  | "model_download"
  | "reembed";

export type JobRecord = {
  asset_id?: string | null;
  attempts: number;
  created_at: string;
  error?: string | null;
  id: string;
  max_attempts: number;
  priority: number;
  status: JobStatus;
  type: JobType;
  updated_at: string;
};

export type JobsListResponse = {
  items: JobRecord[];
  next_cursor?: string | null;
};

export type ListJobsParams = {
  cursor?: string | null;
  limit?: number;
};

export type ReindexResponse = {
  enqueued?: number;
  job_ids?: string[];
};

export function listJobs(params: ListJobsParams = {}, client: ApiClient = apiClient): Promise<JobsListResponse> {
  return client.request<JobsListResponse>("/jobs", { query: params });
}

export function retryJob(jobId: string, client: ApiClient = apiClient): Promise<JobRecord> {
  return client.request<JobRecord>(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
}

export function enqueueReindex(client: ApiClient = apiClient): Promise<ReindexResponse> {
  return client.request<ReindexResponse>("/admin/reindex", { method: "POST" });
}
