import type { MessageKey } from "../../i18n/dictionary";

export type PairingProblem = "wrongCode" | "notFound" | "relayUnavailable" | "rateLimited" | "telegramLogin" | "network" | "generic";

/** Groups backend/relay error codes into the few situations a person can act on. */
export function pairingProblem(code: string | null | undefined): PairingProblem {
  const value = (code ?? "").toLowerCase();
  if (!value) return "generic";
  if (value.includes("relay") || value === "pairing_unavailable" || value === "storage_unavailable") return "relayUnavailable";
  if (value.includes("rate_limit") || value.includes("flood")) return "rateLimited";
  if (value.includes("room_not_found") || value.includes("not_found") || value.includes("expired")) return "notFound";
  if (value.includes("telegram_login") || value.includes("login_failed")) return "telegramLogin";
  if (value.includes("network") || value.includes("timeout") || value.includes("offline")) return "network";
  if (value.includes("code") || value.includes("mismatch") || value.includes("confirm") || value.includes("spake") || value.includes("protocol")) {
    return "wrongCode";
  }
  return "generic";
}

export const pairingProblemKeys: Record<PairingProblem, MessageKey> = {
  generic: "pairing.problem.generic",
  network: "pairing.problem.network",
  notFound: "pairing.problem.notFound",
  rateLimited: "pairing.problem.rateLimited",
  relayUnavailable: "pairing.problem.relayUnavailable",
  telegramLogin: "pairing.problem.telegramLogin",
  wrongCode: "pairing.problem.wrongCode",
};
