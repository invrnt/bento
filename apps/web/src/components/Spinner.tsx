import { cx } from "../lib/cx";

export type SpinnerProps = {
  className?: string;
};

export function Spinner({ className }: SpinnerProps) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent opacity-70 motion-reduce:animate-none",
        className,
      )}
    />
  );
}
