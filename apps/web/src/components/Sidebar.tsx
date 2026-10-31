import type { ComponentType, ReactNode } from "react";

import { t } from "../i18n/dictionary";
import { cx } from "../lib/cx";
import { BrandLogo } from "./BrandMark";

export type SidebarIcon = ComponentType<{ "aria-hidden"?: boolean; className?: string; strokeWidth?: number }>;

export type SidebarItem = {
  group?: string;
  href: string;
  icon?: SidebarIcon;
  label: string;
};

export type SidebarProps = {
  activePath: string;
  className?: string;
  footer?: ReactNode;
  homeHref?: string;
  id?: string;
  items: SidebarItem[];
  onNavigate: (href: string) => void;
};

export function Sidebar({ activePath, className, footer, homeHref = "/photos", id, items, onNavigate }: SidebarProps) {
  const groups = groupItems(items);

  return (
    <aside className={cx("w-60 shrink-0 flex-col gap-6 px-3 pb-3 pt-4", className)} id={id}>
      <a
        className="focus-ring mx-1.5 inline-flex h-9 w-fit items-center rounded-sm"
        href={homeHref}
        onClick={(event) => {
          event.preventDefault();
          onNavigate(homeHref);
        }}
      >
        <BrandLogo label={t("app.brand")} />
      </a>
      <nav aria-label={t("nav.label")} className="-mx-1 flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-1">
        {groups.map((group) => (
          <div className="grid gap-0.5" key={group.label ?? "default"}>
            {group.label ? <p className="mb-1 px-2.5 text-xs font-medium text-ink-subtle">{group.label}</p> : null}
            {group.items.map((item) => {
              const active = activePath === item.href || activePath.startsWith(`${item.href}/`);
              const Icon = item.icon;

              return (
                <a
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "focus-ring group/nav flex h-9 items-center gap-3 rounded-md px-2.5 text-base font-medium transition-[background-color,color,box-shadow] duration-150",
                    active
                      ? "bg-raised text-ink shadow-sm ring-1 ring-line"
                      : "text-ink-muted hover:bg-hover hover:text-ink",
                  )}
                  href={item.href}
                  key={item.href}
                  onClick={(event) => {
                    event.preventDefault();
                    onNavigate(item.href);
                  }}
                >
                  {Icon ? (
                    <Icon
                      aria-hidden
                      className={cx("size-[1.125rem] shrink-0 transition-colors", active ? "text-accent-ink" : "text-ink-subtle group-hover/nav:text-ink-muted")}
                      strokeWidth={1.75}
                    />
                  ) : null}
                  <span className="truncate">{item.label}</span>
                </a>
              );
            })}
          </div>
        ))}
      </nav>
      {footer ? <div className="grid gap-3 px-1">{footer}</div> : null}
    </aside>
  );
}

function groupItems(items: SidebarItem[]): Array<{ items: SidebarItem[]; label?: string }> {
  const groups: Array<{ items: SidebarItem[]; label?: string }> = [];

  for (const item of items) {
    const current = groups.find((group) => group.label === item.group);
    if (current) {
      current.items.push(item);
    } else {
      groups.push({ items: [item], label: item.group });
    }
  }

  return groups;
}
