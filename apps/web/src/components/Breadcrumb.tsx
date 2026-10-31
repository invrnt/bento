import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { cx } from "../lib/cx";

export type BreadcrumbItem = {
  current?: boolean;
  href?: string;
  icon?: ReactNode;
  label: string;
  onNavigate?: (href: string) => void;
};

export type BreadcrumbProps = {
  className?: string;
  items: BreadcrumbItem[];
  label: string;
};

export function Breadcrumb({ className, items, label }: BreadcrumbProps) {
  return (
    <nav aria-label={label} className={cx("min-w-0", className)}>
      <ol className="flex min-w-0 flex-wrap items-center gap-0.5 text-base text-ink-muted">
        {items.map((item, index) => (
          <li className="flex min-w-0 items-center gap-0.5" key={`${item.label}-${index}`}>
            {index > 0 ? <ChevronRight aria-hidden="true" className="size-3.5 shrink-0 text-ink-subtle" /> : null}
            {item.href && !item.current ? (
              <a
                className="focus-ring inline-flex h-7 min-w-0 items-center gap-1.5 rounded-xs px-1.5 transition-colors duration-150 hover:bg-hover hover:text-ink [&_svg]:size-3.5 [&_svg]:shrink-0"
                href={item.href}
                onClick={(event) => {
                  const href = item.href;

                  if (!item.onNavigate || !href) {
                    return;
                  }

                  event.preventDefault();
                  item.onNavigate(href);
                }}
              >
                {item.icon}
                <span className="truncate">{item.label}</span>
              </a>
            ) : (
              <span
                aria-current={item.current ? "page" : undefined}
                className={cx(
                  "inline-flex h-7 min-w-0 items-center gap-1.5 px-1.5 [&_svg]:size-3.5 [&_svg]:shrink-0",
                  item.current ? "font-medium text-ink" : undefined,
                )}
              >
                {item.icon}
                <span className="truncate">{item.label}</span>
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
