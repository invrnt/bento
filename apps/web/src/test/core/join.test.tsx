import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AccountStatus } from "../../api/account";
import type { Pairing } from "../../api/pairing";
import type { VaultStatus } from "../../api/vault";
import { JoinScreen } from "../../features/pairing/JoinScreen";
import { JoinRoute } from "../../routes/join";
import { FakeHttpError, fakeApi, qrMatrix, recoveryCode, sequence } from "./testkit";

vi.hoisted(() => Object.defineProperty(navigator, "language", { configurable: true, value: "es-ES" }));

const pairing = (overrides: Partial<Pairing> = {}): Pairing => ({
  code: null, error: null, expires_at: new Date(Date.now() + 600_000).toISOString(), id: "pair_1", link: null, peer: null, qr: null,
  role: "guest", sas: null, state: "waiting", telegram_qr: null, transport: "relay", vault: null, web_link: null, ...overrides,
});
const sas = ["🐙", "🌵", "🎈", "🚀"];
const authorized: AccountStatus = {
  account: { display_name: "Ana", phone_masked: null, premium: false, user_id: 7, username: "ana" },
  error: null, password_hint: null, qr: null, qr_expires_at: null, qr_url: null, step: "authorized",
};
const vault = (state: VaultStatus["state"]): VaultStatus => ({
  created_at: null, devices_count: 2, other_vaults: 0, reason: null, recovery_kit_saved: true, recovery_kit_stale: false, state, usage: { bytes: 0, files: 0 }, vault_id: "vlt_1",
});

afterEach(cleanup);

function renderJoin(routes: Record<string, unknown>, props: Partial<Parameters<typeof JoinScreen>[0]> = {}) {
  const api = fakeApi(routes);
  const onDone = vi.fn();
  render(<JoinScreen client={api.client} loginPollIntervalMs={10} onDone={onDone} pollIntervalMs={10} qrRefreshMs={60_000} {...props} />);
  return { api, onDone };
}

describe("joining from a new device", () => {
  it("joins with a code, shows the emojis while the host approves and downloads the library", async () => {
    const { api, onDone } = renderJoin({
      "GET /pairing/pair_1": sequence(pairing({ sas, state: "awaiting_approval" }), pairing({ sas, state: "awaiting_approval" }), pairing({ state: "completed" })),
      "GET /sync/status": sequence(
        { bootstrap: { done: 1240, total: 3000 }, error: null, last_pull_at: null, last_push_at: null, pending_ops: 0, state: "bootstrapping", waiting_until: null },
        { bootstrap: { done: 1240, total: 3000 }, error: null, last_pull_at: null, last_push_at: null, pending_ops: 0, state: "bootstrapping", waiting_until: null },
        { bootstrap: { done: 3000, total: 3000 }, error: null, last_pull_at: null, last_push_at: null, pending_ops: 0, state: "idle", waiting_until: null },
      ),
      "POST /pairing/join": pairing(),
    });

    const field = screen.getByLabelText("Código de emparejamiento");
    const submit = screen.getByRole("button", { name: "Unirme" });
    fireEvent.change(field, { target: { value: "k7q2mxr9t4w" } });
    expect(field).toHaveValue("K7Q2-MXR9-T4W");
    expect(submit).toBeDisabled();
    fireEvent.change(field, { target: { value: "bento://join?v=1&c=K7Q2-MXR9-T4WA" } });
    expect(field).toHaveValue("K7Q2-MXR9-T4WA");
    fireEvent.click(submit);

    expect(await screen.findByRole("heading", { name: "Confirma en tu otro dispositivo" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Emojis de verificación: 🐙 🌵 🎈 🚀" })).toBeInTheDocument();
    expect(api.callsTo("POST /pairing/join")[0].body).toEqual({ code: "K7Q2-MXR9-T4WA" });

    expect(await screen.findByRole("heading", { name: "Descargando tu biblioteca…" })).toBeInTheDocument();
    expect(await screen.findByText("1.240 de 3.000")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Tu biblioteca está lista" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Abrir mi biblioteca" }));
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("explains a wrong code right on the field", async () => {
    renderJoin({
      "POST /pairing/join": () => {
        throw new FakeHttpError(400, "pairing_code_invalid");
      },
    });
    fireEvent.change(screen.getByLabelText("Código de emparejamiento"), { target: { value: "K7Q2-MXR9-T4WA" } });
    fireEvent.click(screen.getByRole("button", { name: "Unirme" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El código no coincide.");
    expect(screen.getByLabelText("Código de emparejamiento")).toHaveAttribute("aria-invalid", "true");
  });

  it("shows a failed key confirmation with a next step", async () => {
    renderJoin({
      "GET /pairing/pair_1": pairing({ error: { code: "pairing_confirm_failed", message: "" }, state: "failed" }),
      "POST /pairing/join": pairing(),
    });
    fireEvent.change(screen.getByLabelText("Código de emparejamiento"), { target: { value: "K7Q2-MXR9-T4WA" } });
    fireEvent.click(screen.getByRole("button", { name: "Unirme" }));
    expect(await screen.findByRole("heading", { name: "No se pudo conectar" })).toBeInTheDocument();
    expect(screen.getByText(/El código no coincide/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Probar otra vez" }));
    expect(await screen.findByLabelText("Código de emparejamiento")).toBeInTheDocument();
  });

  it("shows its own Telegram QR when the host could not sign it in", async () => {
    renderJoin({
      "GET /pairing/pair_1": pairing({ sas, state: "needs_telegram_login", telegram_qr: qrMatrix }),
      "POST /pairing/join": pairing({ state: "connected" }),
    });
    fireEvent.change(screen.getByLabelText("Código de emparejamiento"), { target: { value: "K7Q2-MXR9-T4WA" } });
    fireEvent.click(screen.getByRole("button", { name: "Unirme" }));
    expect(await screen.findByRole("heading", { name: "Inicia sesión en Telegram" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Código QR para vincular tu cuenta de Telegram" })).toBeInTheDocument();
  });

  it("offers the Telegram fallback when the relay is unavailable, then asks other devices for access", async () => {
    const { api } = renderJoin({
      "GET /account": authorized,
      "GET /pairing/pair_2": pairing({ id: "pair_2", transport: "telegram" }),
      "GET /vault": vault("locked"),
      "POST /pairing/join": () => {
        throw new FakeHttpError(503, "relay_unavailable");
      },
      "POST /pairing/request": pairing({ id: "pair_2", transport: "telegram" }),
    });
    fireEvent.change(screen.getByLabelText("Código de emparejamiento"), { target: { value: "K7Q2-MXR9-T4WA" } });
    fireEvent.click(screen.getByRole("button", { name: "Unirme" }));
    expect(await screen.findByText(/No pudimos usar el servicio de emparejamiento/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión en Telegram" }));

    expect(await screen.findByRole("heading", { name: "Tu nube ya existe en esta cuenta" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Pedir acceso a mis otros dispositivos/ }));
    expect(await screen.findByRole("heading", { name: "Esperando a tus otros dispositivos" })).toBeInTheDocument();
    expect(api.callsTo("POST /pairing/request")).toHaveLength(1);
  });

  it("asks this device to confirm the emojis before it accepts access through Telegram", async () => {
    const vaultInfo = { created_at: "2025-03-12T09:30:00Z", devices_count: 3 };
    const fallback = (overrides: Partial<Pairing> = {}) => pairing({ id: "pair_3", transport: "telegram", vault: vaultInfo, ...overrides });
    const { api, onDone } = renderJoin(
      {
        "GET /account": authorized,
        "GET /pairing/pair_3": sequence(fallback({ sas, state: "awaiting_approval" })),
        "GET /sync/status": { bootstrap: null, error: null, last_pull_at: null, last_push_at: null, pending_ops: 0, state: "idle", waiting_until: null },
        "GET /vault": vault("locked"),
        "POST /pairing/pair_3/confirm": fallback({ sas, state: "approving" }),
        "POST /pairing/request": fallback(),
      },
      { initialStep: "choose" },
    );
    fireEvent.click(await screen.findByRole("button", { name: /Pedir acceso a mis otros dispositivos/ }));

    expect(await screen.findByRole("heading", { name: "¿Ves los mismos emojis en tu otro dispositivo?" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Emojis de verificación: 🐙 🌵 🎈 🚀" })).toBeInTheDocument();
    const summary = screen.getByRole("group", { name: "Nube a la que se unirá este equipo" });
    expect(summary).toHaveTextContent("Creada el 12 de marzo de 2025");
    expect(summary).toHaveTextContent("3 dispositivos");
    expect(api.callsTo("POST /pairing/pair_3/confirm")).toHaveLength(0);

    api.on("GET /pairing/pair_3", sequence(fallback({ sas, state: "approving" }), fallback({ sas, state: "approving" }), fallback({ state: "completed" })));
    fireEvent.click(screen.getByRole("button", { name: "Coinciden" }));
    await waitFor(() => expect(api.callsTo("POST /pairing/pair_3/confirm")).toHaveLength(1));
    expect(await screen.findByText("Esperando el acceso…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Coinciden" })).not.toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Tu biblioteca está lista" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Abrir mi biblioteca" }));
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("stops without accepting anything when the emojis do not match", async () => {
    const fallback = (overrides: Partial<Pairing> = {}) => pairing({ id: "pair_4", sas, state: "awaiting_approval", transport: "telegram", ...overrides });
    const { api } = renderJoin(
      {
        "DELETE /pairing/pair_4": fallback({ sas: null, state: "cancelled" }),
        "GET /account": authorized,
        "GET /pairing/pair_4": fallback(),
        "GET /vault": vault("locked"),
        "POST /pairing/request": fallback(),
      },
      { initialStep: "choose" },
    );
    fireEvent.click(await screen.findByRole("button", { name: /Pedir acceso a mis otros dispositivos/ }));
    expect(screen.queryByRole("group", { name: "Nube a la que se unirá este equipo" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "No coinciden" }));

    expect(await screen.findByRole("heading", { name: "No se añadió este equipo" })).toBeInTheDocument();
    await waitFor(() => expect(api.callsTo("DELETE /pairing/pair_4")).toHaveLength(1));
    expect(api.callsTo("POST /pairing/pair_4/confirm")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Probar otra vez" }));
    expect(await screen.findByRole("heading", { name: "Tu nube ya existe en esta cuenta" })).toBeInTheDocument();
  });

  it("explains why it cannot ask for access when the account has several clouds", async () => {
    renderJoin(
      {
        "POST /pairing/request": () => {
          throw new FakeHttpError(409, "pairing_vault_ambiguous");
        },
      },
      { initialStep: "choose" },
    );
    fireEvent.click(await screen.findByRole("button", { name: /Pedir acceso a mis otros dispositivos/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Tu cuenta de Telegram tiene varias nubes de Bento");
  });

  it("does not ask relay guests to confirm: the code already authenticates the other device", async () => {
    renderJoin({
      "GET /pairing/pair_1": pairing({ sas, state: "awaiting_approval" }),
      "POST /pairing/join": pairing(),
    });
    fireEvent.change(screen.getByLabelText("Código de emparejamiento"), { target: { value: "K7Q2-MXR9-T4WA" } });
    fireEvent.click(screen.getByRole("button", { name: "Unirme" }));
    expect(await screen.findByRole("heading", { name: "Confirma en tu otro dispositivo" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Coinciden" })).not.toBeInTheDocument();
  });

  it("unlocks with the recovery kit when there is no other device", async () => {
    const { api } = renderJoin({
      "GET /account": authorized,
      "GET /sync/status": { bootstrap: null, error: null, last_pull_at: null, last_push_at: null, pending_ops: 0, state: "idle", waiting_until: null },
      "GET /vault": vault("locked"),
      "POST /vault/unlock": sequence(new FakeHttpError(400, "recovery_code_invalid"), vault("bootstrapping")),
    });
    fireEvent.click(screen.getByRole("button", { name: "No tengo el otro dispositivo" }));
    fireEvent.click(await screen.findByRole("button", { name: /Usar mi kit de recuperación/ }));

    const field = screen.getByLabelText("Código de recuperación");
    fireEvent.change(field, { target: { value: recoveryCode.toLowerCase().replaceAll("-", "") } });
    expect(field).toHaveValue(recoveryCode);
    fireEvent.click(screen.getByRole("button", { name: "Desbloquear" }));
    expect(await screen.findByText("Ese código no abre esta nube. Revísalo e inténtalo otra vez.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Desbloquear" }));
    expect(await screen.findByRole("heading", { name: "Tu biblioteca está lista" })).toBeInTheDocument();
    expect(api.callsTo("POST /vault/unlock")[1].body).toEqual({ recovery_code: recoveryCode });
  });

  it("offers to create a cloud when the account has none", async () => {
    const onCreateVault = vi.fn();
    renderJoin({ "GET /account": authorized, "GET /vault": vault("no_vault") }, { onCreateVault });
    fireEvent.click(screen.getByRole("button", { name: "No tengo el otro dispositivo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Crear mi nube" }));
    expect(onCreateVault).toHaveBeenCalledOnce();
  });

  it("explains a removal and offers to join again or to use the recovery kit", () => {
    const onLocalOnly = vi.fn();
    renderJoin({}, { initialStep: "removed", onLocalOnly });
    expect(screen.getByRole("heading", { name: "Este equipo se quitó de tu nube" })).toBeInTheDocument();
    expect(screen.getByText(/no se borró nada/)).toBeInTheDocument();
    expect(screen.getByText(/Bento lo añadirá como un dispositivo nuevo/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Volver a unir este equipo" }));
    expect(screen.getByRole("heading", { name: "Conecta este equipo a tu nube" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Atrás" }));
    expect(screen.getByRole("heading", { name: "Este equipo se quitó de tu nube" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Usar mi kit de recuperación" }));
    expect(screen.getByRole("heading", { name: "Escribe tu código de recuperación" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Atrás" }));
    expect(screen.getByRole("heading", { name: "Este equipo se quitó de tu nube" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Usar solo en este equipo" }));
    expect(onLocalOnly).toHaveBeenCalledOnce();
  });

  it("unlocks a removed device with the recovery kit", async () => {
    const { api } = renderJoin(
      {
        "GET /sync/status": { bootstrap: null, error: null, last_pull_at: null, last_push_at: null, pending_ops: 0, state: "idle", waiting_until: null },
        "POST /vault/unlock": vault("bootstrapping"),
      },
      { initialStep: "removed" },
    );
    fireEvent.click(screen.getByRole("button", { name: "Usar mi kit de recuperación" }));
    fireEvent.change(screen.getByLabelText("Código de recuperación"), { target: { value: recoveryCode } });
    fireEvent.click(screen.getByRole("button", { name: "Desbloquear" }));
    expect(await screen.findByRole("heading", { name: "Tu biblioteca está lista" })).toBeInTheDocument();
    expect(api.callsTo("POST /vault/unlock")[0].body).toEqual({ recovery_code: recoveryCode });
  });

  it("calmly explains when this device is already part of the cloud", () => {
    renderJoin({}, { alreadyMember: true });
    expect(screen.getByRole("heading", { name: "Este equipo ya está en tu nube" })).toBeInTheDocument();
  });

  it("cancels an ongoing pairing when the person goes back", async () => {
    const { api } = renderJoin({
      "DELETE /pairing/pair_1": pairing({ state: "cancelled" }),
      "GET /pairing/pair_1": pairing(),
      "POST /pairing/join": pairing(),
    });
    fireEvent.change(screen.getByLabelText("Código de emparejamiento"), { target: { value: "K7Q2-MXR9-T4WA" } });
    fireEvent.click(screen.getByRole("button", { name: "Unirme" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(api.callsTo("DELETE /pairing/pair_1")).toHaveLength(1));
    expect(await screen.findByLabelText("Código de emparejamiento")).toBeInTheDocument();
  });
});

describe("join route", () => {
  it("prefills the code from /join?c=… and #v=1&c=… links", () => {
    const onDone = vi.fn();
    const { unmount } = render(<JoinRoute hash="" onDone={onDone} search="?c=k7q2mxr9t4wa" />);
    expect(screen.getByLabelText("Código de emparejamiento")).toHaveValue("K7Q2-MXR9-T4WA");
    unmount();
    render(<JoinRoute hash="#v=1&c=AB12-CD34-EF56" onDone={onDone} search="" />);
    expect(screen.getByLabelText("Código de emparejamiento")).toHaveValue("AB12-CD34-EF56");
  });
});
