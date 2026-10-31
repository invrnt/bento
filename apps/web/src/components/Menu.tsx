import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";

import { cx } from "../lib/cx";

export type MenuItem = {
  disabled?: boolean;
  icon?: ReactNode;
  id: string;
  label: string;
  onSelect: () => void;
  separatorBefore?: boolean;
  tone?: "default" | "danger";
};

export type MenuProps = {
  align?: "start" | "end";
  items: MenuItem[];
  label: string;
  trigger: ReactNode;
  triggerClassName?: string;
  triggerVariant?: "secondary" | "ghost";
};

const triggerVariants = {
  ghost: "border-transparent bg-transparent text-ink-muted hover:bg-hover hover:text-ink aria-expanded:bg-pressed aria-expanded:text-ink",
  secondary: "border-line bg-raised px-2.5 text-ink shadow-xs hover:bg-subtle aria-expanded:bg-subtle",
};

const itemSelector = 'button[role="menuitem"]:not(:disabled)';

export function Menu({ align = "end", items, label, trigger, triggerClassName, triggerVariant = "secondary" }: MenuProps) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<CSSProperties>({});
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const closeMenu = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) {
      return;
    }

    const rect = triggerRef.current.getBoundingClientRect();
    const estimatedHeight = items.length * 36 + 12;
    const openUp = window.innerHeight - rect.bottom < estimatedHeight + 12 && rect.top > estimatedHeight + 12;
    setPosition({
      ...(openUp ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }),
      ...(align === "end" ? { right: Math.max(8, window.innerWidth - rect.right) } : { left: Math.max(8, rect.left) }),
    });
  }, [align, items.length, open]);

  useEffect(() => {
    if (!open) {
      return;
    }

    menuRef.current?.querySelector<HTMLButtonElement>(itemSelector)?.focus();

    function onDocumentPointer(event: MouseEvent) {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) {
        setOpen(false);
      }
    }

    function onDocumentKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu();
      }
    }

    function onViewportChange(event: Event) {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", onDocumentPointer);
    document.addEventListener("keydown", onDocumentKeyDown);
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);

    return () => {
      document.removeEventListener("mousedown", onDocumentPointer);
      document.removeEventListener("keydown", onDocumentKeyDown);
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [closeMenu, open]);

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const elements = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>(itemSelector) ?? []);
    const index = elements.indexOf(document.activeElement as HTMLButtonElement);
    const targets: Record<string, number> = {
      ArrowDown: (index + 1) % elements.length,
      ArrowUp: (index - 1 + elements.length) % elements.length,
      End: elements.length - 1,
      Home: 0,
    };

    if (event.key in targets && elements.length > 0) {
      event.preventDefault();
      elements[targets[event.key]]?.focus();
    } else if (event.key === "Tab") {
      event.preventDefault();
      closeMenu();
    }
  }

  return (
    <div className="relative inline-flex">
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={label}
        className={cx(
          "focus-ring inline-flex h-8 min-w-8 items-center justify-center gap-1.5 rounded-sm border text-base font-medium transition-colors duration-150 [&_svg]:size-4",
          triggerVariants[triggerVariant],
          triggerClassName,
        )}
        onClick={() => setOpen((current) => !current)}
        ref={triggerRef}
        type="button"
      >
        {trigger}
      </button>
      {open
        ? createPortal(
            <div
              aria-label={label}
              className="fixed z-50 min-w-52 max-w-72 origin-top animate-pop-in rounded-lg border border-line bg-raised p-1.5 text-ink shadow-lg"
              onKeyDown={onMenuKeyDown}
              ref={menuRef}
              role="menu"
              style={position}
            >
              {items.map((item, index) => (
                <Fragment key={item.id}>
                  {item.separatorBefore && index > 0 ? <div className="-mx-1.5 my-1.5 h-px bg-line" role="separator" /> : null}
                  <button
                    className={cx(
                      "flex h-9 w-full items-center gap-2.5 rounded-sm px-2.5 text-left text-base outline-none transition-colors duration-100 disabled:pointer-events-none disabled:opacity-45 [&_svg]:size-4 [&_svg]:shrink-0",
                      item.tone === "danger"
                        ? "text-danger-ink hover:bg-danger-soft focus-visible:bg-danger-soft"
                        : "hover:bg-hover focus-visible:bg-hover [&_svg]:text-ink-muted",
                    )}
                    disabled={item.disabled}
                    onClick={() => {
                      item.onSelect();
                      closeMenu();
                    }}
                    role="menuitem"
                    tabIndex={-1}
                    type="button"
                  >
                    {item.icon ? <span aria-hidden="true" className="contents">{item.icon}</span> : null}
                    <span className="truncate">{item.label}</span>
                  </button>
                </Fragment>
              ))}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
