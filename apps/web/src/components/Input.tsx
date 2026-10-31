import type { ComponentProps, ReactNode } from "react";
import { useId } from "react";

import { cx } from "../lib/cx";

export type InputProps = ComponentProps<"input"> & {
  error?: string;
  hideLabel?: boolean;
  hint?: string;
  label: string;
  leadingIcon?: ReactNode;
  trailing?: ReactNode;
  wrapperClassName?: string;
};

export function Input({
  className,
  error,
  hideLabel = false,
  hint,
  id,
  label,
  leadingIcon,
  trailing,
  wrapperClassName,
  ...props
}: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  const describedBy = [props["aria-describedby"], hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cx("grid min-w-0 gap-1.5", wrapperClassName)}>
      <label className={cx("text-sm font-medium text-ink", hideLabel && "sr-only")} htmlFor={inputId}>
        {label}
      </label>
      <div className="relative flex min-w-0 items-center">
        {leadingIcon ? (
          <span aria-hidden="true" className="pointer-events-none absolute left-3 flex text-ink-subtle [&_svg]:size-4">
            {leadingIcon}
          </span>
        ) : null}
        <input
          {...props}
          aria-describedby={describedBy}
          aria-invalid={error ? true : props["aria-invalid"]}
          className={cx("field px-3", leadingIcon ? "pl-9" : undefined, trailing ? "pr-10" : undefined, className)}
          id={inputId}
        />
        {trailing ? <span className="absolute right-1.5 flex items-center">{trailing}</span> : null}
      </div>
      {hint ? (
        <p className="text-xs text-ink-muted" id={hintId}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="text-xs font-medium text-danger-ink" id={errorId} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
