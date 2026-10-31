import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Pairing } from "../../api/pairing";
import { AddDeviceDialog } from "../../features/pairing/AddDeviceDialog";
import { PairingRequestsBanner } from "../../features/pairing/PairingRequestsBanner";
import { FakeHttpError, fakeApi, qrMatrix, sequence } from "./testkit";

vi.hoisted(() => Object.defineProperty(navigator, "language", { configurable: true, value: "es-ES" }));

const sas = ["🐙", "🌵", "🎈", "🚀"];
const peer = { device_name: "Portátil de Ana", platform: "linux" };
const hosted = (overrides: Partial<Pairing> = {}): Pairing => ({
  code: "K7Q2-MXR9-T4WA", error: null, expires_at: new Date(Date.now() + 600_000).toISOString(), id: "pair_h", link: "bento://join?v=1&c=K7Q2-MXR9-T4WA",
  peer: null, qr: qrMatrix, role: "host", sas: null, state: "waiting", telegram_qr: null, transport: "relay", vault: null, web_link: "https://bento.app/join#v=1&c=K7Q2-MXR9-T4WA", ...overrides,
});

afterEach(cleanup);

function renderDialog(routes: Record<string, unknown>) {
  const api = fakeApi(routes);
  const onAdded = vi.fn();
  const onOpenChange = vi.fn();
  render(<AddDeviceDialog client={api.client} onAdded={onAdded} onOpenChange={onOpenChange} open pollIntervalMs={10} />);
  return { api, onAdded, onOpenChange };
}

describe("add device (host)", () => {
  it("shows the QR, code, link and countdown, then asks to approve with emojis", async () => {
    const { api, onAdded } = renderDialog({
      "GET /pairing/pair_h": sequence(hosted(), hosted({ peer, sas, state: "awaiting_approval" })),
      "POST /pairing/host": hosted(),
      "POST /pairing/pair_h/approve": hosted({ peer, state: "approving" }),
    });

    const dialog = await screen.findByRole("dialog", { name: "Añadir dispositivo" });
    expect(await within(dialog).findByRole("img", { name: "Código QR para añadir un dispositivo" })).toBeInTheDocument();
    expect(within(dialog).getByTestId("host-code")).toHaveTextContent("K7Q2-MXR9-T4WA");
    expect(within(dialog).getByText("https://bento.app/join#v=1&c=K7Q2-MXR9-T4WA")).toBeInTheDocument();
    expect(within(dialog).getByText(/Caduca en (10:00|9:\d\d)/)).toBeInTheDocument();
    expect(within(dialog).getByText("En el otro equipo, abre Bento y elige «Ya uso Bento en otro dispositivo».")).toBeInTheDocument();

    const approve = await screen.findByRole("dialog", { name: "¿Añadir «Portátil de Ana · Linux»?" });
    expect(within(approve).getByRole("img", { name: "Emojis de verificación: 🐙 🌵 🎈 🚀" })).toBeInTheDocument();

    api.on("GET /pairing/pair_h", hosted({ peer, state: "completed" }));
    fireEvent.click(within(approve).getByRole("button", { name: "Añadir" }));
    expect(await screen.findByText("Dispositivo añadido")).toBeInTheDocument();
    expect(api.callsTo("POST /pairing/pair_h/approve")).toHaveLength(1);
    expect(onAdded).toHaveBeenCalledOnce();
  });

  it("rejects with “No soy yo”", async () => {
    const { api } = renderDialog({
      "GET /pairing/pair_h": hosted({ peer, sas, state: "awaiting_approval" }),
      "POST /pairing/host": hosted(),
      "POST /pairing/pair_h/reject": hosted({ peer, state: "rejected" }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "No soy yo" }));
    expect(await screen.findByText("No se añadió el dispositivo")).toBeInTheDocument();
    expect(api.callsTo("POST /pairing/pair_h/reject")).toHaveLength(1);
  });

  it("explains the fallback when the relay is unavailable", async () => {
    renderDialog({
      "POST /pairing/host": () => {
        throw new FakeHttpError(503, "relay_unavailable");
      },
    });
    expect(await screen.findByText("El emparejamiento rápido no está disponible")).toBeInTheDocument();
    expect(screen.getByText(/«Pedir acceso a mis otros dispositivos»/)).toBeInTheDocument();
  });

  it("offers a new code once the current one expires", async () => {
    const { api } = renderDialog({
      "GET /pairing/pair_h": hosted({ state: "expired" }),
      "POST /pairing/host": sequence(hosted({ expires_at: new Date(Date.now() - 1000).toISOString() }), hosted()),
    });
    expect(await screen.findByText("El código caducó")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generar otro código" }));
    await waitFor(() => expect(api.callsTo("POST /pairing/host")).toHaveLength(2));
  });

  it("cancels the pairing when the dialog closes before finishing", async () => {
    const { api, onOpenChange } = renderDialog({
      "DELETE /pairing/pair_h": hosted({ state: "cancelled" }),
      "GET /pairing/pair_h": hosted(),
      "POST /pairing/host": hosted(),
    });
    await screen.findByTestId("host-code");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
    await waitFor(() => expect(api.callsTo("DELETE /pairing/pair_h")).toHaveLength(1));
  });
});

describe("fallback join requests", () => {
  it("shows a non-modal banner, then reviews the emojis and approves", async () => {
    const api = fakeApi({
      "GET /pairing/pair_r": hosted({ id: "pair_r", peer, state: "completed", transport: "telegram" }),
      "GET /pairing/requests": { items: [{ created_at: "2026-10-31T10:00:00Z", device_name: "Portátil de Ana", id: "req_1", platform: "linux" }] },
      "POST /pairing/requests/req_1/approve": hosted({ id: "pair_r", peer, state: "approving", transport: "telegram" }),
      "POST /pairing/requests/req_1/review": hosted({ id: "pair_r", peer, sas, state: "awaiting_approval", transport: "telegram" }),
    });
    render(<PairingRequestsBanner client={api.client} pollIntervalMs={10} />);

    expect(await screen.findByText("Un dispositivo nuevo quiere unirse")).toBeInTheDocument();
    expect(screen.getByText("«Portátil de Ana · Linux» pidió acceso a tu nube.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revisar" }));

    const dialog = await screen.findByRole("dialog", { name: "¿Añadir «Portátil de Ana · Linux»?" });
    expect(await within(dialog).findByRole("img", { name: "Emojis de verificación: 🐙 🌵 🎈 🚀" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Añadir" }));
    expect(await screen.findByText("Dispositivo añadido")).toBeInTheDocument();
    expect(api.callsTo("POST /pairing/requests/req_1/review")).toHaveLength(1);
    expect(api.callsTo("POST /pairing/requests/req_1/approve")).toHaveLength(1);
  });

  it("tells the person when another device already answered the request", async () => {
    const api = fakeApi({
      "GET /pairing/requests": { items: [{ created_at: "2026-10-31T10:00:00Z", device_name: "Portátil de Ana", id: "req_3", platform: "linux" }] },
      "POST /pairing/requests/req_3/review": hosted({
        error: { code: "pairing_request_taken", message: "Another device answered this request" },
        id: "pair_t",
        peer,
        state: "failed",
        transport: "telegram",
      }),
    });
    render(<PairingRequestsBanner client={api.client} pollIntervalMs={10} />);
    fireEvent.click(await screen.findByRole("button", { name: "Revisar" }));

    const dialog = await screen.findByRole("dialog", { name: "¿Añadir «Portátil de Ana · Linux»?" });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Otro dispositivo respondió a esta solicitud. Si no fuiste tú, cancela en el equipo nuevo.",
    );
    expect(within(dialog).queryByRole("button", { name: "Añadir" })).not.toBeInTheDocument();
    const closeButtons = within(dialog).getAllByRole("button", { name: "Cerrar" });
    fireEvent.click(closeButtons[closeButtons.length - 1]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("explains that a removed device has to join as a new one", async () => {
    const api = fakeApi({
      "GET /pairing/requests": { items: [{ created_at: "2026-10-31T10:00:00Z", device_name: "Mesa", id: "req_4", platform: "windows" }] },
      "POST /pairing/requests/req_4/review": () => {
        throw new FakeHttpError(409, "pairing_device_removed");
      },
    });
    render(<PairingRequestsBanner client={api.client} pollIntervalMs={10} />);
    fireEvent.click(await screen.findByRole("button", { name: "Revisar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ese equipo se quitó de tu nube");
  });

  it("can be dismissed for now", async () => {
    const api = fakeApi({
      "GET /pairing/requests": { items: [{ created_at: "2026-10-31T10:00:00Z", device_name: "Mesa", id: "req_2", platform: "windows" }] },
    });
    render(<PairingRequestsBanner client={api.client} pollIntervalMs={10} />);
    fireEvent.click(await screen.findByRole("button", { name: "Ahora no" }));
    expect(screen.queryByText("Un dispositivo nuevo quiere unirse")).not.toBeInTheDocument();
  });
});
