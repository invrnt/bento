import { useCallback, useEffect, useRef, useState } from "react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import {
  getAccount,
  startPhoneLogin,
  startQrLogin,
  submitLoginCode,
  submitLoginPassword,
} from "../../api/account";
import type { AccountStatus, TelegramAccount } from "../../api/account";
import type { ApiErrorBody } from "../../api/qr";
import { apiErrorBody, retryAfterSeconds } from "../onboarding/apiErrors";

export type LoginView = "qr" | "phone" | "code" | "password";

export type TelegramLoginOptions = {
  client?: ApiClient;
  onAuthorized: (account: TelegramAccount) => void;
  /** How often to check whether the QR was scanned. */
  pollIntervalMs?: number;
  /** Telegram login tokens last about 30 s; refresh a little earlier. */
  qrRefreshMs?: number;
};

export type TelegramLogin = {
  busy: boolean;
  error: ApiErrorBody | null;
  /** Epoch ms until which Telegram asked to wait (flood wait). */
  retryAt: number | null;
  retry: () => void;
  status: AccountStatus | null;
  submitCode: (code: string) => void;
  submitPassword: (password: string) => void;
  submitPhone: (phone: string) => void;
  switchToPhone: () => void;
  switchToQr: () => void;
  view: LoginView;
};

const fallbackError: ApiErrorBody = { code: "request_failed", message: "" };

export function useTelegramLogin({
  client = apiClient,
  onAuthorized,
  pollIntervalMs = 1500,
  qrRefreshMs = 25_000,
}: TelegramLoginOptions): TelegramLogin {
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [view, setView] = useState<LoginView>("qr");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [retryAt, setRetryAt] = useState<number | null>(null);
  const authorized = useRef(false);
  const onAuthorizedRef = useRef(onAuthorized);
  onAuthorizedRef.current = onAuthorized;
  const viewRef = useRef(view);
  viewRef.current = view;

  const fail = useCallback((body: ApiErrorBody | null) => {
    const resolved = body ?? fallbackError;
    setError(resolved);
    const wait = retryAfterSeconds(resolved);
    setRetryAt(wait ? Date.now() + wait * 1000 : null);
  }, []);

  const apply = useCallback(
    (next: AccountStatus) => {
      if (authorized.current) return;
      setStatus((current) =>
        next.step === "qr_pending" && !next.qr && current?.qr ? { ...next, qr: current.qr, qr_expires_at: current.qr_expires_at } : next,
      );
      if (next.step === "authorized" && next.account) {
        authorized.current = true;
        onAuthorizedRef.current(next.account);
        return;
      }
      if (next.step === "code_required") setView("code");
      if (next.step === "password_required") setView("password");
      if (next.error) fail(next.error);
    },
    [fail],
  );

  const run = useCallback(
    async (action: () => Promise<AccountStatus>, quiet = false) => {
      if (!quiet) {
        setBusy(true);
        setError(null);
        setRetryAt(null);
      }
      try {
        apply(await action());
      } catch (caught) {
        fail(apiErrorBody(caught));
      } finally {
        if (!quiet) setBusy(false);
      }
    },
    [apply, fail],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const current = await getAccount(client);
        if (cancelled) return;
        if (current.step === "authorized" || current.step === "code_required" || current.step === "password_required") {
          apply(current);
          return;
        }
      } catch {
        // Fall through to a fresh QR login.
      }
      if (!cancelled) await run(() => startQrLogin(client));
    })();
    return () => {
      cancelled = true;
    };
    // Start once per mount; later steps are driven by the person.
  }, []);

  const pending = view === "qr" && status?.step === "qr_pending";

  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => {
      void getAccount(client)
        .then((next) => {
          if (viewRef.current === "qr" && next.step !== "signed_out") apply(next);
        })
        .catch(() => undefined);
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [apply, client, pending, pollIntervalMs]);

  const expiresAt = status?.qr_expires_at ?? null;
  useEffect(() => {
    if (!pending) return;
    const untilExpiry = expiresAt ? new Date(expiresAt).getTime() - Date.now() - 1500 : qrRefreshMs;
    const delay = Math.max(Math.min(1000, qrRefreshMs), Math.min(qrRefreshMs, untilExpiry));
    const timer = setTimeout(() => void run(() => startQrLogin(client), true), delay);
    return () => clearTimeout(timer);
  }, [client, expiresAt, pending, qrRefreshMs, run, status?.qr]);

  return {
    busy,
    error,
    retry: () => {
      if (viewRef.current === "qr") void run(() => startQrLogin(client));
      else {
        setError(null);
        setRetryAt(null);
      }
    },
    retryAt,
    status,
    submitCode: (code) => void run(() => submitLoginCode(code.replace(/\s+/g, ""), client)),
    submitPassword: (password) => void run(() => submitLoginPassword(password, client)),
    submitPhone: (phone) => void run(() => startPhoneLogin(phone.replace(/[^\d+]/g, ""), client)),
    switchToPhone: () => {
      setError(null);
      setRetryAt(null);
      setView("phone");
    },
    switchToQr: () => {
      setView("qr");
      void run(() => startQrLogin(client));
    },
    view,
  };
}
