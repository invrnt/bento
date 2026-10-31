import { useEffect, useRef, useState } from "react";
import { ArrowLeft, CircleCheck, Cloud, Inbox, LockKeyhole, MonitorSmartphone, MousePointerClick, Search } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { getAccount } from "../../api/account";
import type { TelegramAccount } from "../../api/account";
import { createVault, getVault } from "../../api/vault";
import type { VaultStatus } from "../../api/vault";
import type { QrMatrix } from "../../api/qr";
import { BentoLoader, BrandMark } from "../../components/BrandMark";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Kbd } from "../../components/Kbd";
import { t } from "../../i18n/dictionary";
import { AccountAvatar } from "../account/AccountAvatar";
import { TelegramSignIn } from "../account/TelegramSignIn";
import { RecoveryKit } from "../recovery/RecoveryKit";
import { recoveryQrFrom } from "../recovery/recoveryCode";
import { errorCode } from "./apiErrors";
import { BackupStep } from "./BackupStep";
import { isLaunchAtLoginError, setDesktopPreferences } from "./desktopHost";
import { tf } from "./format";
import { chooseLocalMode, forgetLocalMode } from "./localMode";
import { HeroIcon, SetupFrame } from "./SetupFrame";

export type FirstRunStep = "welcome" | "telegram" | "creating" | "backup" | "kit" | "done";

export type FirstRunProps = {
  client?: ApiClient;
  initialStep?: Extract<FirstRunStep, "welcome" | "telegram" | "creating">;
  loginPollIntervalMs?: number;
  /** The Telegram account already has a vault: continue with the join/recovery choice. */
  onExistingVault: () => void;
  onFinish: () => void;
  /** "Ya uso Bento en otro dispositivo". */
  onJoin: () => void;
  onLocalOnly: () => void;
  qrRefreshMs?: number;
};

const numbered: Partial<Record<FirstRunStep, number>> = { backup: 3, creating: 2, done: 5, kit: 4, telegram: 1 };
const totalSteps = 5;

/** Bienvenida → Conecta tu Telegram → Creando tu nube → Elige qué respaldar → Kit de recuperación → Listo. */
export function FirstRun({
  client = apiClient,
  initialStep = "welcome",
  loginPollIntervalMs,
  onExistingVault,
  onFinish,
  onJoin,
  onLocalOnly,
  qrRefreshMs,
}: FirstRunProps) {
  const [step, setStep] = useState<FirstRunStep>(initialStep);
  const [account, setAccount] = useState<TelegramAccount | null>(null);
  const [vault, setVault] = useState<VaultStatus | null>(null);
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);
  const [recoveryQr, setRecoveryQr] = useState<QrMatrix | null>(null);
  const [leaving, setLeaving] = useState(false);
  const steps = numbered[step] ? { current: numbered[step]!, total: totalSteps } : undefined;

  async function keepLocal() {
    setLeaving(true);
    await chooseLocalMode(client);
    setLeaving(false);
    onLocalOnly();
  }

  function finish() {
    forgetLocalMode();
    onFinish();
  }

  if (step === "welcome") {
    return <WelcomeStep leaving={leaving} onJoin={onJoin} onLocalOnly={() => void keepLocal()} onStart={() => setStep("telegram")} />;
  }

  if (step === "telegram") {
    return (
      <SetupFrame
        description={t("firstRun.telegram.body")}
        footer={
          <Button leadingIcon={<ArrowLeft />} onClick={() => setStep("welcome")} variant="ghost">
            {t("setup.back")}
          </Button>
        }
        stepKey="telegram"
        steps={steps}
        title={t("firstRun.telegram.title")}
      >
        <TelegramSignIn
          client={client}
          onAuthorized={(next) => {
            setAccount(next);
            setStep("creating");
          }}
          pollIntervalMs={loginPollIntervalMs}
          qrRefreshMs={qrRefreshMs}
        />
      </SetupFrame>
    );
  }

  if (step === "creating") {
    return (
      <CreatingStep
        account={account}
        client={client}
        onCreated={(created, code, qr) => {
          setVault(created);
          setRecoveryCode(code);
          setRecoveryQr(qr);
          setStep("backup");
        }}
        onExistingVault={onExistingVault}
        steps={steps!}
      />
    );
  }

  if (step === "backup") {
    return <BackupStep client={client} onNext={() => setStep(recoveryCode ? "kit" : "done")} steps={steps!} />;
  }

  if (step === "kit" && recoveryCode) {
    return (
      <SetupFrame description={t("firstRun.kit.body")} stepKey="kit" steps={steps} title={t("firstRun.kit.title")}>
        <RecoveryKit
          accountName={account?.display_name}
          client={client}
          code={recoveryCode}
          createdAt={vault?.created_at}
          onConfirmed={() => setStep("done")}
          onLater={() => setStep("done")}
          qr={recoveryQr}
        />
      </SetupFrame>
    );
  }

  return <DoneStep onFinish={finish} steps={{ current: totalSteps, total: totalSteps }} />;
}

function WelcomeStep({ leaving, onJoin, onLocalOnly, onStart }: { leaving: boolean; onJoin: () => void; onLocalOnly: () => void; onStart: () => void }) {
  const points = [
    { body: t("firstRun.welcome.point1.body"), icon: LockKeyhole, title: t("firstRun.welcome.point1.title") },
    { body: t("firstRun.welcome.point2.body"), icon: Cloud, title: t("firstRun.welcome.point2.title") },
    { body: t("firstRun.welcome.point3.body"), icon: MonitorSmartphone, title: t("firstRun.welcome.point3.title") },
  ];

  return (
    <SetupFrame
      aside={t("firstRun.welcome.legal")}
      description={t("firstRun.welcome.body")}
      eyebrow={t("firstRun.welcome.eyebrow")}
      hero={<BrandMark className="size-14" />}
      showLogo={false}
      stepKey="welcome"
      title={t("firstRun.welcome.title")}
      width="md"
    >
      <ul className="grid gap-3.5">
        {points.map(({ body, icon: Icon, title }) => (
          <li className="flex gap-3" key={title}>
            <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-accent-soft text-accent-ink">
              <Icon className="size-[1.125rem]" strokeWidth={1.75} />
            </span>
            <span className="grid gap-0.5">
              <span className="text-base font-medium text-ink">{title}</span>
              <span className="text-sm text-ink-muted">{body}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-7 grid gap-2.5">
        <Button className="w-full" onClick={onStart} size="lg" variant="primary">
          {t("firstRun.welcome.start")}
        </Button>
        <Button className="w-full" onClick={onJoin} size="lg">
          {t("firstRun.welcome.join")}
        </Button>
        <Button className="justify-self-center" loading={leaving} onClick={onLocalOnly} size="sm" variant="ghost">
          {t("firstRun.welcome.localOnly")}
        </Button>
      </div>
    </SetupFrame>
  );
}

function CreatingStep({
  account: knownAccount,
  client,
  onCreated,
  onExistingVault,
  steps,
}: {
  account: TelegramAccount | null;
  client: ApiClient;
  onCreated: (vault: VaultStatus | null, code: string | null, qr: QrMatrix | null) => void;
  onExistingVault: () => void;
  steps: { current: number; total: number };
}) {
  const [account, setAccount] = useState(knownAccount);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const startedAttempt = useRef<number | null>(null);
  const callbacks = useRef({ onCreated, onExistingVault });
  callbacks.current = { onCreated, onExistingVault };

  useEffect(() => {
    if (knownAccount) return;
    void getAccount(client)
      .then((status) => status.account && setAccount(status.account))
      .catch(() => undefined);
  }, [client, knownAccount]);

  useEffect(() => {
    // Creating a vault is not idempotent: run once per attempt.
    if (startedAttempt.current === attempt) return;
    startedAttempt.current = attempt;
    setFailed(false);
    void (async () => {
      try {
        const current = await getVault(client).catch(() => null);
        if (current?.state === "locked") return callbacks.current.onExistingVault();
        if (current?.state === "ready" || current?.state === "bootstrapping") return callbacks.current.onCreated(current, null, null);
        const created = await createVault(client);
        callbacks.current.onCreated(created.vault, created.recovery_code, recoveryQrFrom(created));
      } catch (caught) {
        if (errorCode(caught) === "vault_already_exists") callbacks.current.onExistingVault();
        else setFailed(true);
      }
    })();
  }, [attempt, client]);

  return (
    <SetupFrame
      description={failed ? t("firstRun.creating.failed") : t("firstRun.creating.body")}
      footer={
        failed ? (
          <Button className="ml-auto" onClick={() => setAttempt((value) => value + 1)} variant="primary">
            {t("common.retry")}
          </Button>
        ) : undefined
      }
      stepKey="creating"
      steps={steps}
      title={t("firstRun.creating.title")}
    >
      <div className="grid gap-5">
        {account ? (
          <div className="flex items-center gap-3 rounded-lg border border-line bg-subtle p-3">
            <AccountAvatar name={account.display_name} revision={account.user_id} />
            <div className="min-w-0">
              <p className="truncate font-medium text-ink">{tf("firstRun.creating.connectedAs", { name: account.display_name })}</p>
              {account.username ? <p className="truncate text-sm text-ink-muted">@{account.username}</p> : null}
            </div>
            <CircleCheck aria-hidden="true" className="ml-auto size-5 shrink-0 text-success-ink" />
          </div>
        ) : null}
        {failed ? (
          <Callout role="alert" tone="danger">
            {t("firstRun.creating.failedHint")}
          </Callout>
        ) : (
          <div aria-live="polite" className="flex items-center gap-4 py-2" role="status">
            <BentoLoader className="size-10" />
            <div className="grid gap-0.5">
              <span className="font-medium text-ink">{t("firstRun.creating.working")}</span>
              <span className="text-sm text-ink-muted">{t("firstRun.creating.detail")}</span>
            </div>
          </div>
        )}
      </div>
    </SetupFrame>
  );
}

function DoneStep({ onFinish, steps }: { onFinish: () => void; steps: { current: number; total: number } }) {
  const [loginItemFailed, setLoginItemFailed] = useState(false);
  const loginItemRequested = useRef(false);

  useEffect(() => {
    // Reaching "Listo" turns on launch at login (desktop only; changeable in Ajustes › General).
    if (loginItemRequested.current) return;
    loginItemRequested.current = true;
    setDesktopPreferences({ launchAtLogin: true }).catch((caught) => {
      if (isLaunchAtLoginError(caught)) setLoginItemFailed(true);
    });
  }, []);

  const apple = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
  const tips = [
    { body: t("firstRun.done.tip.inbox.body"), icon: Inbox, title: t("firstRun.done.tip.inbox.title") },
    { body: t("firstRun.done.tip.drop.body"), icon: MousePointerClick, title: t("firstRun.done.tip.drop.title") },
    { body: null, icon: Search, title: t("firstRun.done.tip.search.title") },
  ];

  return (
    <SetupFrame
      description={t("firstRun.done.body")}
      footer={
        <Button className="ml-auto" onClick={onFinish} size="lg" variant="primary">
          {t("firstRun.done.open")}
        </Button>
      }
      hero={<HeroIcon tone="success"><CircleCheck /></HeroIcon>}
      stepKey="done"
      steps={steps}
      title={t("firstRun.done.title")}
    >
      <ul className="grid gap-3">
        {tips.map(({ body, icon: Icon, title }) => (
          <li className="flex items-start gap-3 rounded-lg border border-line bg-subtle p-3.5" key={title}>
            <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-raised text-accent-ink shadow-xs ring-1 ring-line">
              <Icon className="size-[1.125rem]" strokeWidth={1.75} />
            </span>
            <span className="grid gap-0.5">
              <span className="text-base font-medium text-ink">{title}</span>
              {body ? (
                <span className="text-sm text-ink-muted">{body}</span>
              ) : (
                <span className="flex items-center gap-1.5 text-sm text-ink-muted">
                  {t("firstRun.done.tip.search.body")} <Kbd>{apple ? t("search.shortcutMac") : t("search.shortcut")}</Kbd>
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {loginItemFailed ? (
        <Callout className="mt-4" role="status" tone="neutral">
          {t("firstRun.done.loginItemFailed")}
        </Callout>
      ) : null}
    </SetupFrame>
  );
}
