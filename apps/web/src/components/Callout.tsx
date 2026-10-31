import type { AriaRole, ReactNode } from "react";
import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";

import { cx } from "../lib/cx";

export type CalloutTone = "neutral" | "info" | "success" | "warning" | "danger";

const toneClasses: Record<CalloutTone, string> = {
  danger: "border-danger/25 bg-danger-soft [&_[data-callout-icon]]:text-danger-ink",
  info: "border-accent/20 bg-accent-soft [&_[data-callout-icon]]:text-accent-ink",
  neutral: "border-line bg-subtle [&_[data-callout-icon]]:text-ink-muted",
  success: "border-success/25 bg-success-soft [&_[data-callout-icon]]:text-success-ink",
  warning: "border-warning/35 bg-warning-soft [&_[data-callout-icon]]:text-warning-ink",
};

const toneIcons: Record<CalloutTone, ReactNode> = {
  danger: <CircleAlert />,
  info: <Info />,
  neutral: <Info />,
  success: <CircleCheck />,
  warning: <TriangleAlert />,
};

export type CalloutProps = {
  action?: ReactNode;
  children?: ReactNode;
  className?: string;
  icon?: ReactNode;
  role?: AriaRole;
  title?: ReactNode;
  tone?: CalloutTone;
};

/** Inline, non-blocking message. Pass `role` explicitly when it must be announced. */
export function Callout({ action, children, className, icon, role, title, tone = "neutral" }: CalloutProps) {
  return (
    <div
      className={cx(
        "flex flex-col gap-3 rounded-lg border p-3.5 text-base sm:flex-row sm:items-center sm:justify-between",
        toneClasses[tone],
        className,
      )}
      role={role}
    >
      <div className="flex min-w-0 gap-3">
        <span aria-hidden="true" className="mt-0.5 flex shrink-0 [&_svg]:size-[1.125rem]" data-callout-icon>
          {icon ?? toneIcons[tone]}
        </span>
        <div className="min-w-0">
          {title ? <p className="font-semibold text-ink">{title}</p> : null}
          {children ? <div className={cx("text-ink-muted", title ? "mt-0.5" : undefined)}>{children}</div> : null}
        </div>
      </div>
      {action ? <div className="flex shrink-0 flex-wrap gap-2 self-start sm:self-center">{action}</div> : null}
    </div>
  );
}
