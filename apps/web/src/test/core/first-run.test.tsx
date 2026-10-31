import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AccountStatus } from "../../api/account";
import type { VaultStatus } from "../../api/vault";
import { FirstRun } from "../../features/onboarding/FirstRun";
import { FakeHttpError, fakeApi, installBridge, installMemoryStorage, qrMatrix, recoveryCode, removeBridge, sequence } from "./testkit";

vi.hoisted(() => Object.defineProperty(navigator, "language", { configurable: true, value: "es-ES" }));

const account = { display_name: "Ana", phone_masked: "+57 ••• ••• 12", premium: false, user_id: 7, username: "ana" };
const status = (overrides: Partial<AccountStatus> = {}): AccountStatus => ({
  account: null, error: null, password_hint: null, qr: null, qr_expires_at: null, qr_url: null, step: "signed_out", ...overrides,
});
const authorized = status({ account, step: "authorized" });
const vault = (overrides: Partial<VaultStatus> = {}): VaultStatus => ({
  created_at: "2026-10-31T10:00:00Z", devices_count: 1, other_vaults: 0, recovery_kit_saved: false, state: "ready", usage: { bytes: 0, files: 0 }, vault_id: "vlt_1", ...overrides,
});
const source = (path: string, label: string) => ({
  bytes_pending: 0, enabled: true, error: null, files_done: 0, files_pending: 0, files_total: 0, id: `src_${label}`, label, last_scan_at: null, path, state: "scanning",
});

function setup(routes: Record<string, unknown> = {}) {
  const api = fakeApi({
    "GET /account": sequence(status(), status({ qr: qrMatrix, step: "qr_pending" }), authorized),
    "GET /backup/sources": { items: [] },
    "GET /backup/suggestions": {
      items: [
        { kind: "pictures", label: "Imágenes", path: "/home/ana/Imágenes" },
        { kind: "documents", label: "Documentos", path: "/home/ana/Documentos" },
      ],
    },
    "GET /vault": vault({ state: "no_vault" }),
    "POST /account/login/qr": status({ qr: qrMatrix, qr_url: "tg://login?token=abc", step: "qr_pending" }),
    "POST /backup/sources": ({ body }: { body: { label: string; path: string } }) => source(body.path, body.label),
    "POST /vault": { recovery_code: recoveryCode, vault: vault() },
    "POST /vault/recovery-code/confirm": vault({ recovery_kit_saved: true }),
    ...routes,
  });
  const handlers = { onExistingVault: vi.fn(), onFinish: vi.fn(), onJoin: vi.fn(), onLocalOnly: vi.fn() };
  render(<FirstRun client={api.client} loginPollIntervalMs={10} qrRefreshMs={60_000} {...handlers} />);
  return { api, ...handlers };
}

beforeEach(() => {
  installMemoryStorage();
});

afterEach(() => {
  cleanup();
  removeBridge();
});

describe("first run", () => {
  it("signs in with the QR, creates the vault, picks folders, confirms the kit and finishes", async () => {
    const bridge = installBridge();
    let releaseVault: () => void = () => undefined;
    const { api, onFinish } = setup({
      "POST /vault": () => new Promise((resolve) => (releaseVault = () => resolve({ recovery_code: recoveryCode, vault: vault() }))),
    });

    expect(screen.getByRole("heading", { name: "Tu nube privada, sin límite de espacio, guardada en tu Telegram." })).toBeInTheDocument();
    expect(screen.getByText(/no está afiliado a Telegram/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Empezar" }));

    expect(screen.getByRole("heading", { name: "Conecta tu Telegram" })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "Código QR para vincular tu cuenta de Telegram" })).toBeInTheDocument();
    expect(screen.getByText("Ve a Ajustes › Dispositivos › Vincular dispositivo de escritorio.")).toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Creando tu nube" })).toBeInTheDocument();
    expect(await screen.findByText("Conectado como Ana")).toBeInTheDocument();
    releaseVault();

    expect(await screen.findByRole("heading", { name: "Elige qué respaldar" })).toBeInTheDocument();
    const pictures = await screen.findByRole("checkbox", { name: "Imágenes" });
    const documents = screen.getByRole("checkbox", { name: "Documentos" });
    expect(pictures).toBeChecked();
    expect(documents).toBeChecked();
    fireEvent.click(documents);
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByRole("heading", { name: "Guarda tu kit de recuperación" })).toBeInTheDocument();
    expect(api.callsTo("POST /backup/sources").map((call) => call.body)).toEqual([{ label: "Imágenes", path: "/home/ana/Imágenes" }]);
    const groups = within(screen.getByTestId("recovery-code"));
    expect(groups.getByText("K7QM")).toBeInTheDocument();
    expect(groups.getByText("R2KD")).toBeInTheDocument();

    const lastGroup = screen.getByLabelText("Último grupo del código");
    fireEvent.change(lastGroup, { target: { value: "aaaa" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByText("Ese grupo no coincide. Revisa el último grupo del código.")).toBeInTheDocument();
    expect(api.callsTo("POST /vault/recovery-code/confirm")).toHaveLength(0);

    fireEvent.change(lastGroup, { target: { value: "r2kd" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByRole("heading", { name: "Todo listo" })).toBeInTheDocument();
    expect(api.callsTo("POST /vault/recovery-code/confirm")[0].body).toEqual({ last_group: "R2KD" });
    await waitFor(() => expect(bridge.preferences.set).toHaveBeenCalledWith({ launchAtLogin: true }));

    fireEvent.click(screen.getByRole("button", { name: "Abrir mi biblioteca" }));
    expect(onFinish).toHaveBeenCalledOnce();
  });

  it("signs in by phone with a code and the two-step password", async () => {
    const { api } = setup({
      "GET /account": status(),
      "POST /account/login/code": status({ password_hint: "gato", step: "password_required" }),
      "POST /account/login/password": authorized,
      "POST /account/login/phone": status({ step: "code_required" }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Empezar" }));
    await screen.findByRole("img", { name: "Código QR para vincular tu cuenta de Telegram" });
    fireEvent.click(screen.getByRole("button", { name: "Usar mi número de teléfono" }));

    fireEvent.change(screen.getByLabelText("Número de teléfono"), { target: { value: "+57 300 123 4567" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar código" }));
    const code = await screen.findByLabelText("Código de Telegram");
    fireEvent.change(code, { target: { value: "12345" } });
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByText("Pista: gato")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Contraseña de verificación en dos pasos"), { target: { value: "secreta" } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));

    expect(await screen.findByRole("heading", { name: "Elige qué respaldar" })).toBeInTheDocument();
    expect(api.callsTo("POST /account/login/phone")[0].body).toEqual({ phone: "+573001234567" });
    expect(api.callsTo("POST /account/login/code")[0].body).toEqual({ code: "12345" });
    expect(api.callsTo("POST /account/login/password")[0].body).toEqual({ password: "secreta" });
  });

  it("explains a Telegram flood wait with a countdown and blocks retries", async () => {
    setup({
      "GET /account": status(),
      "POST /account/login/phone": () => {
        throw new FakeHttpError(429, "telegram_flood_wait", { retry_after_seconds: 240 });
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Empezar" }));
    await screen.findByRole("img", { name: "Código QR para vincular tu cuenta de Telegram" });
    fireEvent.click(screen.getByRole("button", { name: "Usar mi número de teléfono" }));
    fireEvent.change(screen.getByLabelText("Número de teléfono"), { target: { value: "+57 300 123 4567" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar código" }));

    expect(await screen.findByText("Telegram pidió esperar")).toBeInTheDocument();
    expect(screen.getByText(/esperar 4 min; podrás intentarlo otra vez en [34]:\d\d/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar código" })).toBeDisabled();
  });

  it("shows human errors for a wrong code", async () => {
    setup({
      "GET /account": status({ step: "code_required" }),
      "POST /account/login/code": () => {
        throw new FakeHttpError(400, "telegram_code_invalid");
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Empezar" }));
    fireEvent.change(await screen.findByLabelText("Código de Telegram"), { target: { value: "99999" } });
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El código no es correcto. Revísalo e inténtalo otra vez.");
  });

  it("keeps Bento on this device only through the settings API", async () => {
    const { api, onLocalOnly } = setup({
      "GET /settings/values": { revision: 4, values: { storage_backend: { apply_mode: "restart_services", locked: false, source: "saved", value: "telegram" } } },
      "PATCH /settings/values": { restart_plan: { affected_keys: [], mode: "live", services: [] }, revision: 5, values: {} },
    });
    fireEvent.click(screen.getByRole("button", { name: "Usar solo en este equipo" }));
    await waitFor(() => expect(onLocalOnly).toHaveBeenCalledOnce());
    expect(api.callsTo("PATCH /settings/values")[0].body).toEqual({ revision: 4, values: { storage_backend: "local" } });
    expect(window.localStorage.getItem("bento:local-mode")).toBe("1");
  });

  it("hands over to the join flow when the account already has a vault", async () => {
    const { api, onExistingVault, onJoin } = setup({ "GET /account": authorized, "GET /vault": vault({ state: "locked" }) });
    fireEvent.click(screen.getByRole("button", { name: "Ya uso Bento en otro dispositivo" }));
    expect(onJoin).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Empezar" }));
    await waitFor(() => expect(onExistingVault).toHaveBeenCalledOnce());
    expect(api.callsTo("POST /vault")).toHaveLength(0);
  });

  it("lets the person save the kit later", async () => {
    setup({ "GET /account": authorized, "GET /backup/suggestions": { items: [] } });
    fireEvent.click(screen.getByRole("button", { name: "Empezar" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ahora no" }));
    fireEvent.click(await screen.findByRole("button", { name: "Más tarde" }));
    expect(await screen.findByRole("heading", { name: "Todo listo" })).toBeInTheDocument();
  });
});
