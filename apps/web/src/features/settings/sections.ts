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
 * `/settings` → General, `/settings/<section>` or `/settings?section=<section>`; `recovery`
 * (path or `?section=recovery`, used by Actividad and desktop notifications) opens
 * Cuenta y nube with the recovery kit focused.
 */
export function settingsLocation(pathname: string, search = ""): SettingsLocation {
  const segment = pathname.replace(/\/+$/, "").split("/")[2] || new URLSearchParams(search).get("section") || "";
  if (segment === "recovery") return { focus: "recovery", section: "account" };
  const match = settingsSections.find((section) => section.id === segment);
  return { focus: null, section: match?.id ?? "general" };
}

export function settingsPath(section: SettingsSection): string {
  return section === "general" ? "/settings" : `/settings/${section}`;
}
