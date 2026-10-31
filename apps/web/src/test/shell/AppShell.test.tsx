import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SidebarStatus } from "../../app/status";
import { AppShell } from "../../components/AppShell";
import { clearToasts, showToast } from "../../components/Toast";
import { describeActivity } from "../../features/activity/activityModel";
import { navItems } from "../../routes/routeConfig";

describe("AppShell", () => {
  afterEach(() => act(() => clearToasts()));

  it("puts the account status above the theme switcher and closes the drawer when it is used", () => {
    const onNavigate = vi.fn();
    render(
      <AppShell
        activePath="/photos"
        navItems={navItems}
        onNavigate={onNavigate}
        onSearch={vi.fn()}
        sidebarStatus={<SidebarStatus account={null} onNavigate={onNavigate} status={describeActivity(null)} usage={null} />}
      >
        <p>Contenido</p>
      </AppShell>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Abrir menú" }));
    const sidebar = document.getElementById("app-sidebar")!;
    const status = within(sidebar).getByRole("link", { name: /Este equipo/ });
    expect(status.compareDocumentPosition(within(sidebar).getByRole("radiogroup", { name: "Tema" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(status);
    expect(onNavigate).toHaveBeenCalledWith("/activity");
    expect(screen.getByRole("button", { name: "Abrir menú" })).toHaveAttribute("aria-expanded", "false");
  });

  it("lists Trash in the System group and hosts the toast region", () => {
    render(
      <AppShell activePath="/trash" navItems={navItems} onNavigate={vi.fn()} onSearch={vi.fn()}>
        <p>Contenido</p>
      </AppShell>,
    );

    expect(screen.getByRole("link", { name: "Papelera" })).toHaveAttribute("aria-current", "page");
    act(() => {
      showToast({ message: "Movido a la papelera" });
    });
    expect(within(screen.getByRole("region", { name: "Notificaciones" })).getByRole("status")).toHaveTextContent("Movido a la papelera");
  });
});
