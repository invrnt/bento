import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Menu as MenuIcon, X } from "lucide-react";

import { t } from "../i18n/dictionary";
import { cx } from "../lib/cx";
import { BrandMark } from "./BrandMark";
import { IconButton } from "./IconButton";
import { Sidebar } from "./Sidebar";
import type { SidebarItem } from "./Sidebar";
import { StatusIndicator } from "./StatusIndicator";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { ToastViewport } from "./Toast";
import { TopSearch } from "./TopSearch";

export type AppShellProps = {
  activePath: string;
  children: ReactNode;
  navItems: SidebarItem[];
  onNavigate: (href: string) => void;
  onSearch: (query: string) => void;
  /** Sidebar footer above the theme switcher: account, usage and a one-line status. */
  sidebarStatus?: ReactNode;
  /** Top-bar status pill. */
  status?: ReactNode;
};

/**
 * The tray (app background) holds two compartments: the sidebar and the raised
 * main panel. On small screens the sidebar becomes a drawer.
 */
export function AppShell({ activePath, children, navItems, onNavigate, onSearch, sidebarStatus, status }: AppShellProps) {
  const [navOpen, setNavOpen] = useState(false);
  const mainRef = useRef<HTMLElement | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    mainRef.current?.scrollTo?.({ top: 0 });
  }, [activePath]);

  useEffect(() => {
    if (!navOpen) {
      return;
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setNavOpen(false);
        menuButtonRef.current?.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [navOpen]);

  function navigate(href: string) {
    setNavOpen(false);
    onNavigate(href);
  }

  return (
    <div className="flex h-dvh min-h-0 bg-tray text-ink">
      <a
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:bg-raised focus:px-3 focus:py-2 focus:text-ink focus:shadow-lg focus:outline-2 focus:outline-focus"
        href="#main-content"
      >
        {t("shell.skipToContent")}
      </a>
      {navOpen ? (
        <div aria-hidden="true" className="fixed inset-0 z-40 animate-fade-in bg-scrim md:hidden" onClick={() => setNavOpen(false)} />
      ) : null}
      <Sidebar
        activePath={activePath}
        className={cx(
          navOpen ? "fixed inset-y-0 left-0 z-50 flex animate-drawer-in bg-tray shadow-xl" : "hidden",
          "md:static md:z-auto md:flex md:animate-none md:shadow-none",
        )}
        footer={
          <>
            {sidebarStatus ? (
              // The status block navigates on its own; close the mobile drawer when it does.
              <div className="contents" onClick={() => setNavOpen(false)}>
                {sidebarStatus}
              </div>
            ) : null}
            <ThemeSwitcher />
          </>
        }
        id="app-sidebar"
        items={navItems}
        onNavigate={navigate}
      />
      <div className="flex min-w-0 flex-1 flex-col md:py-2 md:pr-2">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface md:rounded-xl md:border md:border-line md:shadow-sm">
          <header
            aria-label={t("shell.topbarLabel")}
            className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3 sm:gap-3 md:px-5"
          >
            <IconButton
              aria-controls="app-sidebar"
              aria-expanded={navOpen}
              className="md:hidden"
              icon={navOpen ? <X /> : <MenuIcon />}
              label={navOpen ? t("shell.closeMenu") : t("shell.openMenu")}
              onClick={() => setNavOpen((open) => !open)}
              ref={menuButtonRef}
              tooltipSide="bottom"
            />
            <BrandMark className="size-6 md:hidden" />
            <TopSearch onSubmit={onSearch} />
            <div className="ml-auto flex items-center">{status ?? <StatusIndicator />}</div>
          </header>
          <main
            aria-label={t("shell.mainLabel")}
            className="min-h-0 flex-1 overflow-y-auto"
            id="main-content"
            ref={mainRef}
            tabIndex={-1}
          >
            <div className="flex min-h-full flex-col px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</div>
          </main>
        </div>
      </div>
      <ToastViewport />
    </div>
  );
}
