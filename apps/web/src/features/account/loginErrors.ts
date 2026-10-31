import type { ApiErrorBody } from "../../api/qr";
import type { MessageKey } from "../../i18n/dictionary";

const loginErrorKeys: Record<string, MessageKey> = {
  network_error: "signIn.error.network",
  telegram_code_invalid: "signIn.error.codeInvalid",
  telegram_login_expired: "signIn.error.expired",
  telegram_network: "signIn.error.network",
  telegram_not_available: "signIn.error.notAvailable",
  telegram_password_invalid: "signIn.error.passwordInvalid",
  telegram_phone_invalid: "signIn.error.phoneInvalid",
};

export function loginErrorKey(error: ApiErrorBody | null): MessageKey {
  return (error && loginErrorKeys[error.code]) || "signIn.error.generic";
}
