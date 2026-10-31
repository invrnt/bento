import { useEffect, useRef } from "react";
import { Search } from "lucide-react";

import { t } from "../i18n/dictionary";
import { Kbd } from "./Kbd";

export type TopSearchProps = {
  onSubmit: (query: string) => void;
};

export function TopSearch({ onSubmit }: TopSearchProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const shortcut = isApplePlatform() ? t("search.shortcutMac") : t("search.shortcut");

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    }

    document.addEventListener("keydown", onKeyDown);

    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <form
      aria-label={t("search.label")}
      className="relative flex w-full min-w-0 max-w-xl flex-1 items-center"
      onSubmit={(event) => {
        event.preventDefault();
        const formData = new FormData(event.currentTarget);
        onSubmit(String(formData.get("q") ?? ""));
      }}
      role="search"
    >
      <Search aria-hidden="true" className="pointer-events-none absolute left-3 size-4 text-ink-subtle" />
      <input
        aria-label={t("search.label")}
        className="peer h-9 w-full rounded-md border border-transparent bg-subtle pl-9 pr-3 text-base sm:pr-16 text-ink outline-none transition-[background-color,border-color,box-shadow] duration-150 placeholder:text-ink-subtle hover:border-line focus:border-accent focus:bg-raised focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-focus)_22%,transparent)]"
        name="q"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            if (event.currentTarget.value) {
              event.currentTarget.value = "";
            } else {
              event.currentTarget.blur();
            }
          }
        }}
        placeholder={t("search.placeholder")}
        ref={inputRef}
        type="search"
      />
      <span className="pointer-events-none absolute right-2.5 hidden peer-focus:opacity-0 sm:flex">
        <Kbd>{shortcut}</Kbd>
      </span>
    </form>
  );
}

function isApplePlatform(): boolean {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
}
