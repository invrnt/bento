import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "../lib/cx";

export type CardProps = HTMLAttributes<HTMLElement> & {
  as?: "div" | "section" | "article" | "aside" | "li";
  children: ReactNode;
  padding?: "none" | "sm" | "md" | "lg";
  tone?: "raised" | "muted";
};

const paddingClasses = {
  lg: "p-6",
  md: "p-5",
  none: "",
  sm: "p-4",
};

/** A compartment inside the page. Never nest one Card inside another. */
export function Card({ as: Element = "div", children, className, padding = "md", tone = "raised", ...props }: CardProps) {
  return (
    <Element
      className={cx(
        "rounded-lg border border-line",
        tone === "raised" ? "bg-raised shadow-xs" : "bg-subtle",
        paddingClasses[padding],
        className,
      )}
      {...props}
    >
      {children}
    </Element>
  );
}
