import { useId } from "react";
import type { ReactElement } from "react";

import { cx } from "../lib/cx";

export type TooltipSide = "top" | "bottom" | "left" | "right";

export type TooltipProps = {
  children: ReactElement;
  className?: string;
  label: string;
  side?: TooltipSide;
};

const sideClasses: Record<TooltipSide, string> = {
  bottom: "left-1/2 top-[calc(100%+8px)] -translate-x-1/2",
  left: "right-[calc(100%+8px)] top-1/2 -translate-y-1/2",
  right: "left-[calc(100%+8px)] top-1/2 -translate-y-1/2",
  top: "bottom-[calc(100%+8px)] left-1/2 -translate-x-1/2",
};

export function Tooltip({ children, className, label, side = "top" }: TooltipProps) {
  const id = useId();

  return (
    <span className={cx("group/tooltip relative inline-flex", className)}>
      {children}
      <span
        className={cx(
          "pointer-events-none absolute z-50 w-max max-w-60 rounded-sm bg-tooltip px-2 py-1 text-xs font-medium text-ink-inverse opacity-0 shadow-md transition-opacity duration-150",
          "group-hover/tooltip:opacity-100 group-hover/tooltip:delay-300 group-has-[:focus-visible]/tooltip:opacity-100",
          sideClasses[side],
        )}
        id={id}
        role="tooltip"
      >
        {label}
      </span>
    </span>
  );
}
