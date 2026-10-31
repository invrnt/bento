import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import { Check, Copy, FileDown, Printer, ShieldAlert } from "lucide-react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { confirmRecoveryKit } from "../../api/vault";
import type { VaultStatus } from "../../api/vault";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { Input } from "../../components/Input";
import { t } from "../../i18n/dictionary";
import { errorCode } from "../onboarding/apiErrors";
import { copyText } from "../onboarding/clipboard";
import { canSavePdf, savePageAsPdf } from "../onboarding/desktopHost";
import { setPendingRecoveryCode } from "./pendingKit";
import { formatRecoveryCode, lastRecoveryGroup, matchesLastGroup, normalizeRecoveryInput, recoveryGroups } from "./recoveryCode";
import { RecoveryKitSheet } from "./RecoveryKitSheet";

export type RecoveryKitProps = {
  accountName?: string | null;
  client?: ApiClient;
  code: string;
  createdAt?: string | null;
  onConfirmed: (vault: VaultStatus | null) => void;
  /** Offer "Más tarde"; omit when saving the kit is mandatory. */
  onLater?: () => void;
};

type Notice = "copied" | "copyFailed" | "pdfSaved" | "pdfFailed" | null;

const mismatchCodes = new Set(["recovery_code_invalid", "recovery_group_mismatch", "validation_failed"]);

/** Shows a fresh recovery code, lets the person copy/print/save it and confirm by typing the last group. */
export function RecoveryKit({ accountName, client = apiClient, code, createdAt, onConfirmed, onLater }: RecoveryKitProps) {
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const desktopPdf = canSavePdf();
  const codeLabelId = useId();
  const groups = recoveryGroups(code);
  const expectedLength = lastRecoveryGroup(code).length || 4;

  useEffect(() => {
    setPendingRecoveryCode(code);
  }, [code]);

  async function copy() {
    setNotice((await copyText(formatRecoveryCode(code))) ? "copied" : "copyFailed");
  }

  async function save() {
    if (!desktopPdf) {
      window.print();
      return;
    }
    setSaving(true);
    try {
      const result = await savePageAsPdf(t("recovery.pdfName"));
      if (result && !result.canceled) setNotice("pdfSaved");
    } catch {
      setNotice("pdfFailed");
    } finally {
      setSaving(false);
    }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    if (!matchesLastGroup(code, typed)) {
      setError(t("recovery.confirm.mismatch"));
      return;
    }
    setConfirming(true);
    setError(null);
    try {
      const vault = await confirmRecoveryKit(normalizeRecoveryInput(typed), client);
      setPendingRecoveryCode(null);
      onConfirmed(vault);
    } catch (caught) {
      setError(mismatchCodes.has(errorCode(caught) ?? "") ? t("recovery.confirm.mismatch") : t("recovery.confirm.failed"));
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="grid gap-5">
      <div>
        <p className="mb-2 text-sm font-medium text-ink" id={codeLabelId}>
          {t("recovery.code.label")}
        </p>
        <div
          aria-labelledby={codeLabelId}
          className="grid grid-cols-3 gap-2 rounded-xl border border-line bg-sunken p-2.5"
          data-testid="recovery-code"
          role="group"
        >
          {groups.map((group, index) => (
            <span
              className="rounded-md bg-raised px-2 py-2 text-center font-mono text-md font-medium tracking-[0.14em] text-ink shadow-xs ring-1 ring-line sm:text-lg"
              key={`${group}-${index}`}
            >
              {group}
            </span>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button leadingIcon={notice === "copied" ? <Check /> : <Copy />} onClick={() => void copy()} size="sm">
            {notice === "copied" ? t("recovery.copied") : t("recovery.copy")}
          </Button>
          <Button leadingIcon={desktopPdf ? <FileDown /> : <Printer />} loading={saving} onClick={() => void save()} size="sm">
            {desktopPdf ? t("recovery.savePdf") : t("recovery.print")}
          </Button>
          <span aria-live="polite" className="text-sm text-ink-muted" role="status">
            {notice === "pdfSaved" ? t("recovery.pdfSaved") : null}
            {notice === "pdfFailed" ? t("recovery.pdfFailed") : null}
            {notice === "copyFailed" ? t("recovery.copyFailed") : null}
          </span>
        </div>
      </div>

      <Callout icon={<ShieldAlert />} tone="warning">
        {t("recovery.keepSafe")}
      </Callout>

      <form className="grid gap-3" onSubmit={(event) => void confirm(event)}>
        <Input
          autoCapitalize="characters"
          autoComplete="off"
          className="font-mono uppercase tracking-[0.2em]"
          error={error ?? undefined}
          hint={t("recovery.confirm.hint")}
          label={t("recovery.confirm.label")}
          maxLength={expectedLength}
          onChange={(event) => {
            setTyped(normalizeRecoveryInput(event.target.value).slice(0, expectedLength));
            setError(null);
          }}
          spellCheck={false}
          value={typed}
          wrapperClassName="max-w-56"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={typed.length < expectedLength} loading={confirming} type="submit" variant="primary">
            {t("recovery.confirm.submit")}
          </Button>
          {onLater ? (
            <Button onClick={onLater} variant="ghost">
              {t("recovery.later")}
            </Button>
          ) : null}
        </div>
      </form>

      <RecoveryKitSheet accountName={accountName} code={code} createdAt={createdAt} />
    </div>
  );
}
