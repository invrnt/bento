import { useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { Button } from "../../components/Button";
import { Input } from "../../components/Input";
import { t } from "../../i18n/dictionary";
import { formatRecoveryCode, formatRecoveryInput, isCompleteRecoveryCode } from "./recoveryCode";

export type RecoveryCodeFormProps = {
  busy?: boolean;
  error?: string | null;
  extraActions?: ReactNode;
  hint?: string;
  onChange?: () => void;
  onSubmit: (code: string) => void;
  submitLabel: string;
};

/** A 36-character recovery code field that formats itself in groups of 4 while typing or pasting. */
export function RecoveryCodeForm({ busy = false, error, extraActions, hint, onChange, onSubmit, submitLabel }: RecoveryCodeFormProps) {
  const [value, setValue] = useState("");
  const complete = isCompleteRecoveryCode(value);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (complete && !busy) onSubmit(formatRecoveryCode(value));
  }

  return (
    <form className="grid gap-4" onSubmit={submit}>
      <Input
        autoCapitalize="characters"
        autoComplete="off"
        autoFocus
        className="font-mono text-sm tracking-[0.08em] sm:text-base"
        error={error ?? undefined}
        hint={hint ?? t("recovery.enter.hint")}
        label={t("recovery.enter.label")}
        onChange={(event) => {
          setValue(formatRecoveryInput(event.target.value.replace(/^\s*bento-recovery:/i, "")));
          onChange?.();
        }}
        placeholder={t("recovery.enter.placeholder")}
        spellCheck={false}
        value={value}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={!complete} loading={busy} type="submit" variant="primary">
          {submitLabel}
        </Button>
        {extraActions}
      </div>
    </form>
  );
}
