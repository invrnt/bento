import { useEffect, useState } from "react";
import { AppWindow, Languages, Palette } from "lucide-react";

import type { DesktopPlatform } from "../../api/settingsDesktop";
import { Callout } from "../../components/Callout";
import { Select } from "../../components/Select";
import { ThemeSwitcher } from "../../components/ThemeSwitcher";
import { defaultLocale, t } from "../../i18n/dictionary";
import type { Locale } from "../../i18n/dictionary";
import { setLocale, supportedLocales } from "../../i18n/locale";
import { getDesktopPreferences, hasDesktopPreferences, isLaunchAtLoginError, setDesktopPreferences } from "../onboarding/desktopHost";
import type { DesktopPreferences } from "../onboarding/desktopHost";
import { SettingsCard, ToggleRow } from "./SettingsCard";
import { UpdatePanel } from "./UpdatePanel";

const localeNames: Record<Locale, "prefs.language.es" | "prefs.language.en"> = { en: "prefs.language.en", es: "prefs.language.es" };

export type GeneralSectionProps = {
  desktop: DesktopPlatform | null;
  /** Injected in tests; defaults to `setLocale` (persists and reloads). */
  onLocaleChange?: (locale: Locale) => void;
};

/** Ajustes › General: language, theme, desktop behavior and updates. */
export function GeneralSection({ desktop, onLocaleChange = (locale) => setLocale(locale) }: GeneralSectionProps) {
  return (
    <div className="grid gap-4">
      <SettingsCard description={t("prefs.language.body")} icon={<Languages />} title={t("prefs.language.title")}>
        <div className="px-5 py-4">
          <Select
            label={t("prefs.language.label")}
            onChange={(event) => onLocaleChange(event.target.value as Locale)}
            options={supportedLocales.map((locale) => ({ label: t(localeNames[locale]), value: locale }))}
            value={defaultLocale}
            wrapperClassName="max-w-xs"
          />
        </div>
      </SettingsCard>

      <SettingsCard description={t("prefs.theme.body")} icon={<Palette />} title={t("prefs.theme.title")}>
        <div className="px-5 py-4">
          <div className="w-36">
            <ThemeSwitcher />
          </div>
        </div>
      </SettingsCard>

      <DesktopPreferencesCard desktop={desktop} />

      {desktop ? (
        <section className="overflow-hidden rounded-lg border border-line bg-raised shadow-xs [&>section]:border-b-0">
          <UpdatePanel desktop={desktop} />
        </section>
      ) : null}
    </div>
  );
}

function DesktopPreferencesCard({ desktop }: { desktop: DesktopPlatform | null }) {
  const supported = hasDesktopPreferences();
  const [preferences, setPreferences] = useState<DesktopPreferences | null>(null);
  const [saving, setSaving] = useState<keyof DesktopPreferences | null>(null);
  const [status, setStatus] = useState<"saved" | "failed" | "loginItemFailed" | null>(null);

  useEffect(() => {
    if (!supported) return;
    let active = true;
    void getDesktopPreferences().then((value) => active && setPreferences(value));
    return () => {
      active = false;
    };
  }, [supported]);

  if (!supported) {
    return desktop ? null : (
      <Callout icon={<AppWindow />} tone="neutral">
        {t("prefs.desktop.browserOnly")}
      </Callout>
    );
  }

  async function change(key: keyof DesktopPreferences, value: boolean) {
    setSaving(key);
    setStatus(null);
    setPreferences((current) => (current ? { ...current, [key]: value } : current));
    try {
      const next = await setDesktopPreferences({ [key]: value });
      if (next) setPreferences(next);
      setStatus("saved");
    } catch (caught) {
      setPreferences((current) => (current ? { ...current, [key]: !value } : current));
      setStatus(isLaunchAtLoginError(caught) ? "loginItemFailed" : "failed");
    } finally {
      setSaving(null);
    }
  }

  const rows: Array<{ body: string; key: keyof DesktopPreferences; label: string }> = [
    { body: t("prefs.launchAtLogin.body"), key: "launchAtLogin", label: t("prefs.launchAtLogin.label") },
    { body: t("prefs.background.body"), key: "keepRunningInBackground", label: t("prefs.background.label") },
    { body: t("prefs.autoUpdate.body"), key: "autoDownloadUpdates", label: t("prefs.autoUpdate.label") },
  ];

  return (
    <SettingsCard
      description={t("prefs.desktop.body")}
      footer={
        <p aria-live="polite" className="min-h-5 text-xs text-ink-muted" role="status">
          {status === "saved" ? t("prefs.saved") : null}
          {status === "failed" ? t("prefs.failed") : null}
          {status === "loginItemFailed" ? t("prefs.launchAtLogin.failed") : null}
        </p>
      }
      icon={<AppWindow />}
      title={t("prefs.desktop.title")}
    >
      {rows.map((row) => (
        <ToggleRow
          checked={preferences?.[row.key] ?? false}
          description={row.body}
          disabled={!preferences || saving === row.key}
          key={row.key}
          label={row.label}
          onChange={(value) => void change(row.key, value)}
        />
      ))}
    </SettingsCard>
  );
}
