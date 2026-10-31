import { useId, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { cx } from "../lib/cx";

export type TabItem<T extends string> = {
  content: ReactNode;
  label: string;
  value: T;
};

export type TabsProps<T extends string> = {
  ariaLabel: string;
  onChange: (value: T) => void;
  tabs: Array<TabItem<T>>;
  value: T;
};

export function Tabs<T extends string>({ ariaLabel, onChange, tabs, value }: TabsProps<T>) {
  const baseId = useId();
  const listRef = useRef<HTMLDivElement | null>(null);
  const selectedTab = tabs.find((tab) => tab.value === value) ?? tabs[0];

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;

    if (!step) {
      return;
    }

    event.preventDefault();
    const index = tabs.findIndex((tab) => tab.value === selectedTab.value);
    const nextIndex = (index + step + tabs.length) % tabs.length;
    onChange(tabs[nextIndex].value);
    listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[nextIndex]?.focus();
  }

  return (
    <div className="grid gap-4">
      <div
        aria-label={ariaLabel}
        className="flex gap-1 overflow-x-auto border-b border-line"
        onKeyDown={onKeyDown}
        ref={listRef}
        role="tablist"
      >
        {tabs.map((tab, index) => {
          const selected = tab.value === selectedTab.value;

          return (
            <button
              aria-controls={`${baseId}-panel`}
              aria-selected={selected}
              className={cx(
                "focus-ring relative -mb-px h-10 shrink-0 rounded-t-sm px-3 text-base font-medium transition-colors duration-150",
                "after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full after:transition-colors",
                selected ? "text-ink after:bg-accent" : "text-ink-muted after:bg-transparent hover:text-ink",
              )}
              id={`${baseId}-tab-${index}`}
              key={tab.value}
              onClick={() => onChange(tab.value)}
              role="tab"
              tabIndex={selected ? 0 : -1}
              type="button"
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <div className="min-w-0" id={`${baseId}-panel`} role="tabpanel">
        {selectedTab.content}
      </div>
    </div>
  );
}
