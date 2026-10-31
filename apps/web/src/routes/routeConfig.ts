import { Activity, FileText, FolderClosed, Heart, Images, Settings2, SquareLibrary } from "lucide-react";

import { t } from "../i18n/dictionary";
import type { MessageKey } from "../i18n/dictionary";
import type { SidebarItem } from "../components/Sidebar";

export type RouteDefinition = {
  bodyKey: MessageKey;
  pattern: RegExp;
  titleKey: MessageKey;
};

export const navItems: SidebarItem[] = [
  { group: t("nav.group.library"), href: "/photos", icon: Images, label: t("nav.photos") },
  { group: t("nav.group.library"), href: "/albums", icon: SquareLibrary, label: t("nav.albums") },
  { group: t("nav.group.library"), href: "/favorites", icon: Heart, label: t("nav.favorites") },
  { group: t("nav.group.files"), href: "/drive", icon: FolderClosed, label: t("nav.drive") },
  { group: t("nav.group.files"), href: "/documents", icon: FileText, label: t("nav.documents") },
  { group: t("nav.group.system"), href: "/jobs", icon: Activity, label: t("nav.jobs") },
  { group: t("nav.group.system"), href: "/settings", icon: Settings2, label: t("nav.settings") },
];

export const routeDefinitions: RouteDefinition[] = [
  { bodyKey: "route.search.body", pattern: /^\/search\/?$/, titleKey: "route.search.title" },
  { bodyKey: "route.photos.body", pattern: /^\/photos\/?$/, titleKey: "route.photos.title" },
  { bodyKey: "route.photoDetail.body", pattern: /^\/photos\/[^/]+\/?$/, titleKey: "route.photoDetail.title" },
  { bodyKey: "route.albums.body", pattern: /^\/albums\/?$/, titleKey: "route.albums.title" },
  { bodyKey: "route.albumDetail.body", pattern: /^\/albums\/[^/]+\/?$/, titleKey: "route.albumDetail.title" },
  { bodyKey: "route.favorites.body", pattern: /^\/favorites\/?$/, titleKey: "route.favorites.title" },
  { bodyKey: "route.drive.body", pattern: /^\/drive\/?$/, titleKey: "route.drive.title" },
  {
    bodyKey: "route.driveFolder.body",
    pattern: /^\/drive\/folders\/[^/]+\/?$/,
    titleKey: "route.driveFolder.title",
  },
  { bodyKey: "route.documents.body", pattern: /^\/documents\/?$/, titleKey: "route.documents.title" },
  { bodyKey: "route.jobs.body", pattern: /^\/jobs\/?$/, titleKey: "route.jobs.title" },
  { bodyKey: "route.settings.body", pattern: /^\/settings(?:\/[a-z-]+)?\/?$/, titleKey: "route.settings.title" },
  { bodyKey: "route.join.body", pattern: /^\/join\/?$/, titleKey: "route.join.title" },
];

export function resolveRoute(pathname: string): RouteDefinition {
  return (
    routeDefinitions.find((route) => route.pattern.test(pathname)) ?? {
      bodyKey: "route.notFound.body",
      pattern: /.*/,
      titleKey: "route.notFound.title",
    }
  );
}
