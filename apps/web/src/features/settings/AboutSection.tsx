import { Cloud, EyeOff, Info, ShieldCheck } from "lucide-react";

import { Card } from "../../components/Card";
import { t } from "../../i18n/dictionary";
import { tf } from "../onboarding/format";
import { SettingsCard } from "./SettingsCard";
import type { SettingsController } from "./useSettingsController";

/** Ajustes › Acerca de: version, what Telegram can see, and the Telegram API notice. */
export function AboutSection({ controller }: { controller: SettingsController }) {
  const savedVersion = controller.values?.values.app_version?.value;
  const version = controller.desktop?.version ?? (typeof savedVersion === "string" ? savedVersion : null);

  return (
    <div className="grid gap-4">
      <SettingsCard
        description={
          <>
            {t("app.tagline")}
            {version ? <span className="mt-1 block font-mono text-xs tabular-nums">{tf("about.version", { version })}</span> : null}
          </>
        }
        icon={<Info />}
        title={t("app.brand")}
      />

      <Card aria-labelledby="privacy-title" as="section" padding="md" tone="muted">
        <h2 className="flex items-center gap-2 text-base font-semibold text-ink" id="privacy-title">
          <ShieldCheck aria-hidden="true" className="size-[1.125rem] text-accent-ink" strokeWidth={1.75} />
          {t("account.privacy.title")}
        </h2>
        <ul className="mt-3 grid gap-2.5 text-sm text-ink-muted">
          <li className="flex gap-2.5">
            <EyeOff aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {t("account.privacy.encrypted")}
          </li>
          <li className="flex gap-2.5">
            <Cloud aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {t("account.privacy.telegramSees")}
          </li>
          <li className="flex gap-2.5">
            <ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {t("account.privacy.noServers")}
          </li>
        </ul>
        <p className="mt-4 text-sm font-medium text-ink">{t("about.telegramApi")}</p>
        <p className="mt-1 text-xs text-ink-subtle">{t("about.noGuarantee")}</p>
      </Card>
    </div>
  );
}
