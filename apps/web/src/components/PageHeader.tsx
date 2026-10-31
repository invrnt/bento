import type { ReactNode } from "react";

import { cx } from "../lib/cx";

export type PageHeaderProps = {
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  description?: ReactNode;
  eyebrow?: ReactNode;
  title: ReactNode;
  titleId?: string;
};

/** One header per page: title, optional context line, primary actions and an optional toolbar row. */
export function PageHeader({ actions, children, className, description, eyebrow, title, titleId }: PageHeaderProps) {
  return (
    <header className={cx("grid gap-4", className)}>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          {eyebrow ? <div className="mb-1 text-sm font-medium text-ink-muted">{eyebrow}</div> : null}
          <h1 className="truncate text-2xl font-semibold tracking-tighter text-ink" id={titleId}>
            {title}
          </h1>
          {description ? <div className="mt-1 max-w-2xl text-base text-ink-muted">{description}</div> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </header>
  );
}
