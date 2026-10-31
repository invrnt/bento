import { useState } from "react";
import { KeyRound, LifeBuoy, RefreshCw, ScanSearch } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { rotateRecoveryCode, verifyRecoveryCode } from "../../api/vault";
import type { VaultStatus } from "../../api/vault";
import type { QrMatrix } from "../../api/qr";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Card } from "../../components/Card";
import { Dialog } from "../../components/Dialog";
import { t } from "../../i18n/dictionary";
import { RecoveryCodeForm } from "./RecoveryCodeForm";
import { RecoveryKit } from "./RecoveryKit";
import { recoveryErrorKey, recoveryQrFrom } from "./recoveryCode";
import { errorCode } from "../onboarding/apiErrors";

export type RecoverySectionProps = {
  accountName?: string | null;
  client?: ApiClient;
  onChanged?: () => void;
  vault: VaultStatus | null;
};

/** Ajustes › Cuenta y nube › Kit de recuperación: status, new code, verification. */
export function RecoverySection({ accountName, client = apiClient, onChanged, vault }: RecoverySectionProps) {
  const [kitCode, setKitCode] = useState<string | null>(null);
  const [kitQr, setKitQr] = useState<QrMatrix | null>(null);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [rotateError, setRotateError] = useState(false);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const saved = Boolean(vault?.recovery_kit_saved);

  async function rotate() {
    setRotating(true);
    setRotateError(false);
    try {
      const result = await rotateRecoveryCode(client);
      setConfirmRotate(false);
      setKitCode(result.recovery_code);
      setKitQr(recoveryQrFrom(result));
      onChanged?.();
    } catch {
      setRotateError(true);
    } finally {
      setRotating(false);
    }
  }

  return (
    <Card aria-labelledby="recovery-title" as="section" className="scroll-mt-6" id="recovery" padding="none" tabIndex={-1}>
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 gap-3.5">
          <span aria-hidden="true" className="grid size-10 shrink-0 place-items-center rounded-md bg-accent-soft text-accent-ink">
            <LifeBuoy className="size-5" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-ink" id="recovery-title">
                {t("recovery.section.title")}
              </h2>
              <Badge dot tone={saved ? "success" : "warning"}>
                {saved ? t("recovery.status.saved") : t("recovery.status.notSaved")}
              </Badge>
            </div>
            <p className="mt-1 text-base text-ink-muted">{t("recovery.section.body")}</p>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 border-t border-line bg-subtle px-5 py-3.5">
        <Button leadingIcon={<RefreshCw />} onClick={() => setConfirmRotate(true)} size="sm" variant={saved ? "secondary" : "primary"}>
          {t("recovery.section.rotate")}
        </Button>
        <Button leadingIcon={<ScanSearch />} onClick={() => setVerifyOpen(true)} size="sm" variant="ghost">
          {t("recovery.section.verify")}
        </Button>
      </div>

      <Dialog
        actions={
          <>
            <Button onClick={() => setConfirmRotate(false)} variant="ghost">
              {t("setup.cancel")}
            </Button>
            <Button data-autofocus leadingIcon={<RefreshCw />} loading={rotating} onClick={() => void rotate()} variant="primary">
              {t("recovery.rotate.confirm")}
            </Button>
          </>
        }
        description={saved ? t("recovery.rotate.bodySaved") : t("recovery.rotate.bodyUnsaved")}
        icon={<RefreshCw />}
        onOpenChange={setConfirmRotate}
        open={confirmRotate}
        title={t("recovery.rotate.title")}
      >
        {rotateError ? (
          <Callout role="alert" tone="danger">
            {t("recovery.rotate.failed")}
          </Callout>
        ) : (
          <p>{t("recovery.rotate.note")}</p>
        )}
      </Dialog>

      <Dialog icon={<KeyRound />} onOpenChange={(open) => !open && setKitCode(null)} open={kitCode !== null} size="lg" title={t("recovery.kit.title")}>
        {kitCode ? (
          <div className="grid gap-4">
            <p>{t("recovery.kit.why")}</p>
            <RecoveryKit
              accountName={accountName}
              client={client}
              code={kitCode}
              createdAt={vault?.created_at}
              onConfirmed={() => {
                setKitCode(null);
                onChanged?.();
              }}
              onLater={() => setKitCode(null)}
              qr={kitQr}
            />
          </div>
        ) : null}
      </Dialog>

      <VerifyDialog client={client} onOpenChange={setVerifyOpen} open={verifyOpen} />
    </Card>
  );
}

function VerifyDialog({ client, onOpenChange, open }: { client: ApiClient; onOpenChange: (open: boolean) => void; open: boolean }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<"valid" | "invalid" | "checksum" | "failed" | null>(null);

  async function verify(code: string) {
    setBusy(true);
    setResult(null);
    try {
      const response = await verifyRecoveryCode(code, client);
      setResult(response.valid ? "valid" : "invalid");
    } catch (caught) {
      setResult(recoveryErrorKey(errorCode(caught), "recovery.verify.failed") === "recovery.error.checksum" ? "checksum" : "failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      description={t("recovery.verify.body")}
      icon={<ScanSearch />}
      onOpenChange={(next) => {
        if (!next) setResult(null);
        onOpenChange(next);
      }}
      open={open}
      title={t("recovery.verify.title")}
    >
      <div className="grid gap-4">
        <RecoveryCodeForm busy={busy} onChange={() => setResult(null)} onSubmit={(code) => void verify(code)} submitLabel={t("recovery.verify.submit")} />
        <div aria-live="polite">
          {result === "valid" ? (
            <Callout role="status" tone="success">
              {t("recovery.verify.valid")}
            </Callout>
          ) : null}
          {result === "invalid" ? (
            <Callout role="status" tone="danger">
              {t("recovery.verify.invalid")}
            </Callout>
          ) : null}
          {result === "checksum" ? (
            <Callout role="status" tone="warning">
              {t("recovery.error.checksum")}
            </Callout>
          ) : null}
          {result === "failed" ? (
            <Callout role="alert" tone="danger">
              {t("recovery.verify.failed")}
            </Callout>
          ) : null}
        </div>
      </div>
    </Dialog>
  );
}
