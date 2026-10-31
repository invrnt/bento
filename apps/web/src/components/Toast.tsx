import { useEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { CircleAlert, CircleCheck, Info, X } from "lucide-react";

import { t } from "../i18n/dictionary";
import { cx } from "../lib/cx";
import { Button } from "./Button";
import { IconButton } from "./IconButton";
import { Kbd } from "./Kbd";

export type ToastTone = "neutral" | "success" | "danger";

export type ToastAction = {
  label: string;
  onAction: () => unknown;
  /** Marks the action as an undo: it also runs with Ctrl/⌘ Z while the toast is visible. */
  undo?: boolean;
};

export type ToastOptions = {
  action?: ToastAction;
  /** Milliseconds before the toast leaves on its own; `0` keeps it until dismissed. */
  durationMs?: number;
  icon?: ReactNode;
  message: string;
  tone?: ToastTone;
};

export type Toast = ToastOptions & { id: string };

const maxVisible = 3;
const listeners = new Set<() => void>();
let toasts: Toast[] = [];
let sequence = 0;

function emit(next: Toast[]) {
  toasts = next;
  for (const listener of listeners) {
    listener();
  }
}

/** Shows a short, non-blocking message. Returns its id. */
export function showToast(options: ToastOptions): string {
  sequence += 1;
  const id = `toast-${sequence}`;
  emit([...toasts, { ...options, id }].slice(-maxVisible));
  return id;
}

export function dismissToast(id: string): void {
  if (toasts.some((toast) => toast.id === id)) {
    emit(toasts.filter((toast) => toast.id !== id));
  }
}

export function clearToasts(): void {
  emit([]);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot() {
  return toasts;
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

function runAction(toast: Toast) {
  dismissToast(toast.id);
  void toast.action?.onAction();
}

const toneIcons: Record<ToastTone, ReactNode> = {
  danger: <CircleAlert />,
  neutral: <Info />,
  success: <CircleCheck />,
};

const toneClasses: Record<ToastTone, string> = {
  danger: "text-danger-ink",
  neutral: "text-ink-muted",
  success: "text-success-ink",
};

/** Renders every toast in a fixed region. Mounted once by `AppShell`. */
export function ToastViewport() {
  const items = useToasts();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.shiftKey || event.altKey || event.key.toLowerCase() !== "z") {
        return;
      }
      if (isEditableTarget(event.target)) {
        return;
      }

      const latest = [...toasts].reverse().find((toast) => toast.action?.undo);
      if (latest) {
        event.preventDefault();
        runAction(latest);
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return createPortal(
    <section
      aria-label={t("toast.regionLabel")}
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-3 sm:p-5 md:left-60 md:items-start md:px-7"
    >
      {items.map((toast) => (
        <ToastCard key={toast.id} toast={toast} />
      ))}
    </section>,
    document.body,
  );
}

function ToastCard({ toast }: { toast: Toast }) {
  const [paused, setPaused] = useState(false);
  const tone = toast.tone ?? "neutral";
  const duration = toast.durationMs ?? (toast.action ? 8000 : 5000);
  const shortcut = isApplePlatform() ? t("toast.undoShortcutMac") : t("toast.undoShortcut");

  useEffect(() => {
    if (paused || duration <= 0) {
      return;
    }

    const timer = window.setTimeout(() => dismissToast(toast.id), duration);
    return () => window.clearTimeout(timer);
  }, [duration, paused, toast.id]);

  return (
    <div
      className="pointer-events-auto flex w-full max-w-md animate-slide-up items-center gap-3 rounded-lg border border-line bg-raised py-1.5 pl-3.5 pr-1.5 text-ink shadow-lg sm:w-auto sm:min-w-80"
      onBlur={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      role={tone === "danger" ? "alert" : "status"}
    >
      <span aria-hidden="true" className={cx("flex shrink-0 [&_svg]:size-[1.125rem]", toneClasses[tone])}>
        {toast.icon ?? toneIcons[tone]}
      </span>
      <p className="min-w-0 flex-1 py-1.5 text-base">{toast.message}</p>
      {toast.action ? (
        <Button
          aria-keyshortcuts={toast.action.undo ? "Control+Z Meta+Z" : undefined}
          className="text-accent-ink hover:text-accent-ink"
          onClick={() => runAction(toast)}
          size="sm"
          variant="ghost"
        >
          {toast.action.label}
          {toast.action.undo ? (
            <span aria-hidden="true" className="hidden sm:contents">
              <Kbd>{shortcut}</Kbd>
            </span>
          ) : null}
        </Button>
      ) : null}
      <IconButton icon={<X />} label={t("toast.dismiss")} onClick={() => dismissToast(toast.id)} size="sm" />
    </div>
  );
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  return target.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
}

function isApplePlatform(): boolean {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
}
