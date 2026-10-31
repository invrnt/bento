import { useCallback, useEffect, useRef, useState } from "react";
import { Check, CircleCheck, Copy, Link2, MonitorSmartphone, RotateCw, Timer, TriangleAlert, Unplug } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { approvePairing, cancelPairing, hostPairing, rejectPairing, terminalPairingStates } from "../../api/pairing";
import type { Pairing } from "../../api/pairing";
import { StatusDot } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Dialog } from "../../components/Dialog";
import { IconButton } from "../../components/IconButton";
import { QrCode } from "../../components/QrCode";
import { Spinner } from "../../components/Spinner";
import { LoadingState } from "../../components/States";
import { t } from "../../i18n/dictionary";
import { errorCode } from "../onboarding/apiErrors";
import { copyText } from "../onboarding/clipboard";
import { formatClock, tf } from "../onboarding/format";
import { useSecondsLeft } from "../onboarding/useNow";
import { deviceDisplayName } from "../devices/deviceLabels";
import { pairingProblem, pairingProblemKeys } from "./pairingErrors";
import { SasEmojis, SasHint } from "./SasEmojis";
import { usePairingSession } from "./usePairingSession";

export type AddDeviceDialogProps = {
  client?: ApiClient;
  onAdded?: () => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  pollIntervalMs?: number;
};

type Phase =
  | "loading"
  | "relay-unavailable"
  | "start-failed"
  | "code"
  | "approve"
  | "approving"
  | "guest-login"
  | "completed"
  | "rejected"
  | "expired"
  | "failed";

/** Ajustes › Dispositivos › Añadir dispositivo: big QR + code, then "¿Añadir «…»?" with the emojis. */
export function AddDeviceDialog({ client = apiClient, onAdded, onOpenChange, open, pollIntervalMs = 1000 }: AddDeviceDialogProps) {
  const [initial, setInitial] = useState<Pairing | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [actionError, setActionError] = useState(false);
  const [acting, setActing] = useState<"approve" | "reject" | null>(null);
  const [copied, setCopied] = useState<"code" | "link" | null>(null);
  const session = usePairingSession(initial, { client, pollIntervalMs });
  const pairing = session.pairing;
  const latest = useRef<Pairing | null>(null);
  latest.current = pairing;
  const notifiedAdded = useRef(false);

  const deadline = pairing?.expires_at ? new Date(pairing.expires_at).getTime() : null;
  const secondsLeft = useSecondsLeft(pairing && (pairing.state === "waiting" || pairing.state === "connected") ? deadline : null);

  const start = useCallback(async () => {
    setStarting(true);
    setStartError(null);
    setActionError(false);
    setInitial(null);
    notifiedAdded.current = false;
    try {
      setInitial(await hostPairing(client));
    } catch (caught) {
      setStartError(errorCode(caught) ?? "generic");
    } finally {
      setStarting(false);
    }
  }, [client]);

  const startedForOpen = useRef(false);
  useEffect(() => {
    if (!open) {
      startedForOpen.current = false;
      setInitial(null);
      return;
    }
    if (startedForOpen.current) return;
    startedForOpen.current = true;
    void start();
  }, [open, start]);

  useEffect(() => {
    if (pairing?.state === "completed" && !notifiedAdded.current) {
      notifiedAdded.current = true;
      onAdded?.();
    }
  }, [onAdded, pairing?.state]);

  function close() {
    const current = latest.current;
    if (current && !terminalPairingStates.has(current.state)) void cancelPairing(current.id, client).catch(() => undefined);
    onOpenChange(false);
  }

  async function decide(approve: boolean) {
    if (!pairing) return;
    setActing(approve ? "approve" : "reject");
    setActionError(false);
    try {
      session.setPairing(approve ? await approvePairing(pairing.id, client) : await rejectPairing(pairing.id, client));
    } catch {
      setActionError(true);
    } finally {
      setActing(null);
    }
  }

  async function copy(kind: "code" | "link", value: string) {
    if (await copyText(value)) setCopied(kind);
  }

  const phase = resolvePhase(starting, startError, pairing, secondsLeft);
  const peerName = pairing?.peer ? deviceDisplayName(pairing.peer.device_name, pairing.peer.platform) : "";
  const problem = pairingProblem(pairing?.error?.code);
  const link = pairing?.web_link ?? pairing?.link ?? null;

  return (
    <Dialog
      actions={
        <DialogActions
          acting={acting}
          onApprove={() => void decide(true)}
          onClose={close}
          onReject={() => void decide(false)}
          onRetry={() => void start()}
          phase={phase}
        />
      }
      icon={<MonitorSmartphone />}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      open={open}
      size="lg"
      title={phase === "approve" ? tf("hostPair.approve.title", { name: peerName }) : t("hostPair.title")}
    >
      <div aria-live="polite" className="grid gap-5">
        {phase === "loading" ? <LoadingState label={t("hostPair.loading")} /> : null}

        {phase === "relay-unavailable" ? (
          <Callout icon={<Unplug />} role="alert" title={t("hostPair.relay.title")} tone="warning">
            <p>{t("hostPair.relay.body")}</p>
            <p className="mt-2">{t("hostPair.relay.fallback")}</p>
          </Callout>
        ) : null}

        {phase === "start-failed" ? (
          <Callout role="alert" tone="danger">
            {t("hostPair.startFailed")}
          </Callout>
        ) : null}

        {phase === "code" && pairing ? (
          <>
            <div className="grid gap-6 sm:grid-cols-[13.5rem_minmax(0,1fr)] sm:items-center">
              <div className="mx-auto w-full max-w-[13.5rem] rounded-xl border border-line bg-white p-1.5 shadow-xs">
                {pairing.qr ? <QrCode label={t("hostPair.qr.label")} matrix={pairing.qr} /> : null}
              </div>
              <div className="grid min-w-0 gap-4">
                {pairing.code ? (
                  <div>
                    <p className="text-sm font-medium text-ink-muted">{t("hostPair.code.label")}</p>
                    <div className="mt-1 flex items-center gap-1.5">
                      <span className="font-mono text-2xl font-semibold tracking-[0.1em] text-ink" data-testid="host-code">
                        {pairing.code}
                      </span>
                      <IconButton
                        icon={copied === "code" ? <Check /> : <Copy />}
                        label={copied === "code" ? t("hostPair.copied") : t("hostPair.code.copy")}
                        onClick={() => void copy("code", pairing.code!)}
                      />
                    </div>
                  </div>
                ) : null}
                {link ? (
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-ink-muted">{t("hostPair.link.label")}</p>
                    <div className="mt-1 flex min-w-0 items-center gap-1.5">
                      <code className="min-w-0 truncate rounded-xs bg-sunken px-1.5 py-1 text-xs text-ink">{link}</code>
                      <IconButton
                        icon={copied === "link" ? <Check /> : <Link2 />}
                        label={copied === "link" ? t("hostPair.copied") : t("hostPair.link.copy")}
                        onClick={() => void copy("link", link)}
                      />
                    </div>
                  </div>
                ) : null}
                <p className="flex items-center gap-2 text-sm tabular-nums text-ink-muted">
                  <Timer aria-hidden="true" className="size-4 shrink-0" />
                  {tf("hostPair.expiresIn", { time: formatClock(secondsLeft) })}
                </p>
              </div>
            </div>
            <Callout tone="neutral">{t("hostPair.instructions")}</Callout>
            <p className="flex items-center gap-2.5 text-base text-ink" role="status">
              <StatusDot className="size-2" pulse tone="accent" />
              {pairing.state === "connected" ? t("hostPair.connecting") : t("hostPair.waiting")}
            </p>
          </>
        ) : null}

        {phase === "approve" && pairing?.sas ? (
          <div className="grid gap-4 py-2">
            <p className="text-center text-base text-ink-muted">{t("hostPair.approve.body")}</p>
            <SasEmojis emojis={pairing.sas} />
            <SasHint />
          </div>
        ) : null}

        {phase === "approving" ? (
          <p className="flex items-center justify-center gap-2.5 py-8 text-base text-ink" role="status">
            <Spinner className="text-accent-ink" />
            {tf("hostPair.approving", { name: peerName })}
          </p>
        ) : null}

        {phase === "guest-login" ? (
          <p className="flex items-center justify-center gap-2.5 py-8 text-center text-base text-ink" role="status">
            <Spinner className="text-accent-ink" />
            {tf("hostPair.guestLogin", { name: peerName })}
          </p>
        ) : null}

        {phase === "completed" ? (
          <Callout icon={<CircleCheck />} role="status" title={t("hostPair.completed.title")} tone="success">
            {tf("hostPair.completed.body", { name: peerName })}
          </Callout>
        ) : null}

        {phase === "rejected" ? (
          <Callout role="status" title={t("hostPair.rejected.title")} tone="neutral">
            {t("hostPair.rejected.body")}
          </Callout>
        ) : null}

        {phase === "expired" ? (
          <Callout icon={<Timer />} role="status" title={t("hostPair.expired.title")} tone="warning">
            {t("hostPair.expired.body")}
          </Callout>
        ) : null}

        {phase === "failed" ? (
          <Callout icon={<TriangleAlert />} role="alert" title={t("hostPair.failed.title")} tone="danger">
            {t(pairingProblemKeys[problem])}
          </Callout>
        ) : null}

        {actionError ? (
          <Callout role="alert" tone="danger">
            {t("hostPair.actionFailed")}
          </Callout>
        ) : null}
      </div>
    </Dialog>
  );
}

function resolvePhase(starting: boolean, startError: string | null, pairing: Pairing | null, secondsLeft: number): Phase {
  if (starting) return "loading";
  if (startError) return pairingProblem(startError) === "relayUnavailable" ? "relay-unavailable" : "start-failed";
  if (!pairing) return "loading";
  switch (pairing.state) {
    case "waiting":
    case "connected":
      return secondsLeft > 0 || !pairing.expires_at ? "code" : "expired";
    case "awaiting_approval":
      return pairing.sas ? "approve" : "approving";
    case "needs_telegram_login":
      return "guest-login";
    case "approving":
    case "bootstrapping":
      return "approving";
    case "completed":
      return "completed";
    case "rejected":
      return "rejected";
    case "expired":
    case "cancelled":
      return "expired";
    default:
      return pairingProblem(pairing.error?.code) === "relayUnavailable" ? "relay-unavailable" : "failed";
  }
}

function DialogActions({
  acting,
  onApprove,
  onClose,
  onReject,
  onRetry,
  phase,
}: {
  acting: "approve" | "reject" | null;
  onApprove: () => void;
  onClose: () => void;
  onReject: () => void;
  onRetry: () => void;
  phase: Phase;
}) {
  switch (phase) {
    case "approve":
      return (
        <>
          <Button disabled={acting !== null} loading={acting === "reject"} onClick={onReject}>
            {t("hostPair.approve.reject")}
          </Button>
          <Button data-autofocus disabled={acting !== null} loading={acting === "approve"} onClick={onApprove} variant="primary">
            {t("hostPair.approve.accept")}
          </Button>
        </>
      );
    case "completed":
    case "rejected":
      return (
        <Button data-autofocus onClick={onClose} variant="primary">
          {t("hostPair.done")}
        </Button>
      );
    case "expired":
    case "failed":
    case "start-failed":
    case "relay-unavailable":
      return (
        <>
          <Button onClick={onClose} variant="ghost">
            {t("common.close")}
          </Button>
          <Button data-autofocus leadingIcon={<RotateCw />} onClick={onRetry} variant="primary">
            {phase === "expired" ? t("hostPair.newCode") : t("common.retry")}
          </Button>
        </>
      );
    default:
      return (
        <Button onClick={onClose} variant="ghost">
          {t("hostPair.cancel")}
        </Button>
      );
  }
}
