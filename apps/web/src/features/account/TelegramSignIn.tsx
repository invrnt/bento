import { useState } from "react";
import type { FormEvent } from "react";
import { Hourglass, Phone, QrCode as QrCodeIcon, RefreshCw, RotateCw } from "lucide-react";

import type { ApiClient } from "../../api/client";
import type { TelegramAccount } from "../../api/account";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Input } from "../../components/Input";
import { QrCode } from "../../components/QrCode";
import { Spinner } from "../../components/Spinner";
import { t } from "../../i18n/dictionary";
import { formatClock, formatDuration, tf } from "../onboarding/format";
import { retryAfterSeconds } from "../onboarding/apiErrors";
import { useSecondsLeft } from "../onboarding/useNow";
import { loginErrorKey } from "./loginErrors";
import { useTelegramLogin } from "./useTelegramLogin";

export type TelegramSignInProps = {
  client?: ApiClient;
  onAuthorized: (account: TelegramAccount) => void;
  pollIntervalMs?: number;
  qrRefreshMs?: number;
};

/** "Conecta tu Telegram": QR that refreshes itself, with phone → code → 2FA as the alternative. */
export function TelegramSignIn({ client, onAuthorized, pollIntervalMs, qrRefreshMs }: TelegramSignInProps) {
  const login = useTelegramLogin({ client, onAuthorized, pollIntervalMs, qrRefreshMs });
  const secondsLeft = useSecondsLeft(login.retryAt);
  const waiting = secondsLeft > 0;
  const blocked = login.busy || waiting;

  return (
    <div className="grid gap-5">
      {login.view === "qr" ? <QrView login={login} /> : null}
      {login.view === "phone" ? <PhoneForm blocked={blocked} busy={login.busy} onSubmit={login.submitPhone} /> : null}
      {login.view === "code" ? (
        <CodeForm
          blocked={blocked}
          busy={login.busy}
          onChangeNumber={login.switchToPhone}
          onSubmit={login.submitCode}
          phoneMasked={login.status?.account?.phone_masked ?? null}
        />
      ) : null}
      {login.view === "password" ? (
        <PasswordForm blocked={blocked} busy={login.busy} hint={login.status?.password_hint ?? null} onSubmit={login.submitPassword} />
      ) : null}

      {login.error ? (
        login.error.code === "telegram_flood_wait" ? (
          <Callout icon={<Hourglass />} role="status" title={t("signIn.flood.title")} tone="warning">
            {waiting
              ? tf("signIn.flood.body", {
                  clock: formatClock(secondsLeft),
                  time: formatDuration(retryAfterSeconds(login.error) ?? secondsLeft) ?? formatClock(secondsLeft),
                })
              : t("signIn.flood.ready")}
          </Callout>
        ) : (
          <Callout
            action={
              login.view === "qr" ? (
                <Button leadingIcon={<RotateCw />} onClick={login.retry} size="sm">
                  {t("signIn.qr.retry")}
                </Button>
              ) : undefined
            }
            role="alert"
            tone="danger"
          >
            {t(loginErrorKey(login.error))}
          </Callout>
        )
      ) : null}

      <div className="flex flex-wrap gap-2">
        {login.view === "qr" ? (
          <Button leadingIcon={<Phone />} onClick={login.switchToPhone} variant="ghost">
            {t("signIn.usePhone")}
          </Button>
        ) : (
          <Button leadingIcon={<QrCodeIcon />} onClick={login.switchToQr} variant="ghost">
            {t("signIn.useQr")}
          </Button>
        )}
      </div>
    </div>
  );
}

function QrView({ login }: { login: ReturnType<typeof useTelegramLogin> }) {
  const qr = login.status?.qr ?? null;
  const steps = [t("signIn.qr.step1"), t("signIn.qr.step2"), t("signIn.qr.step3")];

  return (
    <div className="grid gap-6 sm:grid-cols-[12.5rem_minmax(0,1fr)] sm:items-center">
      <div className="mx-auto w-full max-w-[12.5rem]">
        <div className="rounded-xl border border-line bg-white p-1.5 shadow-xs">
          {qr ? (
            <QrCode label={t("signIn.qr.label")} matrix={qr} />
          ) : (
            <div aria-label={t("signIn.qr.loading")} className="grid aspect-square place-items-center rounded-lg bg-sunken text-ink-subtle" role="status">
              <Spinner />
            </div>
          )}
        </div>
        <p className="mt-2.5 flex items-center justify-center gap-1.5 text-xs text-ink-subtle">
          <RefreshCw aria-hidden="true" className="size-3.5" />
          {t("signIn.qr.refreshes")}
        </p>
      </div>
      <div className="min-w-0">
        <ol className="grid gap-3.5">
          {steps.map((step, index) => (
            <li className="flex gap-3 text-base text-ink" key={step}>
              <span
                aria-hidden="true"
                className="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold tabular-nums text-accent-ink"
              >
                {index + 1}
              </span>
              <span className="pt-0.5">{step}</span>
            </li>
          ))}
        </ol>
        <p aria-live="polite" className="mt-5 flex items-center gap-2 text-sm text-ink-muted">
          {qr ? (
            <>
              <Spinner className="size-3.5 text-accent-ink" />
              {t("signIn.qr.waiting")}
            </>
          ) : null}
        </p>
      </div>
    </div>
  );
}

type FormProps = { blocked: boolean; busy: boolean };

function PhoneForm({ blocked, busy, onSubmit }: FormProps & { onSubmit: (phone: string) => void }) {
  const [phone, setPhone] = useState("");
  const valid = phone.replace(/\D/g, "").length >= 7;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid && !blocked) onSubmit(phone);
  }

  return (
    <form className="grid max-w-sm gap-4" onSubmit={submit}>
      <Input
        autoComplete="tel"
        autoFocus
        hint={t("signIn.phone.hint")}
        inputMode="tel"
        label={t("signIn.phone.label")}
        onChange={(event) => setPhone(event.target.value)}
        placeholder={t("signIn.phone.placeholder")}
        type="tel"
        value={phone}
      />
      <Button className="justify-self-start" disabled={!valid || blocked} loading={busy} type="submit" variant="primary">
        {t("signIn.phone.submit")}
      </Button>
    </form>
  );
}

function CodeForm({
  blocked,
  busy,
  onChangeNumber,
  onSubmit,
  phoneMasked,
}: FormProps & { onChangeNumber: () => void; onSubmit: (code: string) => void; phoneMasked: string | null }) {
  const [code, setCode] = useState("");
  const valid = code.replace(/\D/g, "").length >= 5;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid && !blocked) onSubmit(code);
  }

  return (
    <form className="grid max-w-sm gap-4" onSubmit={submit}>
      <Input
        autoComplete="one-time-code"
        autoFocus
        className="font-mono tracking-[0.2em]"
        hint={phoneMasked ? tf("signIn.code.hintPhone", { phone: phoneMasked }) : t("signIn.code.hint")}
        inputMode="numeric"
        label={t("signIn.code.label")}
        maxLength={8}
        onChange={(event) => setCode(event.target.value.replace(/[^\d]/g, ""))}
        value={code}
      />
      <div className="flex flex-wrap gap-2">
        <Button disabled={!valid || blocked} loading={busy} type="submit" variant="primary">
          {t("signIn.code.submit")}
        </Button>
        <Button onClick={onChangeNumber} variant="ghost">
          {t("signIn.code.changeNumber")}
        </Button>
      </div>
    </form>
  );
}

function PasswordForm({ blocked, busy, hint, onSubmit }: FormProps & { hint: string | null; onSubmit: (password: string) => void }) {
  const [password, setPassword] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (password && !blocked) onSubmit(password);
  }

  return (
    <form className="grid max-w-sm gap-4" onSubmit={submit}>
      <p className="text-base text-ink-muted">{t("signIn.password.body")}</p>
      <Input
        autoComplete="current-password"
        autoFocus
        hint={hint ? tf("signIn.password.hint", { hint }) : undefined}
        label={t("signIn.password.label")}
        onChange={(event) => setPassword(event.target.value)}
        type="password"
        value={password}
      />
      <Button className="justify-self-start" disabled={!password || blocked} loading={busy} type="submit" variant="primary">
        {t("signIn.password.submit")}
      </Button>
    </form>
  );
}
