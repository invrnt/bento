import { cx } from "../lib/cx";

export type BrandMarkProps = {
  className?: string;
  /** Accessible name. Omit when the mark sits next to visible brand text. */
  title?: string;
};

/**
 * The Bento mark: a lacquer box with three compartments and a single shu (umeboshi) dot.
 * Geometry is documented in orchestration/design-system/brand.md.
 */
export function BrandMark({ className, title }: BrandMarkProps) {
  return (
    <svg
      aria-hidden={title ? undefined : true}
      className={cx("size-7 shrink-0", className)}
      role={title ? "img" : undefined}
      viewBox="0 0 32 32"
    >
      {title ? <title>{title}</title> : null}
      <rect className="fill-ink" height="32" rx="9" width="32" />
      <rect className="fill-tray" height="22" rx="3.5" width="10.5" x="4.5" y="5" />
      <rect className="fill-tray" height="10" rx="3.5" width="10.5" x="17" y="5" />
      <rect className="fill-tray" height="10" rx="3.5" width="10.5" x="17" y="17" />
      <circle className="fill-shu" cx="22.25" cy="22" r="2.75" />
    </svg>
  );
}

export type BrandLogoProps = {
  className?: string;
  label: string;
};

export function BrandLogo({ className, label }: BrandLogoProps) {
  return (
    <span className={cx("inline-flex items-center gap-2.5", className)}>
      <BrandMark />
      <span className="text-[1.0625rem] font-semibold tracking-[-0.03em] text-ink">{label}</span>
    </span>
  );
}

export type BentoLoaderProps = {
  className?: string;
};

/** Compartments fill one after another; the ume lands last. */
export function BentoLoader({ className }: BentoLoaderProps) {
  return (
    <svg aria-hidden="true" className={cx("size-8 shrink-0", className)} viewBox="0 0 32 32">
      <rect className="fill-none stroke-line-strong" height="30" rx="8.5" strokeWidth="1.5" width="30" x="1" y="1" />
      <rect className="animate-bento fill-ink-subtle" height="22" rx="3.5" width="10.5" x="4.5" y="5" />
      <rect className="animate-bento fill-ink-subtle [animation-delay:180ms]" height="10" rx="3.5" width="10.5" x="17" y="5" />
      <rect className="animate-bento fill-ink-subtle [animation-delay:360ms]" height="10" rx="3.5" width="10.5" x="17" y="17" />
      <circle className="animate-bento fill-shu [animation-delay:540ms]" cx="22.25" cy="22" r="2.75" />
    </svg>
  );
}
