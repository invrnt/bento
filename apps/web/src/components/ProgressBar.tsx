import { cx } from "../lib/cx";

export type ProgressBarProps = {
  className?: string;
  /** Accessible name; omit to render a decorative bar. */
  label?: string;
  tone?: "accent" | "success" | "danger";
  value: number;
};

const toneClasses = {
  accent: "bg-accent",
  danger: "bg-danger",
  success: "bg-success",
};

export function ProgressBar({ className, label, tone = "accent", value }: ProgressBarProps) {
  const percent = Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0));

  return (
    <div
      aria-hidden={label ? undefined : true}
      aria-label={label}
      aria-valuemax={label ? 100 : undefined}
      aria-valuemin={label ? 0 : undefined}
      aria-valuenow={label ? Math.round(percent) : undefined}
      className={cx("h-1.5 w-full overflow-hidden rounded-full bg-sunken", className)}
      role={label ? "progressbar" : undefined}
    >
      <div
        className={cx("h-full rounded-full transition-[width] duration-300 ease-out motion-reduce:transition-none", toneClasses[tone])}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
