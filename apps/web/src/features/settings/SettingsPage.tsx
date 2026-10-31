import { useEffect } from "react";
import type { MouseEvent } from "react";

import { apiClient } from "../../api/client";
import type { ApiClient } from "../../api/client";
import { getAccount } from "../../api/account";
import { getVault } from "../../api/vault";
import { PageHeader } from "../../components/PageHeader";
import { t } from "../../i18n/dictionary";
import type { Locale } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { usePolledResource } from "../../lib/usePolledResource";
import { AccountSection } from "../account/AccountSection";
import { activityStore } from "../activity/activityStore";
import { DevicesSection } from "../devices/DevicesSection";
import { AboutSection } from "./AboutSection";
import { AdvancedSection, SettingsApplyStatus, SettingsDirtyBar } from "./AdvancedSection";
import { BackupSection } from "./BackupSection";
import { GeneralSection } from "./GeneralSection";
import { settingsPath, settingsSections } from "./sections";
import type { SettingsSection } from "./sections";
import { SmartSearchSection } from "./SmartSearchSection";
import type { SettingsController } from "./useSettingsController";

export type SettingsPageProps = {
  client?: ApiClient;
  controller: SettingsController;
  focus?: "recovery" | null;
  onLocaleChange?: (locale: Locale) => void;
  onNavigate: (href: string) => void;
  /** Reopens Telegram setup (first run or unlock) from Cuenta y nube / Dispositivos. */
  onStartSetup?: () => void;
  pollIntervalMs?: number;
  section: SettingsSection;
};

/** Ajustes: General, Cuenta y nube, Dispositivos, Respaldo, Búsqueda inteligente, Avanzado, Acerca de. */
export function SettingsPage({
  client = apiClient,
  controller,
  focus = null,
  onLocaleChange,
  onNavigate,
  onStartSetup,
  pollIntervalMs,
  section,
}: SettingsPageProps) {
  const needsCloud = section === "account" || section === "devices" || section === "backup";
  const needsAccount = section === "account" || section === "devices";
  const vault = usePolledResource(() => (needsCloud ? getVault(client) : Promise.resolve(null)), null, needsCloud ? section : "none");
  const account = usePolledResource(() => (needsAccount ? getAccount(client) : Promise.resolve(null)), null, needsAccount ? section : "none");
  const active = settingsSections.find((item) => item.id === section) ?? settingsSections[0];

  useEffect(() => {
    if (focus !== "recovery" || section !== "account" || vault.isLoading) return;
    const target = document.getElementById("recovery");
    target?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    target?.focus({ preventScroll: true });
  }, [focus, section, vault.isLoading]);

  function refreshCloud() {
    void vault.refresh();
    void account.refresh();
    // Reviews, removals and new kits clear Activity items: update the status pill now.
    void activityStore.refresh();
  }

  function go(event: MouseEvent<HTMLAnchorElement>, href: string) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    onNavigate(href);
  }

  return (
    <div className="mx-auto w-full max-w-6xl pb-28">
      <PageHeader className="mb-6" description={t("settingsNav.description")} title={t("settings.header.title")} />

      <div className="grid gap-6 lg:grid-cols-[13.5rem_minmax(0,1fr)]">
        <nav aria-label={t("settings.categories.label")} className="-mx-1 lg:sticky lg:top-0 lg:mx-0 lg:self-start">
          <ul className="flex gap-1 overflow-x-auto px-1 pb-1 lg:grid lg:gap-0.5 lg:overflow-visible lg:p-0">
            {settingsSections.map((item) => {
              const Icon = item.icon;
              const current = item.id === section;
              const href = settingsPath(item.id);
              return (
                <li key={item.id}>
                  <a
                    aria-current={current ? "page" : undefined}
                    className={cx(
                      "focus-ring group/category flex h-9 min-w-max items-center gap-3 rounded-md px-2.5 text-left text-base font-medium transition-[background-color,color,box-shadow] duration-150",
                      current ? "bg-raised text-ink shadow-sm ring-1 ring-line" : "text-ink-muted hover:bg-hover hover:text-ink",
                    )}
                    href={href}
                    onClick={(event) => go(event, href)}
                  >
                    <Icon
                      aria-hidden="true"
                      className={cx("size-[1.125rem] shrink-0 transition-colors", current ? "text-accent-ink" : "text-ink-subtle group-hover/category:text-ink-muted")}
                      strokeWidth={1.75}
                    />
                    {t(item.label)}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>

        <section aria-labelledby="settings-section-title" className="grid min-w-0 content-start gap-4">
          <h2 className="sr-only" id="settings-section-title">
            {t(active.label)}
          </h2>
          {section === "general" ? <GeneralSection desktop={controller.desktop} onLocaleChange={onLocaleChange} /> : null}
          {section === "account" ? (
            <AccountSection account={account.data} client={client} onChanged={refreshCloud} onConnect={onStartSetup} vault={vault.data} />
          ) : null}
          {section === "devices" ? (
            <DevicesSection
              accountName={account.data?.account?.display_name ?? null}
              client={client}
              onChanged={refreshCloud}
              onConnect={onStartSetup}
              pairingPollIntervalMs={pollIntervalMs}
              vault={vault.data}
            />
          ) : null}
          {section === "backup" ? <BackupSection client={client} pollIntervalMs={pollIntervalMs} vault={vault.data} /> : null}
          {section === "smart-search" ? <SmartSearchSection controller={controller} /> : null}
          {section === "advanced" ? <AdvancedSection controller={controller} /> : null}
          {section === "about" ? <AboutSection controller={controller} /> : null}
          {section === "smart-search" || section === "advanced" ? <SettingsApplyStatus controller={controller} /> : null}
        </section>
      </div>

      {controller.dirty ? <SettingsDirtyBar controller={controller} /> : null}
    </div>
  );
}
