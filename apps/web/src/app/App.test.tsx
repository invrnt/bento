import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../api/client";
import type { VaultStatus } from "../api/vault";
import { fakeApi, installBridge, installMemoryStorage, removeBridge } from "../test/core/testkit";
import { App } from "./App";

const vault = (state: VaultStatus["state"]): VaultStatus => ({
  created_at: null, devices_count: 1, other_vaults: 0, recovery_kit_saved: true, state, usage: { bytes: 0, files: 0 }, vault_id: "vlt_1",
});

/** Routes every typed client call through an in-memory API (the default client captured `fetch` at import). */
function routeApi(routes: Record<string, unknown>) {
  const api = fakeApi(routes);
  vi.spyOn(apiClient, "request").mockImplementation((path, options) => api.client.request(path, options));
  return api;
}

beforeEach(() => {
  installMemoryStorage();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  removeBridge();
  window.history.pushState({}, "", "/");
});

describe("App", () => {
  it("redirects the root route to photos and renders the shell", async () => {
    window.history.pushState({}, "", "/");

    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe("/photos"));
    expect(await screen.findByRole("navigation", { name: "Navegación principal" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Búsqueda global" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fotos" })).toBeInTheDocument();
  });

  it("navigates between placeholder routes without a full reload", async () => {
    window.history.pushState({}, "", "/photos");

    render(<App />);
    fireEvent.click(await screen.findByRole("link", { name: "Drive" }));

    expect(window.location.pathname).toBe("/drive");
    expect(screen.getByRole("heading", { name: "Drive" })).toBeInTheDocument();
  });

  it("focuses global search with the keyboard shortcut", async () => {
    window.history.pushState({}, "", "/photos");

    render(<App />);
    const search = await screen.findByRole("searchbox", { name: "Búsqueda global" });
    fireEvent.keyDown(document, { ctrlKey: true, key: "k" });

    expect(search).toHaveFocus();
  });

  it("submits global search to the search route", async () => {
    window.history.pushState({}, "", "/photos");

    render(<App />);
    const search = await screen.findByRole("searchbox", { name: "Búsqueda global" });

    fireEvent.change(search, { target: { value: "factura" } });
    fireEvent.submit(search.closest("form")!);

    expect(window.location.pathname).toBe("/search");
    expect(window.location.search).toBe("?q=factura");
    expect(screen.getByRole("heading", { name: "Búsqueda" })).toBeInTheDocument();
  });
});

describe("first-run gate", () => {
  it("shows the welcome for a signed-out device", async () => {
    routeApi({ "GET /vault": vault("signed_out") });
    window.history.pushState({}, "", "/photos");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Tu nube privada, sin límite de espacio, guardada en tu Telegram." })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Navegación principal" })).not.toBeInTheDocument();
  });

  it("opens the library when local mode was chosen", async () => {
    window.localStorage.setItem("bento:local-mode", "1");
    routeApi({ "GET /vault": vault("signed_out") });
    window.history.pushState({}, "", "/photos");
    render(<App />);
    expect(await screen.findByRole("navigation", { name: "Navegación principal" })).toBeInTheDocument();
  });

  it("offers the join or recovery choice when this device is locked", async () => {
    routeApi({ "GET /vault": vault("locked") });
    window.history.pushState({}, "", "/photos");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Tu nube ya existe en esta cuenta" })).toBeInTheDocument();
  });

  it("goes from the welcome to the join screen", async () => {
    routeApi({ "GET /vault": vault("no_vault") });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Ya uso Bento en otro dispositivo" }));
    expect(window.location.pathname).toBe("/join");
    expect(await screen.findByRole("heading", { name: "Conecta este equipo a tu nube" })).toBeInTheDocument();
  });

  it("opens desktop join links on the join screen with the code filled in", async () => {
    let emit: (link: unknown) => void = () => undefined;
    const bridge = installBridge({ onDeepLink: vi.fn((listener) => ((emit = listener), vi.fn())) });
    routeApi({ "GET /vault": vault("signed_out") });
    render(<App />);
    await screen.findByRole("button", { name: "Empezar" });
    expect(bridge.onDeepLink).toHaveBeenCalled();

    act(() => emit({ code: "K7Q2-MXR9-T4WA", kind: "join" }));
    expect(window.location.pathname).toBe("/join");
    expect(await screen.findByLabelText("Código de emparejamiento")).toHaveValue("K7Q2-MXR9-T4WA");
  });

  it("explains a join link on a device that is already set up", async () => {
    routeApi({ "GET /pairing/requests": { items: [] }, "GET /vault": vault("ready") });
    window.history.pushState({}, "", "/join?c=K7Q2-MXR9-T4WA");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Este equipo ya está en tu nube" })).toBeInTheDocument();
  });

  it("routes the Actividad recovery-kit link to Cuenta y nube", async () => {
    routeApi({
      "GET /account": { account: null, error: null, password_hint: null, qr: null, qr_expires_at: null, qr_url: null, step: "authorized" },
      "GET /pairing/requests": { items: [] },
      "GET /vault": { ...vault("ready"), recovery_kit_saved: false },
    });
    window.history.pushState({}, "", "/settings?section=recovery");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Kit de recuperación" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cuenta y nube" })).toHaveAttribute("aria-current", "page");
  });
});
