import type { ComponentProps, ReactNode } from "react";

import { cx } from "../lib/cx";
import { Tooltip } from "./Tooltip";
import type { TooltipSide } from "./Tooltip";

export type IconButtonVariant = "ghost" | "secondary" | "overlay";
export type IconButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<IconButtonVariant, string> = {
  ghost: "border-transparent bg-transparent text-ink-muted hover:bg-hover hover:text-ink active:bg-pressed",
  overlay:
    "border-white/10 bg-black/35 text-white backdrop-blur-md hover:bg-white/15 active:bg-white/25 disabled:bg-black/20",
  secondary: "border-line bg-raised text-ink shadow-xs hover:border-line-strong hover:bg-subtle active:bg-sunken",
};

const sizeClasses: Record<IconButtonSize, string> = {
  lg: "size-10 rounded-md [&_svg]:size-5",
  md: "size-8 rounded-sm [&_svg]:size-4",
  sm: "size-7 rounded-xs [&_svg]:size-3.5",
};

export type IconButtonProps = Omit<ComponentProps<"button">, "children"> & {
  icon: ReactNode;
  label: string;
  size?: IconButtonSize;
  tooltipSide?: TooltipSide;
  variant?: IconButtonVariant;
};

export function IconButton({
  className,
  icon,
  label,
  size = "md",
  tooltipSide = "top",
  type = "button",
  variant = "ghost",
  ...props
}: IconButtonProps) {
  return (
    <Tooltip label={label} side={tooltipSide}>
      <button
        aria-label={label}
        className={cx(
          "focus-ring inline-flex shrink-0 items-center justify-center border transition-[background-color,border-color,color] duration-150 disabled:pointer-events-none disabled:opacity-40 [&_svg]:shrink-0",
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        type={type}
        {...props}
      >
        <span aria-hidden="true" className="contents">
          {icon}
        </span>
      </button>
    </Tooltip>
  );
}
