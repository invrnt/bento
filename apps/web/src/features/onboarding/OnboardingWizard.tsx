import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { Bot, Check, ChevronLeft, ChevronRight, Cpu, Database, FolderOpen, ListChecks, ShieldCheck } from "lucide-react";

import { Badge } from "../../components/Badge";
import { BrandMark } from "../../components/BrandMark";
import { Button } from "../../components/Button";
import { Callout } from "../../components/Callout";
import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import type { SettingsController } from "../settings/useSettingsController";

const steps = ["data", "storage", "ai", "review"] as const;

const stepLabels: Record<(typeof steps)[number], MessageKey> = {
  ai: "onboarding.step.ai",
  data: "onboarding.step.data",
  review: "onboarding.step.review",
  storage: "onboarding.step.storage",
};

export function OnboardingWizard({ controller, onComplete }: { controller: SettingsController; onComplete: () => void }) {
  const [stepIndex, setStepIndex] = useState(0);
  const [isFinishing, setIsFinishing] = useState(false);
  const dialogRef = useRef<HTMLElement>(null);
  const step = steps[stepIndex];

  useEffect(() => {
    dialogRef.current?.querySelector<HTMLElement>("button:not(:disabled), input, select")?.focus();
  }, [step]);

  function trapFocus(event: KeyboardEvent) {
    if (event.key !== "Tab") return;
    const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [tabindex='0']") ?? [])];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }

  async function finish() {
    setIsFinishing(true);
    const result = await controller.validate(true);
    if (result?.valid) {
      await controller.save();
      onComplete();
    }
    setIsFinishing(false);
  }

  function next() {
    if (step === "storage" && controller.draft.storage_backend === undefined) controller.setValue("storage_backend", "local");
    if (step === "ai") {
      if (controller.draft.ocr_provider === undefined) controller.setValue("ocr_provider", "disabled");
      if (controller.draft.embeddings_provider === undefined) controller.setValue("embeddings_provider", "disabled");
    }
    setStepIndex((current) => Math.min(steps.length - 1, current + 1));
  }

  return (
    <div
      aria-labelledby="onboarding-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid animate-fade-in overflow-y-auto bg-scrim p-4 backdrop-blur-sm sm:p-6"
      onKeyDown={trapFocus}
      role="dialog"
    >
      <section className="m-auto flex w-full max-w-3xl animate-pop-in flex-col overflow-hidden rounded-2xl border border-line bg-raised shadow-xl" ref={dialogRef}>
        <header className="border-b border-line px-6 pb-5 pt-6 sm:px-8 sm:pt-7">
          <div className="flex items-center gap-3.5">
            <BrandMark className="size-10" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink-muted">{t("onboarding.eyebrow")}</p>
              <h1 className="text-2xl font-semibold tracking-tighter text-ink" id="onboarding-title">{t("onboarding.title")}</h1>
            </div>
          </div>
          <p className="mt-3 max-w-2xl text-base text-ink-muted">{t("onboarding.subtitle")}</p>
          <ol aria-label={t("onboarding.progress.label")} className="mt-6 flex items-center gap-2">
            {steps.map((item, index) => {
              const done = index < stepIndex;
              const current = index === stepIndex;
              return (
                <li className={cx("flex min-w-0 items-center gap-2", index < steps.length - 1 && "flex-1")} key={item}>
                  <span
                    aria-hidden="true"
                    className={cx(
                      "grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold tabular-nums transition-colors duration-200",
                      done && "bg-success-soft text-success-ink",
                      current && "bg-accent text-on-accent shadow-sheen-accent",
                      !done && !current && "bg-sunken text-ink-subtle",
                    )}
                  >
                    {done ? <Check className="size-3.5" strokeWidth={2.5} /> : index + 1}
                  </span>
                  <span className={cx("truncate text-sm font-medium", current ? "text-ink" : "hidden text-ink-muted sm:inline")}>{t(stepLabels[item])}</span>
                  <span className="sr-only">{done ? t("onboarding.progress.complete") : current ? t("onboarding.progress.current") : t("onboarding.progress.pending")}</span>
                  {index < steps.length - 1 ? (
                    <span aria-hidden="true" className={cx("h-px min-w-4 flex-1 rounded-full transition-colors duration-200", done ? "bg-success" : "bg-line")} />
                  ) : null}
                </li>
              );
            })}
          </ol>
        </header>

        <div className="min-h-80 px-6 py-7 sm:px-8">
          {step === "data" ? (
            <WizardSection body={t("onboarding.data.body")} icon={<Database />} title={t("onboarding.data.title")}>
              <div className="grid gap-1.5">
                <label className="text-sm font-medium text-ink" htmlFor="onboarding-data-dir">{t("settings.data_dir.label")}</label>
                <div className="flex gap-2">
                  <input
                    className="field px-3 font-mono text-sm"
                    id="onboarding-data-dir"
                    onChange={(event) => { controller.setValue("data_dir", event.target.value); controller.setDataMigration("use-empty"); }}
                    value={String(controller.draft.data_dir ?? "")}
                  />
                  <Button
                    aria-label={t("settings.path.pick")}
                    leadingIcon={<FolderOpen />}
                    onClick={async () => { await controller.pickPath("data_dir"); controller.setDataMigration("use-empty"); }}
                  >
                    {t("settings.path.pick")}
                  </Button>
                </div>
              </div>
              <p className="mt-3 flex items-start gap-2 text-sm text-ink-muted">
                <ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-success-ink" />
                {t("onboarding.data.safe")}
              </p>
            </WizardSection>
          ) : null}
          {step === "storage" ? (
            <WizardSection body={t("onboarding.storage.body")} icon={<Bot />} title={t("onboarding.storage.title")}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Choice active={controller.draft.storage_backend !== "telegram"} body={t("onboarding.storage.local.body")} label={t("onboarding.storage.local.title")} onClick={() => controller.setValue("storage_backend", "local")} recommended />
                <Choice active={controller.draft.storage_backend === "telegram"} body={t("onboarding.storage.telegram.body")} label={t("onboarding.storage.telegram.title")} onClick={() => controller.setValue("storage_backend", "telegram")} />
              </div>
              {controller.draft.storage_backend === "telegram" ? <TelegramSetup controller={controller} /> : null}
            </WizardSection>
          ) : null}
          {step === "ai" ? (
            <WizardSection body={t("onboarding.ai.body")} icon={<Cpu />} title={t("onboarding.ai.title")}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Choice active={controller.draft.ocr_provider === "rapidocr"} body={t("onboarding.ai.ocr.body")} indicator="check" label={t("onboarding.ai.ocr.title")} onClick={() => controller.setValue("ocr_provider", controller.draft.ocr_provider === "rapidocr" ? "disabled" : "rapidocr")} />
                <Choice active={controller.draft.embeddings_provider === "jina"} body={t("onboarding.ai.embeddings.body")} indicator="check" label={t("onboarding.ai.embeddings.title")} onClick={() => controller.setValue("embeddings_provider", controller.draft.embeddings_provider === "jina" ? "disabled" : "jina")} />
              </div>
              <Callout className="mt-4" tone="neutral">{t("onboarding.ai.optional")}</Callout>
            </WizardSection>
          ) : null}
          {step === "review" ? (
            <WizardSection body={t("onboarding.review.body")} icon={<ListChecks />} title={t("onboarding.review.title")}>
              <dl className="divide-y divide-line overflow-hidden rounded-lg border border-line">
                <Review label={t("settings.data_dir.label")} mono value={String(controller.draft.data_dir ?? t("common.unknown"))} />
                <Review label={t("settings.storage_backend.label")} value={controller.draft.storage_backend === "telegram" ? t("settings.storage.telegram") : t("settings.storage.local")} />
                <Review label={t("settings.category.ai")} value={controller.draft.ocr_provider === "rapidocr" || controller.draft.embeddings_provider === "jina" ? t("onboarding.review.aiEnabled") : t("onboarding.review.aiDisabled")} />
              </dl>
            </WizardSection>
          ) : null}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-line bg-subtle px-6 py-4 sm:px-8">
          <Button disabled={stepIndex === 0 || isFinishing} leadingIcon={<ChevronLeft />} onClick={() => setStepIndex((current) => Math.max(0, current - 1))} variant="ghost">
            {t("onboarding.back")}
          </Button>
          <span className="hidden text-sm tabular-nums text-ink-muted sm:inline">
            {t("onboarding.step.counter").replace("{current}", String(stepIndex + 1)).replace("{total}", String(steps.length))}
          </span>
          {step === "review" ? (
            <Button disabled={isFinishing} leadingIcon={<Check />} onClick={() => void finish()} variant="primary">
              {isFinishing ? t("settings.applying") : t("onboarding.finish")}
            </Button>
          ) : (
            <Button onClick={next} trailingIcon={<ChevronRight />} variant="primary">{t("onboarding.next")}</Button>
          )}
        </footer>
      </section>
    </div>
  );
}

function WizardSection({ body, children, icon, title }: { body: string; children: ReactNode; icon: ReactNode; title: string }) {
  return (
    <section>
      <div className="mb-6 flex gap-4">
        <span aria-hidden="true" className="grid size-11 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent-ink [&_svg]:size-5">{icon}</span>
        <div className="min-w-0">
          <h2 className="text-xl font-semibold text-ink">{title}</h2>
          <p className="mt-1 text-base text-ink-muted">{body}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function Choice({ active, body, indicator = "radio", label, onClick, recommended = false }: { active: boolean; body: string; indicator?: "check" | "radio"; label: string; onClick: () => void; recommended?: boolean }) {
  return (
    <button
      aria-pressed={active}
      className={cx(
        "focus-ring relative grid gap-2 rounded-lg border p-4 text-left transition-[background-color,border-color,box-shadow] duration-150",
        active ? "border-accent bg-accent-soft shadow-xs" : "border-line bg-raised hover:border-line-strong hover:shadow-sm",
      )}
      onClick={onClick}
      type="button"
    >
      <span className="flex items-start justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2.5">
          <span
            aria-hidden="true"
            className={cx(
              "grid size-[1.125rem] shrink-0 place-items-center border transition-colors duration-150",
              indicator === "radio" ? "rounded-full" : "rounded-[5px]",
              active ? "border-accent bg-accent text-on-accent" : "border-line-strong bg-raised",
            )}
          >
            {active ? (indicator === "radio" ? <span className="size-1.5 rounded-full bg-on-accent" /> : <Check className="size-3" strokeWidth={3} />) : null}
          </span>
          <strong className="font-semibold text-ink">{label}</strong>
        </span>
        {recommended ? <Badge tone="shu">{t("onboarding.recommended")}</Badge> : null}
      </span>
      <span className="pl-7 text-sm text-ink-muted">{body}</span>
    </button>
  );
}

function Review({ label, mono = false, value }: { label: string; mono?: boolean; value: string }) {
  return (
    <div className="grid gap-1 bg-raised px-4 py-3 sm:grid-cols-[11rem_1fr] sm:gap-4">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className={cx("break-all font-medium text-ink", mono && "font-mono text-sm")}>{value}</dd>
    </div>
  );
}

const telegramSecrets = ["telegram_bot_token", "telegram_api_id", "telegram_api_hash", "telegram_raw_chat_id", "telegram_thumbs_chat_id", "telegram_journal_chat_id", "telegram_webhook_secret"] as const;
function TelegramSetup({ controller }: { controller: SettingsController }) {
  const probe = controller.validation?.probes.find((item) => item.key === "telegram_bot_api_url");
  return (
    <div className="mt-4 rounded-lg border border-line bg-subtle p-4">
      <h3 className="font-semibold text-ink">{t("onboarding.telegram.title")}</h3>
      <p className="mt-0.5 text-sm text-ink-muted">{t("onboarding.telegram.body")}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {telegramSecrets.map((key) => (
          <label className="grid gap-1.5 text-sm font-medium text-ink" key={key}>
            <span>{t(`settings.${key}.label`)}</span>
            <input
              autoComplete="new-password"
              className="field px-3 font-mono text-sm"
              onChange={(event) => controller.setSecret(key, event.target.value ? { operation: "set", value: event.target.value } : null)}
              type="password"
              value={controller.secretEdits[key]?.operation === "set" ? controller.secretEdits[key].value : ""}
            />
          </label>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button onClick={() => void controller.probe("telegram_bot_api_url", "telegram")} size="sm">{t("settings.probe.action")}</Button>
        {probe ? (
          <span role="status">
            <Badge dot tone={probe.status === "ok" ? "success" : "danger"}>{probe.status === "ok" ? t("settings.probe.ok") : t("settings.probe.failed")}</Badge>
          </span>
        ) : null}
      </div>
    </div>
  );
}
