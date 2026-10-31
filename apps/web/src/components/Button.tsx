import type { ComponentProps, ReactNode } from "react";

import { cx } from "../lib/cx";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-ghost";
export type ButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "border-transparent bg-accent text-on-accent shadow-sheen-accent hover:bg-accent-hover active:translate-y-px",
  secondary:
    "border-line bg-raised text-ink shadow-xs hover:border-line-strong hover:bg-subtle active:bg-sunken",
  ghost: "border-transparent bg-transparent text-ink-muted hover:bg-hover hover:text-ink active:bg-pressed",
  danger: "border-transparent bg-danger text-on-danger shadow-sm hover:bg-danger-hover active:translate-y-px",
  "danger-ghost": "border-transparent bg-transparent text-danger-ink hover:bg-danger-soft active:bg-danger-soft",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-sm px-2.5 text-sm [&_svg]:size-3.5",
  md: "h-9 gap-2 rounded-md px-3.5 text-base [&_svg]:size-4",
  lg: "h-11 gap-2 rounded-md px-5 text-md [&_svg]:size-[1.125rem]",
};

export type ButtonProps = ComponentProps<"button"> & {
  children: ReactNode;
  leadingIcon?: ReactNode;
  loading?: boolean;
  size?: ButtonSize;
  trailingIcon?: ReactNode;
  variant?: ButtonVariant;
};

export function Button({
  children,
  className,
  disabled,
  leadingIcon,
  loading = false,
  size = "md",
  trailingIcon,
  type = "button",
  variant = "secondary",
  ...props
}: ButtonProps) {
  return (
    <button
      aria-busy={loading || undefined}
      className={cx(
        "focus-ring inline-flex max-w-full shrink-0 select-none items-center justify-center border font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow,transform] duration-150 ease-out disabled:pointer-events-none disabled:opacity-45 [&_svg]:shrink-0",
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      disabled={disabled || loading}
      type={type}
      {...props}
    >
      {loading ? <Spinner /> : leadingIcon}
      {typeof children === "string" ? (
        <span className="min-w-0 truncate">{children}</span>
      ) : (
        <span className="inline-flex min-w-0 items-center gap-[inherit]">{children}</span>
      )}
      {trailingIcon}
    </button>
  );
}
