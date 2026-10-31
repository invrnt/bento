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
