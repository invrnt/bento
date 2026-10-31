import { ApiError } from "../../api/client";
import type { ApiErrorBody } from "../../api/qr";

/** Reads `{error: {code, message, details}}` from a failed request, if present. */
export function apiErrorBody(error: unknown): ApiErrorBody | null {
  if (error instanceof ApiError) {
    const details = error.details as { error?: Partial<ApiErrorBody> } | null;
    const body = details && typeof details === "object" ? details.error : undefined;
    if (body && typeof body.code === "string") {
      return { code: body.code, details: body.details ?? {}, message: body.message ?? "" };
    }
    return { code: error.status >= 500 ? "server_error" : "request_failed", details: {}, message: error.message };
  }
  if (error instanceof TypeError) return { code: "network_error", details: {}, message: error.message };
  return null;
}

export function errorCode(error: unknown): string | null {
  return apiErrorBody(error)?.code ?? null;
}

export function retryAfterSeconds(body: ApiErrorBody | null): number | null {
  const value = body?.details?.retry_after_seconds;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}
