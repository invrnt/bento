import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { t } from "../i18n/dictionary";
import { cx } from "../lib/cx";
import { IconButton } from "./IconButton";

const focusableSelector = [
  "a[href]",
  "button:not(:disabled)",
  "input:not(:disabled)",
  "select:not(:disabled)",
  "textarea:not(:disabled)",
  "iframe",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export type DialogSize = "sm" | "md" | "lg" | "xl";

const sizeClasses: Record<DialogSize, string> = {
  lg: "max-w-2xl",
  md: "max-w-lg",
  sm: "max-w-md",
  xl: "max-w-4xl",
};

export type DialogProps = {
  actions?: ReactNode;
  children: ReactNode;
  description?: string;
  icon?: ReactNode;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  size?: DialogSize;
  title: string;
  tone?: "default" | "danger";
};

export function Dialog({
  actions,
  children,
  description,
  icon,
  onOpenChange,
  open,
  size = "md",
  title,
  tone = "default",
}: DialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  // Callers often pass an inline callback; keep the latest one without re-running the focus effect.
  const onOpenChangeRef = useRef(onOpenChange);
  onOpenChangeRef.current = onOpenChange;

  useEffect(() => {
    if (!open) {
      return;
    }

    returnFocusRef.current = document.activeElement as HTMLElement | null;

    const preferred = panelRef.current?.querySelector<HTMLElement>("[data-autofocus]");
    const focusable = getFocusable(panelRef.current);
    (preferred ?? focusable[0] ?? panelRef.current)?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onOpenChangeRef.current(false);
      }

      if (event.key === "Tab") {
        trapFocus(event, panelRef.current);
      }
    }

    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [open]);

  if (!open) {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 grid animate-fade-in place-items-center overflow-y-auto bg-scrim p-4 backdrop-blur-[2px] sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onOpenChange(false);
        }
      }}
      role="presentation"
    >
      <div
        aria-describedby={description ? descriptionId : undefined}
        aria-labelledby={titleId}
        aria-modal="true"
        className={cx(
          "flex max-h-[min(88vh,52rem)] w-full animate-pop-in flex-col overflow-hidden rounded-xl border border-line bg-raised text-ink shadow-xl outline-none",
          sizeClasses[size],
        )}
        ref={panelRef}
        role="dialog"
        tabIndex={-1}
      >
        <div className="flex items-start gap-3 px-5 pb-2 pt-5 sm:px-6 sm:pt-6">
          {icon ? (
            <span
              aria-hidden="true"
              className={cx(
                "grid size-9 shrink-0 place-items-center rounded-md [&_svg]:size-[1.125rem]",
                tone === "danger" ? "bg-danger-soft text-danger-ink" : "bg-accent-soft text-accent-ink",
              )}
            >
              {icon}
            </span>
          ) : null}
          <div className="min-w-0 flex-1 pt-1">
            <h2 className="truncate text-lg font-semibold text-ink" id={titleId}>
              {title}
            </h2>
            {description ? (
              <p className="mt-1 text-base text-ink-muted" id={descriptionId}>
                {description}
              </p>
            ) : null}
          </div>
          <IconButton className="-mr-1.5 -mt-0.5" icon={<X />} label={t("common.close")} onClick={() => onOpenChange(false)} />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 pt-2 text-base text-ink-muted sm:px-6 sm:pb-6">{children}</div>
        {actions ? (
          <div className="flex flex-wrap justify-end gap-2 border-t border-line bg-subtle px-5 py-3.5 sm:px-6">{actions}</div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}

function getFocusable(root: HTMLElement | null): HTMLElement[] {
  if (!root) {
    return [];
  }

  return Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    (element) => !element.hasAttribute("disabled") && element.tabIndex !== -1,
  );
}

function trapFocus(event: KeyboardEvent, root: HTMLElement | null) {
  const focusable = getFocusable(root);

  if (focusable.length === 0) {
    event.preventDefault();
    root?.focus();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
