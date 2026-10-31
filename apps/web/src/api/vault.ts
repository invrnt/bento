import { apiClient } from "./client";
import type { ApiClient } from "./client";
import type { QrMatrix } from "./qr";

export type VaultState = "local_only" | "signed_out" | "no_vault" | "locked" | "bootstrapping" | "ready";

export type VaultStatus = {
  created_at: string | null;
  devices_count: number;
  other_vaults: number;
  recovery_kit_saved: boolean;
  state: VaultState;
  usage: { bytes: number; files: number };
  vault_id: string | null;
};

export type CreatedVault = { recovery_code: string; recovery_qr?: QrMatrix; vault: VaultStatus };

export function getVault(client: ApiClient = apiClient): Promise<VaultStatus> {
  return client.request<VaultStatus>("/vault");
}

export function createVault(client: ApiClient = apiClient): Promise<CreatedVault> {
  return client.request<CreatedVault>("/vault", { method: "POST" });
}

export function unlockVault(recoveryCode: string, client: ApiClient = apiClient): Promise<VaultStatus> {
  return client.request<VaultStatus>("/vault/unlock", { body: { recovery_code: recoveryCode }, method: "POST" });
}

export function rotateRecoveryCode(
  client: ApiClient = apiClient,
): Promise<{ recovery_code: string; recovery_qr?: QrMatrix }> {
  return client.request<{ recovery_code: string; recovery_qr?: QrMatrix }>("/vault/recovery-code", { method: "POST" });
}

export function confirmRecoveryKit(lastGroup: string, client: ApiClient = apiClient): Promise<VaultStatus> {
  return client.request<VaultStatus>("/vault/recovery-code/confirm", { body: { last_group: lastGroup }, method: "POST" });
}

export function verifyRecoveryCode(recoveryCode: string, client: ApiClient = apiClient): Promise<{ valid: boolean }> {
  return client.request<{ valid: boolean }>("/vault/recovery-code/verify", {
    body: { recovery_code: recoveryCode },
    method: "POST",
  });
}
