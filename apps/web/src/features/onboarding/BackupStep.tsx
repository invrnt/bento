import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import { ArrowLeft, CircleCheck, FolderPlus } from "lucide-react";

import type { ApiClient } from "../../api/client";
import { addBackupSource, listBackupSources, listBackupSuggestions } from "../../api/backup";
import type { BackupSuggestion } from "../../api/backup";
import { Button } from "../../components/Button";
import { CheckboxBox } from "../../components/Checkbox";
import { Input } from "../../components/Input";
import { LoadingState } from "../../components/States";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { backupErrorKey, backupKindIcon, folderLabel } from "./backupSources";
import { canPickDirectory, pickDirectory } from "./desktopHost";
import { SetupFrame } from "./SetupFrame";

type Choice = {
  added: boolean;
  error: MessageKey | null;
  kind: BackupSuggestion["kind"] | null;
  label: string;
  path: string;
  selected: boolean;
};

export type BackupStepProps = {
  client: ApiClient;
  onBack?: () => void;
  onNext: () => void;
  steps: { current: number; total: number };
};

/** "Elige qué respaldar": suggested folders preselected, plus "Añadir carpeta…". */
export function BackupStep({ client, onBack, onNext, steps }: BackupStepProps) {
  const [choices, setChoices] = useState<Choice[] | null>(null);
  const [typing, setTyping] = useState(false);
  const [typedPath, setTypedPath] = useState("");
  const [saving, setSaving] = useState(false);
  const desktopPicker = canPickDirectory();

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      listBackupSuggestions(client).catch(() => ({ items: [] as BackupSuggestion[] })),
      listBackupSources(client).catch(() => ({ items: [] })),
    ]).then(([suggestions, sources]) => {
      if (cancelled) return;
      const existing = new Set((sources.items ?? []).map((source) => source.path));
      setChoices([
        ...(sources.items ?? []).map((source) => ({ added: true, error: null, kind: null, label: source.label, path: source.path, selected: true })),
        ...(suggestions.items ?? [])
          .filter((suggestion) => !existing.has(suggestion.path))
          .map((suggestion) => ({ added: false, error: null, kind: suggestion.kind, label: suggestion.label, path: suggestion.path, selected: true })),
      ]);
    });
    return () => {
      cancelled = true;
    };
  }, [client]);

  function addPath(path: string) {
    const trimmed = path.trim();
    if (!trimmed) return;
    setChoices((current) => {
      const list = current ?? [];
      if (list.some((choice) => choice.path === trimmed)) {
        return list.map((choice) => (choice.path === trimmed ? { ...choice, selected: true } : choice));
      }
      return [...list, { added: false, error: null, kind: null, label: folderLabel(trimmed), path: trimmed, selected: true }];
    });
  }

  async function pick() {
    if (desktopPicker) {
      const path = await pickDirectory(t("backup.pickTitle"));
      if (path) addPath(path);
      return;
    }
    setTyping(true);
  }

  function submitTyped(event: FormEvent) {
    event.preventDefault();
    addPath(typedPath);
    setTypedPath("");
    setTyping(false);
  }

  async function save() {
    if (!choices) return;
    setSaving(true);
    const next = await Promise.all(
      choices.map(async (choice) => {
        if (!choice.selected || choice.added) return choice;
        try {
          await addBackupSource(choice.path, choice.label, client);
          return { ...choice, added: true, error: null };
        } catch (caught) {
          return { ...choice, error: backupErrorKey(caught) };
        }
      }),
    );
    setChoices(next);
    setSaving(false);
    if (next.every((choice) => !choice.selected || choice.added)) onNext();
  }

  const selectedCount = choices?.filter((choice) => choice.selected).length ?? 0;
  const hasErrors = choices?.some((choice) => choice.selected && choice.error) ?? false;

  return (
    <SetupFrame
      description={t("firstRun.backup.body")}
      footer={
        <>
          {onBack ? (
            <Button leadingIcon={<ArrowLeft />} onClick={onBack} variant="ghost">
              {t("setup.back")}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={onNext} variant="ghost">
              {t("firstRun.backup.skip")}
            </Button>
            <Button disabled={!choices || selectedCount === 0} loading={saving} onClick={() => void save()} variant="primary">
              {t("setup.continue")}
            </Button>
          </div>
        </>
      }
      stepKey="backup"
      steps={steps}
      title={t("firstRun.backup.title")}
    >
      {choices === null ? (
        <LoadingState />
      ) : (
        <div className="grid gap-3">
          {choices.length ? (
            <ul aria-label={t("firstRun.backup.listLabel")} className="grid gap-2">
              {choices.map((choice) => (
                <li key={choice.path}>
                  <FolderChoice
                    choice={choice}
                    onToggle={(selected) =>
                      setChoices((current) => current?.map((item) => (item.path === choice.path ? { ...item, error: null, selected } : item)) ?? current)
                    }
                  />
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-lg border border-dashed border-line-strong px-4 py-6 text-center text-base text-ink-muted">{t("firstRun.backup.empty")}</p>
          )}

          {typing ? (
            <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={submitTyped}>
              <Input
                autoFocus
                className="font-mono text-sm"
                label={t("backup.typePath.label")}
                onChange={(event) => setTypedPath(event.target.value)}
                placeholder={t("backup.typePath.placeholder")}
                value={typedPath}
                wrapperClassName="flex-1"
              />
              <Button disabled={!typedPath.trim()} type="submit">
                {t("backup.typePath.add")}
              </Button>
            </form>
          ) : (
            <Button className="justify-self-start" leadingIcon={<FolderPlus />} onClick={() => void pick()} variant="ghost">
              {t("backup.addFolder")}
            </Button>
          )}

          {hasErrors ? (
            <p className="text-sm text-ink-muted" role="status">
              {t("firstRun.backup.someFailed")}
            </p>
          ) : null}
        </div>
      )}
    </SetupFrame>
  );
}

function FolderChoice({ choice, onToggle }: { choice: Choice; onToggle: (selected: boolean) => void }) {
  const Icon = backupKindIcon(choice.kind);
  const errorId = useId();

  return (
    <label
      className={cx(
        "focus-ring-within flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-[background-color,border-color] duration-150",
        choice.selected ? "border-accent bg-accent-soft" : "border-line bg-raised hover:border-line-strong",
        choice.added && "cursor-default",
      )}
    >
      <CheckboxBox
        aria-describedby={choice.error ? errorId : undefined}
        aria-label={choice.label}
        checked={choice.selected}
        disabled={choice.added}
        onChange={(event) => onToggle(event.target.checked)}
      />
      <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-raised text-accent-ink shadow-xs ring-1 ring-line">
        <Icon className="size-[1.125rem]" strokeWidth={1.75} />
      </span>
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="truncate text-base font-medium text-ink">{choice.label}</span>
        <span className="truncate font-mono text-xs text-ink-muted">{choice.path}</span>
        {choice.error ? (
          <span className="text-xs font-medium text-danger-ink" id={errorId}>
            {t(choice.error)}
          </span>
        ) : null}
      </span>
      {choice.added ? (
        <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-success-ink">
          <CircleCheck aria-hidden="true" className="size-3.5" />
          {t("firstRun.backup.added")}
        </span>
      ) : null}
    </label>
  );
}
