import { Cloud, HardDriveUpload, Info, MonitorSmartphone, Settings2, SlidersHorizontal, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { MessageKey } from "../../i18n/dictionary";

export type SettingsSection = "general" | "account" | "devices" | "backup" | "smart-search" | "advanced" | "about";

export const settingsSections: Array<{ icon: LucideIcon; id: SettingsSection; label: MessageKey }> = [
  { icon: Settings2, id: "general", label: "settingsNav.general" },
  { icon: Cloud, id: "account", label: "settingsNav.account" },
  { icon: MonitorSmartphone, id: "devices", label: "settingsNav.devices" },
  { icon: HardDriveUpload, id: "backup", label: "settingsNav.backup" },
  { icon: Sparkles, id: "smart-search", label: "settingsNav.smartSearch" },
  { icon: SlidersHorizontal, id: "advanced", label: "settingsNav.advanced" },
  { icon: Info, id: "about", label: "settingsNav.about" },
];

export type SettingsLocation = { focus: "recovery" | null; section: SettingsSection };

/**
 * `/settings` → General, `/settings/<section>`, and `/settings/recovery`
 * (Cuenta y nube with the recovery kit focused; the "Guardar kit" action and desktop "recovery-kit" target).
 */
export function settingsLocation(pathname: string): SettingsLocation {
  const segment = pathname.replace(/\/+$/, "").split("/")[2] ?? "";
  if (segment === "recovery") return { focus: "recovery", section: "account" };
  const match = settingsSections.find((section) => section.id === segment);
  return { focus: null, section: match?.id ?? "general" };
}

export function settingsPath(section: SettingsSection): string {
  return section === "general" ? "/settings" : `/settings/${section}`;
}
