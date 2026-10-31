import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

import { BrandLogo } from "../../components/BrandMark";
import { t } from "../../i18n/dictionary";
import { cx } from "../../lib/cx";
import { tf } from "./format";

export type SetupFrameProps = {
  /** Small print under the card (legal, privacy). */
  aside?: ReactNode;
  children?: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  footer?: ReactNode;
  /** Visual above the title (icon tile or the brand mark). */
  hero?: ReactNode;
  /** Hide the logo when the hero already shows the brand mark (one ume per screen). */
  showLogo?: boolean;
  /** Changing it moves focus to the new title so screen readers announce the step. */
  stepKey: string;
  steps?: { current: number; total: number };
  title: ReactNode;
  width?: "md" | "lg";
};

/** Full-window tray with one hero compartment: the shared frame for first run and joining. */
export function SetupFrame({
  aside,
  children,
  description,
  eyebrow,
  footer,
  hero,
  showLogo = true,
  stepKey,
  steps,
  title,
  width = "lg",
}: SetupFrameProps) {
  const titleId = useId();
  const titleRef = useRef<HTMLHeadingElement | null>(null);
  const mainRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    // Each step replaces the card: move focus to its title (screen readers announce the step)
    // unless a field inside it already took focus with autoFocus.
    if (!mainRef.current?.contains(document.activeElement)) titleRef.current?.focus({ preventScroll: true });
  }, [stepKey]);

  return (
    <div className="min-h-dvh overflow-y-auto bg-tray text-ink">
      <div className="flex min-h-dvh flex-col items-center justify-center px-4 py-8 sm:px-6 sm:py-12">
        <main
          aria-labelledby={titleId}
          className={cx(
            "w-full animate-pop-in rounded-2xl border border-line bg-raised shadow-xl",
            width === "md" ? "max-w-lg" : "max-w-2xl",
          )}
          key={stepKey}
          ref={mainRef}
        >
          {showLogo || steps ? (
            <div className="flex items-center justify-between gap-3 px-6 pt-6 sm:px-8 sm:pt-7">
              {showLogo ? <BrandLogo label={t("app.brand")} /> : <span />}
              {steps ? <StepProgress current={steps.current} total={steps.total} /> : null}
            </div>
          ) : null}
          <div className={cx("px-6 pb-6 sm:px-8 sm:pb-8", showLogo || steps ? "pt-7" : "pt-8 sm:pt-10")}>
            {hero ? <div className="mb-5">{hero}</div> : null}
            {eyebrow ? <p className="mb-1.5 text-sm font-medium text-ink-muted">{eyebrow}</p> : null}
            <h1 className="text-2xl font-semibold tracking-tighter text-ink outline-none" id={titleId} ref={titleRef} tabIndex={-1}>
              {title}
            </h1>
            {description ? <div className="mt-2 max-w-xl text-base text-ink-muted">{description}</div> : null}
            {children ? <div className="mt-6">{children}</div> : null}
          </div>
          {footer ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-b-2xl border-t border-line bg-subtle px-6 py-4 sm:px-8">
              {footer}
            </div>
          ) : null}
        </main>
        {aside ? <div className="mt-5 max-w-lg text-center text-xs text-ink-subtle">{aside}</div> : null}
      </div>
    </div>
  );
}

function StepProgress({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-xs font-medium tabular-nums text-ink-muted">{tf("setup.stepOf", { current, total })}</span>
      <ol aria-hidden="true" className="flex items-center gap-1">
        {Array.from({ length: total }, (_, index) => (
          <li
            className={cx(
              "h-1.5 rounded-full transition-[width,background-color] duration-200",
              index + 1 === current ? "w-5 bg-accent" : index + 1 < current ? "w-1.5 bg-accent" : "w-1.5 bg-line-strong",
            )}
            key={index}
          />
        ))}
      </ol>
    </div>
  );
}

/** Square icon tile used as a step hero. */
export function HeroIcon({ children, tone = "accent" }: { children: ReactNode; tone?: "accent" | "success" | "warning" | "danger" }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "grid size-12 place-items-center rounded-lg [&_svg]:size-6",
        tone === "accent" && "bg-accent-soft text-accent-ink",
        tone === "success" && "bg-success-soft text-success-ink",
        tone === "warning" && "bg-warning-soft text-warning-ink",
        tone === "danger" && "bg-danger-soft text-danger-ink",
      )}
    >
      {children}
    </span>
  );
}

export type ChoiceCardProps = {
  body: string;
  disabled?: boolean;
  icon: ReactNode;
  loading?: boolean;
  onClick: () => void;
  title: string;
};

/** A large, keyboard-friendly option button ("Pedir acceso…", "Usar mi kit…"). */
export function ChoiceCard({ body, disabled, icon, loading, onClick, title }: ChoiceCardProps) {
  return (
    <button
      aria-busy={loading || undefined}
      className="focus-ring group flex w-full items-start gap-3.5 rounded-lg border border-line bg-raised p-4 text-left shadow-xs transition-[border-color,box-shadow,background-color] duration-150 hover:border-line-strong hover:shadow-md disabled:pointer-events-none disabled:opacity-50"
      disabled={disabled || loading}
      onClick={onClick}
      type="button"
    >
      <span
        aria-hidden="true"
        className="grid size-10 shrink-0 place-items-center rounded-md bg-accent-soft text-accent-ink transition-colors duration-150 [&_svg]:size-5"
      >
        {icon}
      </span>
      <span className="grid min-w-0 gap-0.5">
        <span className="text-base font-semibold text-ink">{title}</span>
        <span className="text-sm text-ink-muted">{body}</span>
      </span>
    </button>
  );
}
