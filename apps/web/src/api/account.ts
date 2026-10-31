import { apiClient } from "./client";
import type { ApiClient } from "./client";
import type { ApiErrorBody, QrMatrix } from "./qr";

export type LoginStep = "signed_out" | "qr_pending" | "code_required" | "password_required" | "authorized" | "failed";

export type TelegramAccount = {
  display_name: string;
  phone_masked: string | null;
  premium: boolean;
  user_id: number;
  username: string | null;
};

export type AccountStatus = {
  account: TelegramAccount | null;
  error: ApiErrorBody | null;
  password_hint: string | null;
  qr: QrMatrix | null;
  qr_expires_at: string | null;
  qr_url: string | null;
  step: LoginStep;
};

export function getAccount(client: ApiClient = apiClient): Promise<AccountStatus> {
  return client.request<AccountStatus>("/account");
}

export function startQrLogin(client: ApiClient = apiClient): Promise<AccountStatus> {
  return client.request<AccountStatus>("/account/login/qr", { method: "POST" });
}

export function startPhoneLogin(phone: string, client: ApiClient = apiClient): Promise<AccountStatus> {
  return client.request<AccountStatus>("/account/login/phone", { body: { phone }, method: "POST" });
}

export function submitLoginCode(code: string, client: ApiClient = apiClient): Promise<AccountStatus> {
  return client.request<AccountStatus>("/account/login/code", { body: { code }, method: "POST" });
}

export function submitLoginPassword(password: string, client: ApiClient = apiClient): Promise<AccountStatus> {
  return client.request<AccountStatus>("/account/login/password", { body: { password }, method: "POST" });
}

export function logout(client: ApiClient = apiClient): Promise<AccountStatus> {
  return client.request<AccountStatus>("/account/logout", { method: "POST" });
}

export const accountAvatarPath = "/api/account/avatar";
