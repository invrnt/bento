import type { ReactNode } from "react";

import { cx } from "../lib/cx";

export type KbdProps = {
  children: ReactNode;
  className?: string;
};

export function Kbd({ children, className }: KbdProps) {
  return (
    <kbd
      className={cx(
        "inline-flex h-5 min-w-5 select-none items-center justify-center rounded-xs border border-line bg-subtle px-1.5 font-mono text-2xs font-medium text-ink-muted shadow-xs",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
