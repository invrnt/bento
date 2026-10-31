import type { ComponentProps, ReactNode } from "react";
import { useId } from "react";
import { Check, Minus } from "lucide-react";

import { cx } from "../lib/cx";

export type CheckboxProps = Omit<ComponentProps<"input">, "type"> & {
  description?: ReactNode;
  hideLabel?: boolean;
  label: string;
};

export function Checkbox({ className, description, hideLabel = false, id, label, ...props }: CheckboxProps) {
  const generatedId = useId();
  const checkboxId = id ?? generatedId;

  return (
    <label
      className={cx("group/checkbox inline-flex min-h-8 cursor-pointer select-none items-start gap-2.5 text-base text-ink", className)}
      htmlFor={checkboxId}
    >
      <CheckboxBox boxClassName="mt-2" id={checkboxId} {...props} />
      <span className={cx("grid min-w-0 gap-0.5 pt-[0.4375rem] leading-tight", hideLabel && "sr-only")}>
        <span className="font-medium">{label}</span>
        {description ? <span className="text-sm text-ink-muted">{description}</span> : null}
      </span>
    </label>
  );
}

export type CheckboxBoxProps = Omit<ComponentProps<"input">, "type"> & {
  boxClassName?: string;
};

/** The bare styled box, for places where the label is provided by aria-label. */
export function CheckboxBox({ boxClassName, className, ...props }: CheckboxBoxProps) {
  return (
    <span className={cx("relative inline-flex size-4 shrink-0", boxClassName)}>
      <input
        className={cx(
          "peer focus-ring size-4 cursor-pointer appearance-none rounded-[5px] border border-line-strong bg-raised shadow-xs transition-colors duration-100",
          "checked:border-accent checked:bg-accent indeterminate:border-accent indeterminate:bg-accent hover:border-ink-subtle disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        type="checkbox"
        {...props}
      />
      <Check
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 m-auto size-3 text-on-accent opacity-0 peer-checked:opacity-100 peer-indeterminate:opacity-0"
        strokeWidth={3}
      />
      <Minus
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 m-auto size-3 text-on-accent opacity-0 peer-indeterminate:opacity-100"
        strokeWidth={3}
      />
    </span>
  );
}
