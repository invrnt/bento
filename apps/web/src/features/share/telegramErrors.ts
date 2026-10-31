import { ApiError } from "../../api/client";
import { t } from "../../i18n/dictionary";
import { formatDuration, formatMessage } from "../../lib/format";

type ErrorBody = { code?: unknown; details?: unknown };

function errorBody(error: unknown): ErrorBody | null {
  if (!(error instanceof ApiError) || typeof error.details !== "object" || error.details === null) {
    return null;
  }

  const body = (error.details as { error?: unknown }).error;
  return typeof body === "object" && body !== null ? (body as ErrorBody) : null;
}

/** Plain-language message for Telegram failures (flood wait, not connected, network). */
export function telegramErrorMessage(error: unknown): string {
  const body = errorBody(error);
  const code = typeof body?.code === "string" ? body.code : null;

  if (code === "telegram_flood_wait") {
    const details = typeof body?.details === "object" && body.details !== null ? (body.details as Record<string, unknown>) : {};
    const seconds = typeof details.retry_after_seconds === "number" ? details.retry_after_seconds : null;
    const duration = formatDuration(seconds);
    return duration ? formatMessage("telegram.error.floodWait", { duration }) : t("telegram.error.generic");
  }

  if (
    code === "telegram_not_available" ||
    code === "telegram_not_configured" ||
    code === "telegram_not_authorized" ||
    (error instanceof ApiError && error.status === 503)
  ) {
    return t("telegram.error.notConnected");
  }

  if (code === "telegram_network") {
    return t("telegram.error.network");
  }

  return t("telegram.error.generic");
}
