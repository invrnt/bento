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

function nameKey(name: string): string {
  return name.trim().toLocaleLowerCase();
}

/**
 * Tells whether a name is shared by several devices (two "laptop · Linux"), so their rows can
 * also show when each one was added. Devices are counted once per id.
 */
export function sharedNames(devices: ReadonlyArray<{ id: string; name: string }>): (name: string) => boolean {
  const byId = new Map<string, string>();
  for (const device of devices) byId.set(device.id, nameKey(device.name));
  const counts = new Map<string, number>();
  for (const key of byId.values()) counts.set(key, (counts.get(key) ?? 0) + 1);
  return (name) => (counts.get(nameKey(name)) ?? 0) > 1;
}
