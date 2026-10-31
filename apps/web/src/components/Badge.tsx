import type { ReactNode } from "react";

import { cx } from "../lib/cx";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger" | "shu";

const toneClasses: Record<BadgeTone, string> = {
  accent: "bg-accent-soft text-accent-ink",
  danger: "bg-danger-soft text-danger-ink",
  neutral: "bg-sunken text-ink-muted",
  shu: "bg-shu-soft text-shu-ink",
  success: "bg-success-soft text-success-ink",
  warning: "bg-warning-soft text-warning-ink",
};

const dotClasses: Record<BadgeTone, string> = {
  accent: "bg-accent",
  danger: "bg-danger",
  neutral: "bg-ink-subtle",
  shu: "bg-shu",
  success: "bg-success",
  warning: "bg-warning",
};

export type BadgeProps = {
  children: ReactNode;
  className?: string;
  dot?: boolean;
  icon?: ReactNode;
  pulse?: boolean;
  size?: "sm" | "md";
  tone?: BadgeTone;
};

export function Badge({ children, className, dot = false, icon, pulse = false, size = "sm", tone = "neutral" }: BadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex max-w-full shrink-0 select-none items-center gap-1.5 rounded-full font-medium whitespace-nowrap [&_svg]:size-3 [&_svg]:shrink-0",
        size === "sm" ? "h-5 px-2 text-2xs" : "h-6 px-2.5 text-xs",
        toneClasses[tone],
        className,
      )}
    >
      {dot ? <StatusDot pulse={pulse} tone={tone} /> : icon}
      <span className="truncate">{children}</span>
    </span>
  );
}

export type StatusDotProps = {
  className?: string;
  pulse?: boolean;
  tone?: BadgeTone;
};

export function StatusDot({ className, pulse = false, tone = "neutral" }: StatusDotProps) {
  return (
    <span aria-hidden="true" className={cx("relative inline-flex size-1.5 shrink-0", className)}>
      {pulse ? (
        <span className={cx("absolute inset-0 animate-ping rounded-full opacity-60 motion-reduce:animate-none", dotClasses[tone])} />
      ) : null}
      <span className={cx("relative inline-flex size-full rounded-full", dotClasses[tone])} />
    </span>
  );
}
