import { useMemo, useState } from "react";
import {
  AppWindow,
  CircleAlert,
  CircleCheck,
  Download,
  FolderOpen,
  Globe,
  HardDriveDownload,
  KeyRound,
  LockKeyhole,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";

import { Badge, StatusDot } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import type { CalloutTone } from "../../components/Callout";
import { Card } from "../../components/Card";
import { Checkbox } from "../../components/Checkbox";
import { Dialog } from "../../components/Dialog";
import { Input } from "../../components/Input";
import { Select } from "../../components/Select";
import { Spinner } from "../../components/Spinner";
import { ErrorState, LoadingState } from "../../components/States";
import { hasMessage, t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import type { ApplyMode, FieldIssue, SettingDefinition } from "../../api/settings";
import { formatBytes } from "../onboarding/format";
import type { SettingsController } from "./useSettingsController";

const groupOrder = ["storage", "backup", "performance", "ai", "telegram", "general", "advanced"];

/** Ajustes › Avanzado: every registry setting with validation, restart scope and portability tools. */
export function AdvancedSection({ controller }: { controller: SettingsController }) {
  const [query, setQuery] = useState("");
  const fields = useMemo(() => controller.schema?.fields ?? [], [controller.schema]);
  const groups = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    const matching = fields.filter((field) => {
      if (!normalized) return true;
      return `${fieldLabel(field)} ${fieldHelp(field)} ${field.key} ${field.env_aliases.join(" ")}`.toLocaleLowerCase().includes(normalized);
    });
    const names = [...new Set(matching.map((field) => field.group))].sort((left, right) => groupRank(left) - groupRank(right));
    return names.map((name) => ({ fields: matching.filter((field) => field.group === name), name }));
  }, [fields, query]);

  if (controller.isLoading && !controller.schema) return <LoadingState />;
  if (controller.error && !controller.schema) return <ErrorState body={t("settings.settingsError.body")} onRetry={() => void controller.refresh()} />;

  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <p className="max-w-xl text-base text-ink-muted">{t("advanced.body")}</p>
        <Input
          hideLabel
          label={t("settings.search.label")}
          leadingIcon={<Search />}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("settings.search.placeholder")}
          type="search"
          value={query}
          wrapperClassName="w-full sm:w-72"
        />
      </div>

      <div className="grid gap-3 empty:hidden">
        {controller.desktop?.recoveryMode ? <Notice tone="danger" title={t("settings.recovery.title")} body={t("settings.recovery.body")} /> : null}
        {!controller.desktop ? <Notice tone="info" title={t("settings.headless.title")} body={t("settings.headless.body")} /> : null}
        {controller.desktop?.secureStorage === "unavailable" ? <Notice tone="warning" title={t("settings.secureStorage.title")} body={t("settings.secureStorage.body")} /> : null}
        {controller.conflict ? (
          <Callout
            action={<Button leadingIcon={<RefreshCw />} onClick={() => void controller.refresh()} size="sm">{t("settings.conflict.reload")}</Button>}
            role="alert"
            title={t("settings.conflict.title")}
            tone="warning"
          >
            {t("settings.conflict.body")}
          </Callout>
        ) : null}
      </div>

      {!query ? <SpaceOverview controller={controller} /> : null}

      <div aria-live="polite" className="grid min-w-0 content-start gap-4">
        {groups.length ? (
          groups.map((group) => (
            <Card aria-labelledby={`settings-group-${group.name}`} as="section" className="overflow-hidden" key={group.name} padding="none">
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line px-5 py-4">
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold text-ink" id={`settings-group-${group.name}`}>{groupLabel(group.name)}</h2>
                  <p className="mt-0.5 text-sm text-ink-muted">{groupHelp(group.name)}</p>
                </div>
                <Button leadingIcon={<RotateCcw />} onClick={() => controller.resetGroup(group.name)} size="sm" variant="ghost">
                  {t("settings.reset.section")}
                </Button>
              </div>
              <div className="divide-y divide-line">
                {group.fields.map((field) => <SettingField controller={controller} field={field} key={field.key} />)}
              </div>
            </Card>
          ))
        ) : (
          <p className="rounded-lg border border-dashed border-line-strong px-5 py-10 text-center text-base text-ink-muted">{t("settings.search.empty")}</p>
        )}
        {!query ? <Card padding="none"><AdvancedTools controller={controller} /></Card> : null}
      </div>
    </div>
  );
}

/** Validation, apply progress and outcome, shown under any section that edits settings. */
export function SettingsApplyStatus({ controller }: { controller: SettingsController }) {
  return (
    <div className="grid gap-4 empty:hidden">
      {controller.validation ? <ValidationSummary controller={controller} /> : null}
      {controller.applyProgress.length ? <ApplyProgressList controller={controller} /> : null}
      {controller.applyOutcome?.rolledBack ? <Notice tone="danger" title={t("settings.rollback.title")} body={t("settings.rollback.body")} /> : null}
      {controller.applyOutcome && !controller.applyOutcome.rolledBack ? <Notice tone="success" title={t("settings.saved.title")} body={t("settings.saved.body")} /> : null}
    </div>
  );
}

function SpaceOverview({ controller }: { controller: SettingsController }) {
  const [confirmReclaim, setConfirmReclaim] = useState(false);
  const maintenance = controller.publicSettings?.storage_maintenance;
  return (
    <section aria-label={t("advanced.space.label")} className="grid gap-3">
      <div className="grid gap-3 lg:grid-cols-2">
        {maintenance ? (
          <Card className="flex flex-col gap-4" padding="md">
            <div className="flex items-start gap-3">
              <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-accent-soft text-accent-ink">
                <HardDriveDownload className="size-[1.125rem]" strokeWidth={1.75} />
              </span>
              <div className="min-w-0">
                <h3 className="font-semibold text-ink">{t("settings.space.title")}</h3>
                <p className="mt-0.5 text-sm text-ink-muted">
                  {t("settings.space.reclaimable")}: <span className="font-medium tabular-nums text-ink">{formatBytes(maintenance.reclaimable_bytes)}</span>
                </p>
              </div>
            </div>
            <Button
              className="self-start"
              disabled={!maintenance.can_reclaim}
              leadingIcon={<HardDriveDownload />}
              loading={controller.isReclaiming}
              onClick={() => setConfirmReclaim(true)}
              size="sm"
            >
              {controller.isReclaiming ? t("settings.space.reclaiming") : t("settings.space.action")}
            </Button>
          </Card>
        ) : null}
        <Card className={cx("flex items-start gap-3", !maintenance && "lg:col-span-2")} padding="md" tone="muted">
          <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-md bg-raised text-ink-muted shadow-xs">
            {controller.desktop ? <AppWindow className="size-[1.125rem]" strokeWidth={1.75} /> : <Globe className="size-[1.125rem]" strokeWidth={1.75} />}
          </span>
          <div className="min-w-0">
            <h3 className="font-semibold text-ink">{t("settings.desktopStatus.title")}</h3>
            <p className="mt-0.5 text-sm text-ink-muted">{controller.desktop ? t("settings.desktopStatus.desktop") : t("settings.desktopStatus.browser")}</p>
          </div>
        </Card>
      </div>
      {controller.reclaimResult ? <Callout role="status" tone="success">{t("settings.space.success")} {formatBytes(controller.reclaimResult.freed_bytes)}</Callout> : null}
      {controller.reclaimError ? <Callout role="alert" tone="danger">{t("settings.space.error")}</Callout> : null}
      <Dialog
        actions={
          <>
            <Button onClick={() => setConfirmReclaim(false)} variant="ghost">{t("common.close")}</Button>
            <Button leadingIcon={<HardDriveDownload />} onClick={() => { setConfirmReclaim(false); void controller.reclaim(); }} variant="primary">{t("settings.space.confirm")}</Button>
          </>
        }
        icon={<HardDriveDownload />}
        onOpenChange={setConfirmReclaim}
        open={confirmReclaim}
        title={t("settings.space.dialogTitle")}
      >
        <p>{t("settings.space.dialogBody")}</p>
      </Dialog>
    </section>
  );
}

function SettingField({ controller, field }: { controller: SettingsController; field: SettingDefinition }) {
  const current = controller.values?.values[field.key];
  const disabled = !field.editable || field.locked;
  const error = controller.fieldErrors[field.key]?.[0];
  const probe = controller.validation?.probes.find((item) => item.key === field.key);
  return (
    <div className="grid gap-4 px-5 py-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] xl:gap-8">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-semibold text-ink">{fieldLabel(field)}</h3>
          {field.locked ? <Badge icon={<LockKeyhole />} tone="warning">{sourceLabel(current?.source ?? field.source)}</Badge> : null}
        </div>
        <p className="mt-1 text-sm text-ink-muted">{fieldHelp(field)}</p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <Badge>{sourceLabel(current?.source ?? field.source)}</Badge>
          <Badge>{applyLabel(field.apply_mode)}</Badge>
        </div>
        {field.locked && field.env_aliases[0] ? (
          <p className="mt-2 text-xs text-ink-muted">
            {t("settings.locked.byEnvironment")} <code className="rounded-xs bg-sunken px-1 py-0.5 text-2xs text-ink">{field.env_aliases[0]}</code>
          </p>
        ) : null}
      </div>
      <div className="min-w-0 self-center">
        {field.secret ? <SecretControl controller={controller} disabled={disabled} field={field} /> : <ValueControl controller={controller} disabled={disabled} field={field} />}
        {field.key === "data_dir" && JSON.stringify(controller.draft.data_dir) !== JSON.stringify(controller.values?.values.data_dir?.value) ? <DataMigrationChoice controller={controller} /> : null}
        {field.probe && field.probe !== "storage" && controller.desktop ? (
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Button onClick={() => void controller.probe(field.key, field.probe!)} size="sm">{t("settings.probe.action")}</Button>
            {probe ? (
              <span role="status">
                <Badge dot tone={probe.status === "ok" ? "success" : "danger"}>{probe.status === "ok" ? t("settings.probe.ok") : t("settings.probe.failed")}</Badge>
              </span>
            ) : null}
          </div>
        ) : null}
        {error ? (
          <p className="mt-2 flex items-start gap-1.5 text-sm font-medium text-danger-ink" id={`${field.key}-error`} role="alert">
            <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {issueMessage(error)}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function ValueControl({ controller, disabled, field }: { controller: SettingsController; disabled: boolean; field: SettingDefinition }) {
  const value = controller.draft[field.key];
  const invalid = Boolean(controller.fieldErrors[field.key]);
  const common = { "aria-describedby": invalid ? `${field.key}-error` : undefined, "aria-invalid": invalid || undefined, "aria-label": fieldLabel(field), disabled, id: `setting-${field.key}` };
  if (field.type === "boolean") return <Checkbox checked={Boolean(value)} label={fieldLabel(field)} onChange={(event) => controller.setValue(field.key, event.target.checked)} {...common} />;
  if (field.type === "choice") {
    return (
      <Select
        hideLabel
        label={fieldLabel(field)}
        onChange={(event) => controller.setValue(field.key, event.target.value)}
        options={field.constraints.choices.map((choice) => ({ label: choiceLabel(field.key, choice), value: choice }))}
        value={String(value ?? "")}
        {...common}
      />
    );
  }
  const numeric = field.type === "integer" || field.type === "number";
  const input = (
    <input
      className={cx("field px-3", (field.type === "path" || numeric) && "font-mono text-sm")}
      max={field.constraints.maximum ?? undefined}
      min={field.constraints.minimum ?? undefined}
      onChange={(event) => controller.setValue(field.key, numeric ? event.target.valueAsNumber : event.target.value)}
      step={field.type === "integer" ? 1 : field.type === "number" ? "any" : undefined}
      type={numeric ? "number" : "text"}
      value={String(value ?? "")}
      {...common}
    />
  );
  if (field.type !== "path") return input;
  return (
    <div className="flex gap-2">
      {input}
      {controller.desktop ? (
        <Button aria-label={t("settings.path.pick")} disabled={disabled} leadingIcon={<FolderOpen />} onClick={() => void controller.pickPath(field.key, field.key === "jina_model_path")}>
          <span className="hidden sm:inline">{t("settings.path.pick")}</span>
        </Button>
      ) : null}
    </div>
  );
}

function SecretControl({ controller, disabled, field }: { controller: SettingsController; disabled: boolean; field: SettingDefinition }) {
  const current = controller.values?.values[field.key];
  const edit = controller.secretEdits[field.key];
  const canEdit = !disabled && Boolean(controller.desktop) && controller.desktop?.secureStorage === "available";
  return (
    <div className="grid gap-3 rounded-lg border border-line bg-subtle p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-2 text-base font-medium text-ink">
          <StatusDot tone={current?.configured ? "success" : "neutral"} />
          {current?.configured ? t("settings.secret.configured") : t("settings.secret.missing")}
        </span>
        {!controller.desktop ? <Badge icon={<LockKeyhole />}>{t("settings.secret.desktopOnly")}</Badge> : null}
      </div>
      {edit?.operation === "set" ? (
        <input
          aria-label={fieldLabel(field)}
          autoComplete="new-password"
          className="field px-3 font-mono text-sm"
          onBlur={(event) => { if (!event.target.value) controller.setSecret(field.key, null); }}
          onChange={(event) => controller.setSecret(field.key, { operation: "set", value: event.target.value })}
          type="password"
          value={edit.value}
        />
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button disabled={!canEdit} leadingIcon={<KeyRound />} onClick={() => controller.setSecret(field.key, { operation: "set", value: "" })} size="sm">
          {current?.configured ? t("settings.secret.change") : t("settings.secret.add")}
        </Button>
        {current?.configured ? (
          <Button
            disabled={!canEdit}
            leadingIcon={<Trash2 />}
            onClick={() => controller.setSecret(field.key, edit?.operation === "clear" ? null : { operation: "clear" })}
            size="sm"
            variant={edit?.operation === "clear" ? "danger" : "danger-ghost"}
          >
            {edit?.operation === "clear" ? t("settings.secret.clearPending") : t("settings.secret.clear")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function DataMigrationChoice({ controller }: { controller: SettingsController }) {
  const options = [
    { body: t("settings.dataMigration.copyHelp"), label: t("settings.dataMigration.copy"), value: "copy" as const },
    { body: t("settings.dataMigration.emptyHelp"), label: t("settings.dataMigration.empty"), value: "use-empty" as const },
  ];
  return (
    <fieldset className="mt-3 grid gap-2 rounded-lg border border-warning/35 bg-warning-soft p-3.5">
      <legend className="sr-only">{t("settings.dataMigration.title")}</legend>
      <p aria-hidden="true" className="font-semibold text-ink">{t("settings.dataMigration.title")}</p>
      <p className="text-sm text-ink-muted">{t("settings.dataMigration.body")}</p>
      <div className="mt-1 grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <label
            className="focus-ring-within flex cursor-pointer items-start gap-2.5 rounded-md border border-line bg-raised p-3 text-sm transition-colors duration-150 hover:border-line-strong has-[:checked]:border-accent has-[:checked]:bg-accent-soft"
            key={option.value}
          >
            <input checked={controller.dataMigration === option.value} className="peer sr-only" name="data-migration" onChange={() => controller.setDataMigration(option.value)} type="radio" />
            <span aria-hidden="true" className="mt-0.5 size-4 shrink-0 rounded-full border border-line-strong bg-raised transition-[border-width,border-color] duration-150 peer-checked:border-[5px] peer-checked:border-accent" />
            <span className="grid gap-0.5">
              <strong className="font-semibold text-ink">{option.label}</strong>
              <span className="text-xs text-ink-muted">{option.body}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function SettingsDirtyBar({ controller }: { controller: SettingsController }) {
  const restart = controller.validation?.restart_plan;
  const changedKeys = new Set([
    ...Object.keys(controller.secretEdits),
    ...Object.entries(controller.draft).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(controller.values?.values[key]?.value)).map(([key]) => key),
  ]);
  const predictedMode = controller.schema?.fields.filter((field) => changedKeys.has(field.key)).map((field) => field.apply_mode).sort((left, right) => applyModeRank(right) - applyModeRank(left))[0] ?? "live";
  const needsRestart = (restart?.mode ?? predictedMode) !== "live";
  const needsMigrationChoice = changedKeys.has("data_dir") && !controller.dataMigration;
  return (
    <div
      aria-label={t("settings.unsaved.label")}
      className="fixed inset-x-3 bottom-4 z-30 mx-auto flex max-w-3xl animate-slide-up flex-col gap-3 rounded-xl border border-line bg-raised/95 p-3 pl-4 shadow-lg backdrop-blur-md sm:flex-row sm:items-center sm:justify-between md:left-[calc(15rem+0.75rem)]"
      role="region"
    >
      <div className="flex min-w-0 items-center gap-3">
        <StatusDot className="size-2" pulse tone="accent" />
        <div className="min-w-0">
          <p className="font-semibold text-ink">{t("settings.unsaved.title")}</p>
          <p className="truncate text-sm text-ink-muted">{needsMigrationChoice ? t("settings.dataMigration.required") : needsRestart ? t("settings.unsaved.restart") : t("settings.unsaved.body")}</p>
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        <Button disabled={controller.isApplying} onClick={controller.discard} size="sm" variant="ghost">{t("settings.discard")}</Button>
        <Button disabled={controller.isApplying || controller.isValidating} onClick={() => void controller.validate(true)} size="sm">
          {controller.isValidating ? t("settings.validating") : t("settings.validate")}
        </Button>
        <Button disabled={controller.isApplying || needsMigrationChoice} onClick={() => void controller.save()} size="sm" variant="primary">
          {controller.isApplying ? t("settings.applying") : needsRestart ? t("settings.saveRestart") : t("settings.save")}
        </Button>
      </div>
    </div>
  );
}

function ValidationSummary({ controller }: { controller: SettingsController }) {
  const result = controller.validation;
  if (!result) return null;
  return (
    <div aria-live="assertive">
      <Callout title={result.valid ? t("settings.validation.ok") : t("settings.validation.failed")} tone={result.valid ? "success" : "danger"}>
        <p>{result.valid ? restartDescription(result.restart_plan.mode) : t("settings.validation.fix")}</p>
        {result.warnings.length ? (
          <ul className="mt-2 grid list-disc gap-1 pl-5 text-sm">
            {result.warnings.map((warning) => <li key={`${warning.key}-${warning.code}`}>{issueMessage(warning)}</li>)}
          </ul>
        ) : null}
      </Callout>
    </div>
  );
}

function ApplyProgressList({ controller }: { controller: SettingsController }) {
  return (
    <Card aria-live="polite" as="section" padding="sm" role="status">
      <h2 className="font-semibold text-ink">{t("settings.progress.title")}</h2>
      <ol className="mt-3 grid gap-2.5">
        {controller.applyProgress.map((event, index) => (
          <li className="flex items-center gap-2.5 text-base text-ink" key={`${event.phase}-${index}`}>
            {event.status === "ok" ? (
              <CircleCheck aria-hidden="true" className="size-4 shrink-0 text-success-ink" />
            ) : event.status === "failed" ? (
              <CircleAlert aria-hidden="true" className="size-4 shrink-0 text-danger-ink" />
            ) : (
              <Spinner className="text-accent-ink" />
            )}
            <span>{progressLabel(event.phase)}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function AdvancedTools({ controller }: { controller: SettingsController }) {
  const unknown = controller.importPreview?.unknown_keys ?? controller.importPreview?.unknown;
  return (
    <div className="px-5 py-5">
      <h3 className="font-semibold text-ink">{t("settings.portability.title")}</h3>
      <p className="mt-0.5 text-sm text-ink-muted">{t("settings.portability.body")}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <label className="focus-ring-within inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-sm border border-line bg-raised px-2.5 text-sm font-medium text-ink shadow-xs transition-colors duration-150 hover:border-line-strong hover:bg-subtle">
          <Upload aria-hidden="true" className="size-3.5" />
          {t("settings.import.action")}
          <input accept=".env,text/plain" className="sr-only" onChange={(event) => { const file = event.target.files?.[0]; if (file) void controller.importPreviewFromFile(file); event.target.value = ""; }} type="file" />
        </label>
        <Button leadingIcon={<Download />} onClick={() => void controller.exportSafe()} size="sm">{t("settings.export.action")}</Button>
      </div>
      {controller.importPreview ? (
        <Callout
          action={
            <>
              <Button onClick={() => controller.importValues()} size="sm" variant="primary">{t("settings.import.use")}</Button>
              <Button onClick={() => controller.dismissImport()} size="sm" variant="ghost">{t("common.close")}</Button>
            </>
          }
          className="mt-4"
          role="status"
          title={t("settings.import.previewTitle")}
          tone="info"
        >
          <p>{t("settings.import.previewBody")}</p>
          {unknown?.length ? <p className="mt-1.5 text-sm text-warning-ink">{t("settings.import.unknown")}: <span className="font-mono">{unknown.join(", ")}</span></p> : null}
        </Callout>
      ) : null}
    </div>
  );
}

function Notice({ body, title, tone }: { body: string; title: string; tone: Extract<CalloutTone, "danger" | "info" | "success" | "warning"> }) {
  return <Callout role={tone === "danger" ? "alert" : "status"} title={title} tone={tone}>{body}</Callout>;
}

function fieldLabel(field: SettingDefinition) { return hasMessage(field.label_key) ? t(field.label_key) : field.key.replaceAll("_", " "); }
function fieldHelp(field: SettingDefinition) { return hasMessage(field.help_key) ? t(field.help_key) : t("settings.field.defaultHelp"); }
function sourceLabel(source: string) { const key = `settings.source.${source}`; return hasMessage(key) ? t(key) : t("common.unknown"); }
function applyLabel(mode: ApplyMode) { return t(`settings.applyMode.${mode}` as MessageKey); }
function restartDescription(mode: ApplyMode) { return mode === "live" ? t("settings.validation.live") : t("settings.validation.restart"); }
function issueMessage(issue: FieldIssue) { const key = `settings.error.${issue.code}`; return hasMessage(key) ? t(key) : t("settings.error.generic"); }
function progressLabel(phase: string) { const key = `settings.progress.${phase}`; return hasMessage(key) ? t(key) : t("settings.progress.working"); }
function choiceLabel(field: string, choice: string) { const key = `settings.choice.${field}.${choice}`; return hasMessage(key) ? t(key) : choice; }
function groupRank(group: string) { const index = groupOrder.indexOf(group); return index < 0 ? groupOrder.length : index; }
function groupLabel(group: string) { const key = `advanced.group.${group}`; return hasMessage(key) ? t(key) : group; }
function groupHelp(group: string) { const key = `advanced.group.${group}.help`; return hasMessage(key) ? t(key) : t("settings.field.defaultHelp"); }
function applyModeRank(mode: ApplyMode) { return { live: 0, restart_worker: 1, restart_services: 2, restart_app: 3 }[mode]; }
