import { t } from "../i18n/dictionary";
import { cx } from "../lib/cx";
import { StatusDot } from "./Badge";
import type { BadgeTone } from "./Badge";
import { Tooltip } from "./Tooltip";

export type StatusTone = "idle" | "success" | "warning" | "danger";

const toneMap: Record<StatusTone, BadgeTone> = {
  danger: "danger",
  idle: "neutral",
  success: "success",
  warning: "warning",
};

export type StatusIndicatorProps = {
  detail?: string;
  href?: string;
  label?: string;
  onNavigate?: (href: string) => void;
  tone?: StatusTone;
};

export function StatusIndicator({
  detail = t("app.status.detail"),
  href,
  label = t("app.status.idle"),
  onNavigate,
  tone = "idle",
}: StatusIndicatorProps) {
  const pillClasses =
    "inline-flex h-8 min-w-8 items-center justify-center gap-2 rounded-full border border-line bg-raised text-sm font-medium text-ink-muted shadow-xs sm:px-3";
  const content = (
    <>
      <StatusDot pulse={tone === "warning" || tone === "danger"} tone={toneMap[tone]} />
      <span className="sr-only truncate sm:not-sr-only">{label}</span>
    </>
  );

  return (
    <aside aria-label={t("shell.statusLabel")} className="flex shrink-0 select-none">
      <Tooltip label={detail} side="bottom">
        {href ? (
          <a
            className={cx(pillClasses, "focus-ring transition-colors duration-150 hover:border-line-strong hover:text-ink")}
            href={href}
            onClick={(event) => {
              if (!onNavigate) {
                return;
              }
              event.preventDefault();
              onNavigate(href);
            }}
          >
            {content}
          </a>
        ) : (
          <span className={pillClasses}>{content}</span>
        )}
      </Tooltip>
    </aside>
  );
}
