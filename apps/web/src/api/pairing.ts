import { apiClient } from "./client";
import type { ApiClient } from "./client";
import type { ApiErrorBody, QrMatrix } from "./qr";

export type PairingState =
  | "waiting"
  | "connected"
  | "awaiting_approval"
  | "approving"
  | "needs_telegram_login"
  | "bootstrapping"
  | "completed"
  | "rejected"
  | "failed"
  | "expired"
  | "cancelled";

/** What a Sync-channel guest shows next to the emojis. `devices_count` is the other device's unverified claim. */
export type PairingVault = { created_at: string | null; devices_count: number | null };

export type Pairing = {
  code: string | null;
  error: ApiErrorBody | null;
  expires_at: string;
  id: string;
  link: string | null;
  peer: { device_name: string; platform: string } | null;
  qr: QrMatrix | null;
  role: "host" | "guest";
  sas: string[] | null;
  state: PairingState;
  telegram_qr: QrMatrix | null;
  transport: "relay" | "telegram";
  vault: PairingVault | null;
  web_link: string | null;
};

export type PairingRequest = { created_at: string; device_name: string; id: string; platform: string };

export const terminalPairingStates: ReadonlySet<PairingState> = new Set([
  "completed",
  "rejected",
  "failed",
  "expired",
  "cancelled",
]);

const path = (id: string, suffix = "") => `/pairing/${encodeURIComponent(id)}${suffix}`;

export function hostPairing(client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>("/pairing/host", { method: "POST" });
}

export function joinPairing(code: string, client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>("/pairing/join", { body: { code }, method: "POST" });
}

export function requestPairingViaTelegram(client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>("/pairing/request", { method: "POST" });
}

export function getPairing(id: string, client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>(path(id));
}

export function approvePairing(id: string, client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>(path(id, "/approve"), { method: "POST" });
}

/** Sync-channel guest: the emojis match the other device, so accept its access (relay guests never confirm). */
export function confirmPairing(id: string, client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>(path(id, "/confirm"), { method: "POST" });
}

/** A guest of the Sync-channel fallback must confirm the emojis itself before it accepts any access. */
export function needsGuestConfirmation(pairing: Pairing): boolean {
  return pairing.role === "guest" && pairing.transport === "telegram" && pairing.state === "awaiting_approval" && pairing.sas !== null;
}

export function rejectPairing(id: string, client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>(path(id, "/reject"), { method: "POST" });
}

export function cancelPairing(id: string, client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>(path(id), { method: "DELETE" });
}

export function listPairingRequests(client: ApiClient = apiClient): Promise<{ items: PairingRequest[] }> {
  return client.request<{ items: PairingRequest[] }>("/pairing/requests");
}

export function reviewPairingRequest(id: string, client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>(`/pairing/requests/${encodeURIComponent(id)}/review`, { method: "POST" });
}

export function approvePairingRequest(id: string, client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>(`/pairing/requests/${encodeURIComponent(id)}/approve`, { method: "POST" });
}

export function rejectPairingRequest(id: string, client: ApiClient = apiClient): Promise<Pairing> {
  return client.request<Pairing>(`/pairing/requests/${encodeURIComponent(id)}/reject`, { method: "POST" });
}
