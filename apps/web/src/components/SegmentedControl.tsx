import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { cx } from "../lib/cx";
import { Tooltip } from "./Tooltip";

export type SegmentedControlOption<T extends string> = {
  icon?: ReactNode;
  label: string;
  value: T;
};

export type SegmentedControlProps<T extends string> = {
  ariaLabel: string;
  className?: string;
  iconOnly?: boolean;
  onChange: (value: T) => void;
  options: Array<SegmentedControlOption<T>>;
  size?: "sm" | "md";
  /** Spread the segments evenly across the available width. */
  stretch?: boolean;
  value: T;
};

export function SegmentedControl<T extends string>({
  ariaLabel,
  className,
  iconOnly = false,
  onChange,
  options,
  size = "md",
  stretch = false,
  value,
}: SegmentedControlProps<T>) {
  const groupRef = useRef<HTMLDivElement | null>(null);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;

    if (!step) {
      return;
    }

    event.preventDefault();
    const index = options.findIndex((option) => option.value === value);
    const next = options[(index + step + options.length) % options.length];
    onChange(next.value);
    Array.from(groupRef.current?.querySelectorAll<HTMLButtonElement>("[data-value]") ?? [])
      .find((button) => button.dataset.value === next.value)
      ?.focus();
  }

  return (
    <div
      aria-label={ariaLabel}
      className={cx(
        "shrink-0 items-center gap-0.5 rounded-md border border-line bg-sunken p-0.5",
        stretch ? "flex w-full" : "inline-flex",
        size === "sm" ? "h-8" : "h-9",
        className,
      )}
      onKeyDown={onKeyDown}
      ref={groupRef}
      role="radiogroup"
    >
      {options.map((option) => {
        const selected = option.value === value;
        const button = (
          <button
            aria-checked={selected}
            aria-label={iconOnly ? option.label : undefined}
            className={cx(
              "focus-ring inline-flex h-full items-center justify-center gap-1.5 rounded-[calc(var(--radius-md)-3px)] font-medium transition-[background-color,color,box-shadow] duration-150 [&_svg]:size-4 [&_svg]:shrink-0",
              size === "sm" ? "text-sm" : "text-base",
              iconOnly ? (stretch ? "w-full" : "aspect-square") : "px-3",
              stretch && !iconOnly ? "flex-1" : undefined,
              selected ? "bg-raised text-ink shadow-sm" : "text-ink-muted hover:text-ink",
            )}
            data-value={option.value}
            key={option.value}
            onClick={() => onChange(option.value)}
            role="radio"
            tabIndex={selected ? 0 : -1}
            type="button"
          >
            {option.icon ? <span aria-hidden="true" className="contents">{option.icon}</span> : null}
            {iconOnly ? null : <span className="truncate">{option.label}</span>}
          </button>
        );

        return iconOnly ? (
          <Tooltip className={cx("h-full", stretch && "flex-1")} key={option.value} label={option.label}>
            {button}
          </Tooltip>
        ) : (
          button
        );
      })}
    </div>
  );
}
