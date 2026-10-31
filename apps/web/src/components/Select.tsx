import type { ComponentProps } from "react";
import { useId } from "react";
import { ChevronDown } from "lucide-react";

import { cx } from "../lib/cx";

export type SelectOption = {
  label: string;
  value: string;
};

export type SelectProps = ComponentProps<"select"> & {
  hideLabel?: boolean;
  label: string;
  options: SelectOption[];
  wrapperClassName?: string;
};

export function Select({ className, hideLabel = false, id, label, options, wrapperClassName, ...props }: SelectProps) {
  const generatedId = useId();
  const selectId = id ?? generatedId;

  return (
    <div className={cx("grid min-w-0 gap-1.5", wrapperClassName)}>
      <label className={cx("text-sm font-medium text-ink", hideLabel && "sr-only")} htmlFor={selectId}>
        {label}
      </label>
      <div className="relative flex min-w-0 items-center">
        <select className={cx("field appearance-none pl-3 pr-9", className)} id={selectId} {...props}>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-3 size-4 text-ink-subtle" />
      </div>
    </div>
  );
}
