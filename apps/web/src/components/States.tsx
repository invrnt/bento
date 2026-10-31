import type { ReactNode } from "react";
import { RotateCw, TriangleAlert } from "lucide-react";

import { t } from "../i18n/dictionary";
import { cx } from "../lib/cx";
import { BentoLoader } from "./BrandMark";
import { Button } from "./Button";

export type EmptyStateProps = {
  action?: ReactNode;
  body: string;
  className?: string;
  icon?: ReactNode;
  size?: "md" | "sm";
  title: string;
};

export function EmptyState({ action, body, className, icon, size = "md", title }: EmptyStateProps) {
  return (
    <section
      className={cx(
        "grid place-items-center rounded-xl border border-dashed border-line-strong/80 px-6 text-center",
        size === "sm" ? "min-h-44 py-8" : "min-h-72 py-12",
        className,
      )}
    >
      <div className="flex max-w-sm flex-col items-center">
        <span
          aria-hidden="true"
          className="mb-4 grid size-12 place-items-center rounded-lg border border-line bg-raised text-ink-muted shadow-sm [&_svg]:size-5"
        >
          {icon ?? <EmptyCompartments />}
        </span>
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        <p className="mt-1.5 text-base text-ink-muted">{body}</p>
        {action ? <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div> : null}
      </div>
    </section>
  );
}

function EmptyCompartments() {
  return (
    <svg fill="none" stroke="currentColor" strokeDasharray="2.5 2.5" strokeWidth="1.5" viewBox="0 0 24 24">
      <rect height="16" rx="2.5" width="7" x="3" y="4" />
      <rect height="7" rx="2.5" width="9" x="12" y="4" />
      <rect height="7" rx="2.5" width="9" x="12" y="13" />
    </svg>
  );
}

export type LoadingStateProps = {
  className?: string;
  label?: string;
};

export function LoadingState({ className, label = t("common.loading") }: LoadingStateProps) {
  return (
    <div
      aria-live="polite"
      className={cx("flex min-h-40 flex-col items-center justify-center gap-3 py-8 text-sm text-ink-muted", className)}
      role="status"
    >
      <BentoLoader />
      <span className="font-medium">{label}</span>
    </div>
  );
}

export type ErrorStateProps = {
  body: string;
  className?: string;
  onRetry?: () => void;
  title?: string;
};

export function ErrorState({ body, className, onRetry, title = t("common.error") }: ErrorStateProps) {
  return (
    <section
      aria-live="assertive"
      className={cx(
        "flex flex-col gap-4 rounded-lg border border-danger/25 bg-danger-soft p-4 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
      role="alert"
    >
      <div className="flex min-w-0 gap-3">
        <TriangleAlert aria-hidden="true" className="mt-0.5 size-[1.125rem] shrink-0 text-danger-ink" />
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <p className="mt-0.5 break-words text-base text-ink-muted">{body}</p>
        </div>
      </div>
      {onRetry ? (
        <Button className="self-start sm:self-center" leadingIcon={<RotateCw />} onClick={onRetry} size="sm">
          {t("common.retry")}
        </Button>
      ) : null}
    </section>
  );
}
