import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ArrowLeft,
  CircleCheck,
  CloudDownload,
  LifeBuoy,
  MonitorSmartphone,
  ShieldAlert,
  ShieldCheck,
  Timer,
  TriangleAlert,
  Unplug,
  Users,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import {
  cancelPairing,
  confirmPairing,
  joinPairing,
  needsGuestConfirmation,
  requestPairingViaTelegram,
  terminalPairingStates,
} from "../../api/pairing";
import type { Pairing } from "../../api/pairing";
import { getVault, unlockVault } from "../../api/vault";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Input } from "../../components/Input";
import { QrCode } from "../../components/QrCode";
import { Spinner } from "../../components/Spinner";
import { t } from "../../i18n/dictionary";
import { TelegramSignIn } from "../account/TelegramSignIn";
import { errorCode } from "../onboarding/apiErrors";
import { BootstrapMeter } from "../onboarding/BootstrapProgress";
import { ChoiceCard, HeroIcon, SetupFrame } from "../onboarding/SetupFrame";
import { useBootstrapStatus } from "../onboarding/useBootstrapStatus";
import { RecoveryCodeForm } from "../recovery/RecoveryCodeForm";
import { recoveryErrorKey } from "../recovery/recoveryCode";
import { formatPairingInput, isCompletePairingCode } from "./pairingCode";
import { pairingProblem, pairingProblemKeys } from "./pairingErrors";
import type { PairingProblem } from "./pairingErrors";
import { PairingVaultSummary } from "./PairingVaultSummary";
import { SasEmojis } from "./SasEmojis";
import { usePairingSession } from "./usePairingSession";

export type JoinStep = "code" | "pairing" | "signin" | "choose" | "recovery" | "no-vault" | "bootstrap" | "already" | "removed";

export type JoinScreenProps = {
  /** This device is already part of a vault (e.g. a join link opened on a set-up device). */
  alreadyMember?: boolean;
  client?: ApiClient;
  initialCode?: string;
  /** `removed`: another device removed this one; explain it calmly before joining again. */
  initialStep?: Extract<JoinStep, "code" | "choose" | "removed">;
  loginPollIntervalMs?: number;
  onBack?: () => void;
  onCreateVault?: () => void;
  onDone: () => void;
  onLocalOnly?: () => void;
  pollIntervalMs?: number;
  qrRefreshMs?: number;
};

/** New device: join with a code or link, or sign in and use the recovery kit / ask other devices. */
export function JoinScreen({
  alreadyMember = false,
  client = apiClient,
  initialCode = "",
  initialStep = "code",
  loginPollIntervalMs,
  onBack,
  onCreateVault,
  onDone,
  onLocalOnly,
  pollIntervalMs = 1000,
  qrRefreshMs,
}: JoinScreenProps) {
  const [step, setStep] = useState<JoinStep>(alreadyMember ? "already" : initialStep);
  const [code, setCode] = useState(() => formatPairingInput(initialCode));
  const [joining, setJoining] = useState(false);
  const [joinProblem, setJoinProblem] = useState<PairingProblem | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [requestProblem, setRequestProblem] = useState<PairingProblem | null>(null);
  const [unlocking, setUnlocking] = useState(false);
  const [unlockError, setUnlockError] = useState<string | null>(null);
  const [checkingVault, setCheckingVault] = useState(false);
  const [started, setStarted] = useState<Pairing | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmFailed, setConfirmFailed] = useState(false);
  const [mismatch, setMismatch] = useState(false);
  const [recoveryReturn, setRecoveryReturn] = useState<JoinStep>("choose");
  const session = usePairingSession(started, { client, pollIntervalMs });
  const pairing = session.pairing;

  useEffect(() => {
    if (initialCode) setCode(formatPairingInput(initialCode));
  }, [initialCode]);

  useEffect(() => {
    if (step === "pairing" && (pairing?.state === "bootstrapping" || pairing?.state === "completed")) setStep("bootstrap");
  }, [pairing?.state, step]);

  async function join(event: FormEvent) {
    event.preventDefault();
    if (!isCompletePairingCode(code) || joining) return;
    setJoining(true);
    setJoinProblem(null);
    try {
      setStarted(await joinPairing(code, client));
      setStep("pairing");
    } catch (caught) {
      setJoinProblem(pairingProblem(errorCode(caught)));
    } finally {
      setJoining(false);
    }
  }

  async function requestAccess() {
    setRequesting(true);
    setRequestProblem(null);
    try {
      setStarted(await requestPairingViaTelegram(client));
      setStep("pairing");
    } catch (caught) {
      setRequestProblem(pairingProblem(errorCode(caught)));
    } finally {
      setRequesting(false);
    }
  }

  async function afterSignIn() {
    setCheckingVault(true);
    try {
      const vault = await getVault(client);
      if (vault.state === "no_vault") setStep("no-vault");
      else if (vault.state === "ready") onDone();
      else if (vault.state === "bootstrapping") setStep("bootstrap");
      else setStep("choose");
    } catch {
      setStep("choose");
    } finally {
      setCheckingVault(false);
    }
  }

  async function unlock(recoveryCode: string) {
    setUnlocking(true);
    setUnlockError(null);
    try {
      await unlockVault(recoveryCode, client);
      setStep("bootstrap");
    } catch (caught) {
      setUnlockError(t(recoveryErrorKey(errorCode(caught), "join.recovery.failed")));
    } finally {
      setUnlocking(false);
    }
  }

  function openRecovery(from: JoinStep) {
    setRecoveryReturn(from);
    setStep("recovery");
  }

  function leavePairing(next: JoinStep) {
    if (pairing && !terminalPairingStates.has(pairing.state)) void cancelPairing(pairing.id, client).catch(() => undefined);
    setStarted(null);
    setMismatch(false);
    setConfirmFailed(false);
    setStep(next);
  }

  /** "Coinciden": only now does this device accept the access granted by the device behind these emojis. */
  async function confirmMatch() {
    if (!pairing || confirming) return;
    setConfirming(true);
    setConfirmFailed(false);
    try {
      session.setPairing(await confirmPairing(pairing.id, client));
    } catch {
      setConfirmFailed(true);
    } finally {
      setConfirming(false);
    }
  }

  /** "No coinciden": stop here. Without a confirmation the API never installs a grant, even if this call fails. */
  function rejectMatch() {
    if (!pairing) return;
    setMismatch(true);
    void cancelPairing(pairing.id, client)
      .then((cancelled) => session.setPairing(cancelled))
      .catch(() => undefined);
  }

  if (step === "already") {
    return (
      <SetupFrame
        description={t("join.already.body")}
        footer={
          <Button className="ml-auto" onClick={onDone} variant="primary">
            {t("join.already.back")}
          </Button>
        }
        hero={<HeroIcon tone="success"><CircleCheck /></HeroIcon>}
        stepKey="already"
        title={t("join.already.title")}
        width="md"
      />
    );
  }

  if (step === "signin") {
    return (
      <SetupFrame
        description={t("join.signin.body")}
        footer={
          <Button leadingIcon={<ArrowLeft />} onClick={() => setStep("code")} variant="ghost">
            {t("setup.back")}
          </Button>
        }
        stepKey="signin"
        title={t("join.signin.title")}
      >
        {checkingVault ? (
          <p className="flex items-center gap-2.5 text-base text-ink" role="status">
            <Spinner className="text-accent-ink" />
            {t("join.signin.checking")}
          </p>
        ) : (
          <TelegramSignIn client={client} onAuthorized={() => void afterSignIn()} pollIntervalMs={loginPollIntervalMs} qrRefreshMs={qrRefreshMs} />
        )}
      </SetupFrame>
    );
  }

  if (step === "choose") {
    return (
      <SetupFrame
        description={t("join.choose.body")}
        footer={
          <>
            <Button onClick={() => setStep("code")} variant="ghost">
              {t("join.choose.haveCode")}
            </Button>
            {onLocalOnly ? (
              <Button onClick={onLocalOnly} variant="ghost">
                {t("firstRun.welcome.localOnly")}
              </Button>
            ) : null}
          </>
        }
        hero={<HeroIcon><ShieldCheck /></HeroIcon>}
        stepKey="choose"
        title={t("join.choose.title")}
      >
        <div className="grid gap-3">
          <ChoiceCard
            body={t("join.choose.request.body")}
            icon={<Users />}
            loading={requesting}
            onClick={() => void requestAccess()}
            title={t("join.choose.request.title")}
          />
          <ChoiceCard body={t("join.choose.recovery.body")} icon={<LifeBuoy />} onClick={() => openRecovery("choose")} title={t("join.choose.recovery.title")} />
          {requestProblem ? <ProblemCallout problem={requestProblem} /> : null}
        </div>
      </SetupFrame>
    );
  }

  if (step === "recovery") {
    return (
      <SetupFrame
        description={t("join.recovery.body")}
        footer={
          <Button leadingIcon={<ArrowLeft />} onClick={() => setStep(recoveryReturn)} variant="ghost">
            {t("setup.back")}
          </Button>
        }
        hero={<HeroIcon><LifeBuoy /></HeroIcon>}
        stepKey="recovery"
        title={t("join.recovery.title")}
      >
        <RecoveryCodeForm busy={unlocking} error={unlockError} onChange={() => setUnlockError(null)} onSubmit={(value) => void unlock(value)} submitLabel={t("join.recovery.submit")} />
      </SetupFrame>
    );
  }

  if (step === "removed") {
    return (
      <SetupFrame
        description={
          <>
            <p>{t("join.removed.body")}</p>
            <p className="mt-2">{t("join.removed.next")}</p>
          </>
        }
        footer={
          <>
            {onLocalOnly ? (
              <Button onClick={onLocalOnly} variant="ghost">
                {t("firstRun.welcome.localOnly")}
              </Button>
            ) : (
              <span />
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Button leadingIcon={<LifeBuoy />} onClick={() => openRecovery("removed")} variant="secondary">
                {t("join.choose.recovery.title")}
              </Button>
              <Button onClick={() => setStep("code")} variant="primary">
                {t("join.removed.rejoin")}
              </Button>
            </div>
          </>
        }
        hero={<HeroIcon><Unplug /></HeroIcon>}
        stepKey="removed"
        title={t("join.removed.title")}
      />
    );
  }

  if (step === "no-vault") {
    return (
      <SetupFrame
        description={t("join.noVault.body")}
        footer={
          <>
            <Button leadingIcon={<ArrowLeft />} onClick={() => setStep("code")} variant="ghost">
              {t("setup.back")}
            </Button>
            {onCreateVault ? (
              <Button onClick={onCreateVault} variant="primary">
                {t("join.noVault.create")}
              </Button>
            ) : null}
          </>
        }
        hero={<HeroIcon tone="warning"><TriangleAlert /></HeroIcon>}
        stepKey="no-vault"
        title={t("join.noVault.title")}
        width="md"
      />
    );
  }

  if (step === "bootstrap") {
    return <BootstrapStep client={client} onDone={onDone} pollIntervalMs={pollIntervalMs} />;
  }

  if (step === "pairing" && pairing) {
    return (
      <PairingStep
        confirmFailed={confirmFailed}
        confirming={confirming}
        mismatch={mismatch}
        onCancel={() => leavePairing("code")}
        onMatch={() => void confirmMatch()}
        onNoDevice={() => leavePairing("signin")}
        onNoMatch={rejectMatch}
        onRetry={() => (pairing.transport === "telegram" ? leavePairing("choose") : leavePairing("code"))}
        pairing={pairing}
      />
    );
  }

  const fieldError = joinProblem === "wrongCode" || joinProblem === "notFound" ? t(pairingProblemKeys[joinProblem]) : undefined;
  // Arriving from the "removed" explanation, going back returns there.
  const codeBack = initialStep === "removed" ? () => setStep("removed") : onBack;

  return (
    <SetupFrame
      description={t("join.code.body")}
      footer={
        <>
          {codeBack ? (
            <Button leadingIcon={<ArrowLeft />} onClick={codeBack} variant="ghost">
              {t("setup.back")}
            </Button>
          ) : (
            <span />
          )}
          <Button onClick={() => setStep("signin")} variant="ghost">
            {t("join.code.noDevice")}
          </Button>
        </>
      }
      hero={<HeroIcon><MonitorSmartphone /></HeroIcon>}
      stepKey="code"
      title={t("join.code.title")}
    >
      <form className="grid gap-4" onSubmit={(event) => void join(event)}>
        <Input
          autoCapitalize="characters"
          autoComplete="off"
          autoFocus
          className="h-11 font-mono text-lg tracking-[0.12em]"
          error={fieldError}
          hint={t("join.code.hint")}
          label={t("join.code.label")}
          onChange={(event) => {
            setCode(formatPairingInput(event.target.value));
            setJoinProblem(null);
          }}
          placeholder={t("join.code.placeholder")}
          spellCheck={false}
          value={code}
          wrapperClassName="max-w-sm"
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={!isCompletePairingCode(code)} loading={joining} size="lg" type="submit" variant="primary">
            {t("join.code.submit")}
          </Button>
          <p className="text-sm text-ink-muted">{t("join.code.scanHint")}</p>
        </div>
        {joinProblem && !fieldError ? (
          <ProblemCallout
            action={
              joinProblem === "relayUnavailable" ? (
                <Button onClick={() => setStep("signin")} size="sm">
                  {t("join.code.useTelegram")}
                </Button>
              ) : undefined
            }
            problem={joinProblem}
          />
        ) : null}
      </form>
    </SetupFrame>
  );
}

function ProblemCallout({ action, problem }: { action?: ReactNode; problem: PairingProblem }) {
  return (
    <Callout action={action} role="alert" tone={problem === "relayUnavailable" ? "warning" : "danger"}>
      {t(pairingProblemKeys[problem])}
    </Callout>
  );
}

function PairingStep({
  confirmFailed,
  confirming,
  mismatch,
  onCancel,
  onMatch,
  onNoDevice,
  onNoMatch,
  onRetry,
  pairing,
}: {
  confirmFailed: boolean;
  confirming: boolean;
  mismatch: boolean;
  onCancel: () => void;
  onMatch: () => void;
  onNoDevice: () => void;
  onNoMatch: () => void;
  onRetry: () => void;
  pairing: Pairing;
}) {
  const failureFooter = (
    <>
      <Button onClick={onNoDevice} variant="ghost">
        {t("join.code.noDevice")}
      </Button>
      <Button onClick={onRetry} variant="primary">
        {t("join.pairing.retry")}
      </Button>
    </>
  );

  if (mismatch) {
    return (
      <SetupFrame
        description={t("join.pairing.mismatchBody")}
        footer={failureFooter}
        hero={<HeroIcon tone="warning"><ShieldAlert /></HeroIcon>}
        stepKey="pairing-mismatch"
        title={t("join.pairing.mismatchTitle")}
        width="md"
      />
    );
  }

  if (needsGuestConfirmation(pairing) && pairing.sas) {
    return (
      <SetupFrame
        description={t("join.pairing.matchBody")}
        footer={
          <>
            <Button disabled={confirming} onClick={onNoMatch}>
              {t("join.pairing.noMatch")}
            </Button>
            <Button loading={confirming} onClick={onMatch} variant="primary">
              {t("join.pairing.match")}
            </Button>
          </>
        }
        stepKey="pairing-match"
        title={t("join.pairing.matchTitle")}
      >
        <div className="grid gap-5 py-2">
          <SasEmojis emojis={pairing.sas} />
          <PairingVaultSummary vault={pairing.vault} />
          {confirmFailed ? (
            <Callout role="alert" tone="danger">
              {t("join.pairing.confirmFailed")}
            </Callout>
          ) : null}
        </div>
      </SetupFrame>
    );
  }

  const confirmedFallback = pairing.transport === "telegram" && pairing.state === "approving";

  switch (pairing.state) {
    case "awaiting_approval":
    case "approving":
      return (
        <SetupFrame
          description={confirmedFallback ? t("join.pairing.confirmedBody") : t("join.pairing.confirmBody")}
          footer={
            <Button onClick={onCancel} variant="ghost">
              {t("hostPair.cancel")}
            </Button>
          }
          stepKey="pairing-confirm"
          title={t("join.pairing.confirmTitle")}
        >
          <div aria-live="polite" className="grid gap-5 py-2">
            {pairing.sas ? <SasEmojis emojis={pairing.sas} /> : null}
            {confirmedFallback ? <PairingVaultSummary vault={pairing.vault} /> : null}
            <p className="flex items-center justify-center gap-2.5 text-sm text-ink-muted" role="status">
              <Spinner className="size-3.5 text-accent-ink" />
              {confirmedFallback
                ? t("join.pairing.waitingAccess")
                : pairing.state === "approving"
                  ? t("join.pairing.receiving")
                  : t("join.pairing.waitingApproval")}
            </p>
          </div>
        </SetupFrame>
      );
    case "needs_telegram_login":
      return (
        <SetupFrame
          description={t("join.pairing.telegramBody")}
          footer={
            <Button onClick={onCancel} variant="ghost">
              {t("hostPair.cancel")}
            </Button>
          }
          stepKey="pairing-telegram"
          title={t("join.pairing.telegramTitle")}
        >
          <div className="grid gap-6 sm:grid-cols-[12.5rem_minmax(0,1fr)] sm:items-center">
            <div className="mx-auto w-full max-w-[12.5rem] rounded-xl border border-line bg-white p-1.5 shadow-xs">
              {pairing.telegram_qr ? (
                <QrCode label={t("signIn.qr.label")} matrix={pairing.telegram_qr} />
              ) : (
                <div className="grid aspect-square place-items-center rounded-lg bg-sunken text-ink-subtle" role="status">
                  <Spinner />
                </div>
              )}
            </div>
            <ol className="grid gap-3.5">
              {[t("signIn.qr.step1"), t("signIn.qr.step2"), t("signIn.qr.step3")].map((text, index) => (
                <li className="flex gap-3 text-base text-ink" key={text}>
                  <span aria-hidden="true" className="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent-ink">
                    {index + 1}
                  </span>
                  <span className="pt-0.5">{text}</span>
                </li>
              ))}
            </ol>
          </div>
        </SetupFrame>
      );
    case "rejected":
      return (
        <SetupFrame
          description={t("join.pairing.rejectedBody")}
          footer={failureFooter}
          hero={<HeroIcon tone="warning"><TriangleAlert /></HeroIcon>}
          stepKey="pairing-rejected"
          title={t("join.pairing.rejectedTitle")}
          width="md"
        />
      );
    case "expired":
      return (
        <SetupFrame
          description={t("join.pairing.expiredBody")}
          footer={failureFooter}
          hero={<HeroIcon tone="warning"><Timer /></HeroIcon>}
          stepKey="pairing-expired"
          title={t("join.pairing.expiredTitle")}
          width="md"
        />
      );
    case "cancelled":
      return (
        <SetupFrame
          description={t("join.pairing.cancelledBody")}
          footer={failureFooter}
          hero={<HeroIcon tone="warning"><TriangleAlert /></HeroIcon>}
          stepKey="pairing-cancelled"
          title={t("join.pairing.cancelledTitle")}
          width="md"
        />
      );
    case "failed":
      return (
        <SetupFrame
          description={t(pairingProblemKeys[pairingProblem(pairing.error?.code)])}
          footer={failureFooter}
          hero={<HeroIcon tone="danger"><TriangleAlert /></HeroIcon>}
          stepKey="pairing-failed"
          title={t("join.pairing.failedTitle")}
          width="md"
        />
      );
    default:
      return (
        <SetupFrame
          description={pairing.transport === "telegram" ? t("join.pairing.requestBody") : t("join.pairing.connectingBody")}
          footer={
            <Button onClick={onCancel} variant="ghost">
              {t("hostPair.cancel")}
            </Button>
          }
          hero={
            <HeroIcon>
              <Spinner className="size-5" />
            </HeroIcon>
          }
          stepKey="pairing-waiting"
          title={pairing.transport === "telegram" ? t("join.pairing.requestTitle") : t("join.pairing.connectingTitle")}
          width="md"
        />
      );
  }
}

function BootstrapStep({ client, onDone, pollIntervalMs }: { client: ApiClient; onDone: () => void; pollIntervalMs: number }) {
  const progress = useBootstrapStatus(client, pollIntervalMs);

  return (
    <SetupFrame
      description={progress.finished ? t("join.bootstrap.doneBody") : t("join.bootstrap.body")}
      footer={
        <Button className="ml-auto" onClick={onDone} variant="primary">
          {progress.finished ? t("join.bootstrap.open") : t("join.bootstrap.continue")}
        </Button>
      }
      hero={<HeroIcon tone={progress.finished ? "success" : "accent"}>{progress.finished ? <CircleCheck /> : <CloudDownload />}</HeroIcon>}
      stepKey="bootstrap"
      title={progress.finished ? t("join.bootstrap.doneTitle") : t("join.bootstrap.title")}
    >
      <BootstrapMeter progress={progress} />
    </SetupFrame>
  );
}
