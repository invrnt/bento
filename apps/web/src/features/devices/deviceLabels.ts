import { Computer, Laptop, Monitor, MonitorSmartphone } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { t } from "../../i18n/dictionary";
import type { MessageKey } from "../../i18n/dictionary";

const platformKeys: Record<string, MessageKey> = {
  linux: "devices.platform.linux",
  macos: "devices.platform.macos",
  windows: "devices.platform.windows",
};

const platformIcons: Record<string, LucideIcon> = {
  linux: Computer,
  macos: Laptop,
  windows: Monitor,
};

export function platformLabel(platform: string | null | undefined): string {
  const key = platformKeys[(platform ?? "").toLowerCase()];
  return key ? t(key) : t("devices.platform.other");
}

export function platformIcon(platform: string | null | undefined): LucideIcon {
  return platformIcons[(platform ?? "").toLowerCase()] ?? MonitorSmartphone;
}

/** "Portátil de Ana · Linux": appends the platform unless the name already ends with it. */
export function deviceDisplayName(name: string, platform: string | null | undefined): string {
  const label = platformLabel(platform);
  const trimmed = name.trim();
  if (!trimmed) return label;
  return trimmed.toLocaleLowerCase().endsWith(label.toLocaleLowerCase()) ? trimmed : `${trimmed} · ${label}`;
}
