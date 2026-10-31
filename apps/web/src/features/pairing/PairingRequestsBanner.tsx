import { useEffect, useRef, useState } from "react";
import { CircleCheck, MonitorSmartphone, TriangleAlert } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { approvePairingRequest, listPairingRequests, rejectPairingRequest, reviewPairingRequest } from "../../api/pairing";
import type { Pairing, PairingRequest } from "../../api/pairing";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Dialog } from "../../components/Dialog";
import { LoadingState } from "../../components/States";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { usePolledResource } from "../../lib/usePolledResource";
import { deviceDisplayName } from "../devices/deviceLabels";
import { errorCode } from "../onboarding/apiErrors";
import { tf } from "../onboarding/format";
import { pairingProblem, pairingProblemKeys } from "./pairingErrors";
import { SasEmojis, SasHint } from "./SasEmojis";
import { usePairingSession } from "./usePairingSession";

export type PairingRequestsBannerProps = {
  client?: ApiClient;
  pollIntervalMs?: number;
};

/** Non-modal notice for Sync-channel join requests ("Un dispositivo nuevo quiere unirse"). */
export function PairingRequestsBanner({ client = apiClient, pollIntervalMs = 5000 }: PairingRequestsBannerProps) {
  const requests = usePolledResource(() => listPairingRequests(client), pollIntervalMs);
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(() => new Set());
  const [reviewing, setReviewing] = useState<PairingRequest | null>(null);
  const pendingItems = (requests.data?.items ?? []).filter((item) => !dismissed.has(item.id));
  const request = pendingItems[0];

  function dismiss(id: string) {
    setDismissed((current) => new Set([...current, id]));
  }

  return (
    <>
      <div aria-live="polite" className="empty:hidden">
        {request && reviewing?.id !== request.id ? (
          <Callout
            action={
              <>
                <Button onClick={() => dismiss(request.id)} size="sm" variant="ghost">
                  {t("pairReq.later")}
                </Button>
                <Button onClick={() => setReviewing(request)} size="sm" variant="primary">
                  {t("pairReq.review")}
                </Button>
              </>
            }
            className="mb-5 animate-slide-up"
            icon={<MonitorSmartphone />}
            role="status"
            title={t("pairReq.title")}
            tone="info"
          >
            {tf("pairReq.body", { name: deviceDisplayName(request.device_name, request.platform) })}
          </Callout>
        ) : null}
      </div>
      {reviewing ? (
        <ReviewDialog
          client={client}
          onClose={(handled) => {
            if (handled) dismiss(reviewing.id);
            setReviewing(null);
            void requests.refresh();
          }}
          pollIntervalMs={Math.min(pollIntervalMs, 1000)}
          request={reviewing}
        />
      ) : null}
    </>
  );
}

function ReviewDialog({
  client,
  onClose,
  pollIntervalMs,
  request,
}: {
  client: ApiClient;
  onClose: (handled: boolean) => void;
  pollIntervalMs: number;
  request: PairingRequest;
}) {
  const [initial, setInitial] = useState<Pairing | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<MessageKey | null>(null);
  const [acting, setActing] = useState<"approve" | "reject" | null>(null);
  const session = usePairingSession(initial, { client, pollIntervalMs });
  const pairing = session.pairing;
  const name = deviceDisplayName(request.device_name, request.platform);

  const reviewedFor = useRef<string | null>(null);

  useEffect(() => {
    // Reviewing posts an offer to the other device: do it once per request.
    if (reviewedFor.current === request.id) return;
    reviewedFor.current = request.id;
    reviewPairingRequest(request.id, client)
      .then(setInitial)
      .catch((caught: unknown) => setFailure(reviewProblemKey(errorCode(caught))))
      .finally(() => setLoading(false));
  }, [client, request.id]);

  async function decide(approve: boolean) {
    setActing(approve ? "approve" : "reject");
    setFailure(null);
    try {
      const result = approve ? await approvePairingRequest(request.id, client) : await rejectPairingRequest(request.id, client);
      session.setPairing(result);
      if (!approve) onClose(true);
    } catch (caught) {
      setFailure(reviewProblemKey(errorCode(caught)));
    } finally {
      setActing(null);
    }
  }

  const state = pairing?.state;
  const done = state === "completed";
  const ended = state === "failed" || state === "expired" || state === "cancelled" || state === "rejected";
  const working = state === "approving" || state === "bootstrapping" || state === "needs_telegram_login";

  return (
    <Dialog
      actions={
        done ? (
          <Button data-autofocus onClick={() => onClose(true)} variant="primary">
            {t("hostPair.done")}
          </Button>
        ) : ended ? (
          <Button data-autofocus onClick={() => onClose(true)} variant="primary">
            {t("common.close")}
          </Button>
        ) : (
          <>
            <Button disabled={acting !== null || loading || working} loading={acting === "reject"} onClick={() => void decide(false)}>
              {t("hostPair.approve.reject")}
            </Button>
            <Button
              data-autofocus
              disabled={acting !== null || loading || working || !pairing?.sas}
              loading={acting === "approve" || working}
              onClick={() => void decide(true)}
              variant="primary"
            >
              {t("hostPair.approve.accept")}
            </Button>
          </>
        )
      }
      icon={<MonitorSmartphone />}
      onOpenChange={(open) => !open && onClose(done)}
      open
      size="md"
      title={tf("hostPair.approve.title", { name })}
    >
      <div aria-live="polite" className="grid gap-4">
        {loading ? <LoadingState label={t("pairReq.loading")} /> : null}
        {!loading && pairing?.sas && !done && !ended ? (
          <>
            <p className="text-center text-base text-ink-muted">{t("hostPair.approve.body")}</p>
            <SasEmojis emojis={pairing.sas} />
            <SasHint />
          </>
        ) : null}
        {done ? (
          <Callout icon={<CircleCheck />} role="status" title={t("hostPair.completed.title")} tone="success">
            {tf("hostPair.completed.body", { name })}
          </Callout>
        ) : null}
        {pairing && ended && state !== "rejected" ? (
          // Includes `pairing_request_taken`: someone answered first, maybe not one of this person's devices.
          <Callout icon={<TriangleAlert />} role="alert" title={t("hostPair.failed.title")} tone="danger">
            {t(state === "expired" ? "pairReq.expired" : reviewProblemKey(pairing.error?.code))}
          </Callout>
        ) : null}
        {failure ? (
          <Callout role="alert" tone="danger">
            {t(failure)}
          </Callout>
        ) : null}
      </div>
    </Dialog>
  );
}

/** Review outcomes worth explaining; anything else keeps the generic "try again". */
function reviewProblemKey(code: string | null | undefined): MessageKey {
  const problem = pairingProblem(code);
  return problem === "requestTaken" || problem === "deviceRemoved" ? pairingProblemKeys[problem] : "pairReq.failed";
}
