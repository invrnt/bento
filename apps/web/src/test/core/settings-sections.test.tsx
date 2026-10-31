import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SettingDefinition } from "../../api/settings";
import type { VaultStatus } from "../../api/vault";
import { SettingsPage } from "../../features/settings/SettingsPage";
import type { SettingsSection } from "../../features/settings/sections";
import { settingsLocation } from "../../features/settings/sections";
import type { SettingsController } from "../../features/settings/useSettingsController";
import { FakeHttpError, fakeApi, installBridge, installMemoryStorage, recoveryCode, removeBridge } from "./testkit";

const field = (overrides: Partial<SettingDefinition> & Pick<SettingDefinition, "key" | "group" | "type">): SettingDefinition => ({
  apply_mode: "restart_worker", availability: "both", constraints: { choices: [], maximum: null, minimum: null }, default: null, editable: true,
  env_aliases: [overrides.key.toUpperCase()], help_key: `settings.${overrides.key}.help`, label_key: `settings.${overrides.key}.label`, locked: false, probe: null,
  secret: false, source: "saved", ...overrides,
});

const fields: SettingDefinition[] = [
  field({ constraints: { choices: ["disabled", "mock", "rapidocr"], maximum: null, minimum: null }, group: "ai", key: "ocr_provider", type: "choice" }),
  field({ constraints: { choices: ["disabled", "mock", "jina"], maximum: null, minimum: null }, group: "ai", key: "embeddings_provider", type: "choice" }),
  field({ group: "performance", key: "worker_concurrency", type: "integer" }),
  field({ group: "storage", key: "data_dir", probe: "writable_directory", type: "path" }),
  field({ constraints: { choices: ["local", "telegram"], maximum: null, minimum: null }, env_aliases: ["STORAGE_BACKEND"], group: "storage", key: "storage_backend", locked: true, source: "environment", type: "choice" }),
  field({ group: "telegram", key: "telegram_bot_token", secret: true, type: "secret" }),
];

function controller(overrides: Partial<SettingsController> = {}): SettingsController {
  return {
    applyOutcome: null, applyProgress: [], conflict: false, dataMigration: null, desktop: null, dirty: false, discard: vi.fn(), dismissImport: vi.fn(),
    draft: { data_dir: "/data", embeddings_provider: "mock", ocr_provider: "disabled", storage_backend: "telegram", worker_concurrency: 1 },
    error: null, exportSafe: vi.fn(), fieldErrors: {}, importPreview: null, importPreviewFromFile: vi.fn(), importValues: vi.fn(), isApplying: false,
    isLoading: false, isReclaiming: false, isValidating: false, pickPath: vi.fn(), probe: vi.fn(),
    publicSettings: { embeddings_state: "ready", ocr_state: "disabled", storage_backend: "telegram" }, reclaim: vi.fn(), reclaimError: null,
    reclaimResult: null, refresh: vi.fn(), resetGroup: vi.fn(), save: vi.fn(), schema: { fields, revision: 3 }, setDataMigration: vi.fn(), setValue: vi.fn(),
    validate: vi.fn(), validation: null,
    values: {
      revision: 3,
      values: {
        app_version: { apply_mode: "live", locked: false, source: "default", value: "0.9.0" },
        data_dir: { apply_mode: "restart_app", locked: false, source: "saved", value: "/data" },
        embeddings_provider: { apply_mode: "restart_services", locked: false, source: "saved", value: "mock" },
        ocr_provider: { apply_mode: "restart_worker", locked: false, source: "saved", value: "disabled" },
        storage_backend: { apply_mode: "restart_services", locked: true, source: "environment", value: "telegram" },
        worker_concurrency: { apply_mode: "restart_worker", locked: false, source: "saved", value: 1 },
      },
    },
    ...overrides,
  };
}

const vault = (overrides: Partial<VaultStatus> = {}): VaultStatus => ({
  created_at: "2026-10-01T10:00:00Z", devices_count: 2, other_vaults: 0, recovery_kit_saved: true, state: "ready",
  usage: { bytes: 52_428_800_000, files: 1200 }, vault_id: "vlt_1", ...overrides,
});
const signedIn = {
  account: { display_name: "Ana Pérez", phone_masked: "+57 ••• ••• 12", premium: true, user_id: 7, username: "ana" },
  error: null, password_hint: null, qr: null, qr_expires_at: null, qr_url: null, step: "authorized",
};

function renderSettings(section: SettingsSection, routes: Record<string, unknown> = {}, state: SettingsController = controller(), extra: Record<string, unknown> = {}) {
  const api = fakeApi({ "GET /account": signedIn, "GET /vault": vault(), ...routes });
  const onNavigate = vi.fn();
  const onStartSetup = vi.fn();
  render(<SettingsPage client={api.client} controller={state} onNavigate={onNavigate} onStartSetup={onStartSetup} pollIntervalMs={10} section={section} {...extra} />);
  return { api, onNavigate, onStartSetup };
}

beforeEach(() => {
  installMemoryStorage();
});

afterEach(() => {
  cleanup();
  removeBridge();
});

describe("settings information architecture", () => {
  it("lists the sections as links and navigates without reloading", () => {
    const { onNavigate } = renderSettings("general");
    const nav = screen.getByRole("navigation", { name: "Categorías de Ajustes" });
    const labels = within(nav).getAllByRole("link").map((link) => link.textContent);
    expect(labels).toEqual(["General", "Cuenta y nube", "Dispositivos", "Respaldo", "Búsqueda inteligente", "Avanzado", "Acerca de"]);
    expect(within(nav).getByRole("link", { name: "General" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(within(nav).getByRole("link", { name: "Dispositivos" }));
    expect(onNavigate).toHaveBeenCalledWith("/settings/devices");
  });

  it("maps paths and ?section= links to sections", () => {
    expect(settingsLocation("/settings")).toEqual({ focus: null, section: "general" });
    expect(settingsLocation("/settings/backup")).toEqual({ focus: null, section: "backup" });
    expect(settingsLocation("/settings/recovery")).toEqual({ focus: "recovery", section: "account" });
    expect(settingsLocation("/settings", "?section=recovery")).toEqual({ focus: "recovery", section: "account" });
    expect(settingsLocation("/settings", "?section=devices")).toEqual({ focus: null, section: "devices" });
    expect(settingsLocation("/settings/unknown")).toEqual({ focus: null, section: "general" });
  });

  it("never shows environment variable names outside Avanzado", () => {
    for (const section of ["general", "smart-search", "about"] as const) {
      renderSettings(section);
      expect(screen.queryByText(/STORAGE_BACKEND|OCR_PROVIDER|EMBEDDINGS_PROVIDER/)).not.toBeInTheDocument();
      cleanup();
    }
  });
});

describe("General", () => {
  it("changes the language and explains desktop-only options in the browser", () => {
    const onLocaleChange = vi.fn();
    renderSettings("general", {}, controller(), { onLocaleChange });
    fireEvent.change(screen.getByRole("combobox", { name: "Idioma de Bento" }), { target: { value: "en" } });
    expect(onLocaleChange).toHaveBeenCalledWith("en");
    expect(screen.getByRole("radiogroup", { name: "Tema" })).toBeInTheDocument();
    expect(screen.getByText(/están disponibles en Bento Desktop/)).toBeInTheDocument();
  });

  it("saves desktop preferences immediately and explains a refused login item", async () => {
    const bridge = installBridge();
    renderSettings("general");
    const launch = await screen.findByRole("checkbox", { name: "Abrir Bento al iniciar sesión" });
    await waitFor(() => expect(launch).toBeEnabled());
    expect(screen.getByRole("checkbox", { name: "Seguir en segundo plano al cerrar la ventana" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Descargar actualizaciones automáticamente" })).toBeChecked();

    fireEvent.click(launch);
    await waitFor(() => expect(bridge.preferences.set).toHaveBeenCalledWith({ launchAtLogin: true }));
    expect(await screen.findByText("Cambios guardados.")).toBeInTheDocument();

    bridge.preferences.set.mockRejectedValueOnce(new Error("Error invoking remote method 'bento:preferences-set': Error: preferences_launch_at_login_failed"));
    fireEvent.click(launch);
    expect(await screen.findByText(/Tu sistema no permitió abrir Bento al iniciar sesión/)).toBeInTheDocument();
  });
});

describe("Cuenta y nube", () => {
  it("shows the account, usage and signs out explaining the consequence", async () => {
    const { api } = renderSettings("account", { "POST /account/logout": { ...signedIn, account: null, step: "signed_out" } });
    expect(await screen.findByRole("heading", { name: "Ana Pérez" })).toBeInTheDocument();
    expect(screen.getByText("@ana · +57 ••• ••• 12")).toBeInTheDocument();
    expect(screen.getByText("Premium")).toBeInTheDocument();
    expect(screen.getByText("1.200")).toBeInTheDocument();
    expect(screen.getByText("48,8 GB")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
    const dialog = screen.getByRole("dialog", { name: "¿Cerrar sesión de Telegram?" });
    expect(within(dialog).getByText(/Tu biblioteca se queda en este equipo/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cerrar sesión" }));
    await waitFor(() => expect(api.callsTo("POST /account/logout")).toHaveLength(1));
    expect(window.localStorage.getItem("bento:local-mode")).toBe("1");
  });

  it("offers to connect Telegram when signed out", async () => {
    const { onStartSetup } = renderSettings("account", { "GET /account": { ...signedIn, account: null, step: "signed_out" }, "GET /vault": vault({ state: "local_only" }) });
    fireEvent.click(await screen.findByRole("button", { name: "Conectar mi Telegram" }));
    expect(onStartSetup).toHaveBeenCalledOnce();
  });

  it("only shows a recovery code right after generating a new one, and verifies codes", async () => {
    const { api } = renderSettings("account", {
      "GET /vault": vault({ recovery_kit_saved: false }),
      "POST /vault/recovery-code": { recovery_code: recoveryCode },
      "POST /vault/recovery-code/verify": ({ body }: { body: { recovery_code: string } }) => {
        if (body.recovery_code.startsWith("AAAA")) throw new FakeHttpError(400, "recovery_code_checksum");
        return { valid: body.recovery_code === recoveryCode };
      },
    });
    const card = await screen.findByRole("region", { name: /Kit de recuperación/ });
    expect(within(card).getByText("Sin guardar")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /Guardar kit|Ver código/ })).not.toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "Verificar código" }));
    const verify = screen.getByRole("dialog", { name: "Verificar código" });
    const input = within(verify).getByLabelText("Código de recuperación");
    fireEvent.change(input, { target: { value: recoveryCode } });
    fireEvent.click(within(verify).getByRole("button", { name: "Verificar" }));
    expect(await within(verify).findByText("Este código es válido para tu nube.")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: recoveryCode.replace("R2KD", "R2KX") } });
    fireEvent.click(within(verify).getByRole("button", { name: "Verificar" }));
    expect(await within(verify).findByText(/Este código no abre tu nube/)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: `AAAA${recoveryCode.slice(4)}` } });
    fireEvent.click(within(verify).getByRole("button", { name: "Verificar" }));
    expect(await within(verify).findByText("Revisa el código: algún carácter no es correcto.")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    fireEvent.click(within(card).getByRole("button", { name: "Generar nuevo código" }));
    const rotate = screen.getByRole("dialog", { name: "¿Generar un nuevo código?" });
    fireEvent.click(within(rotate).getByRole("button", { name: "Generar código" }));
    const kit = await screen.findByRole("dialog", { name: "Guarda tu kit de recuperación" });
    expect(within(kit).getByText("R2KD")).toBeInTheDocument();
    expect(within(kit).getByRole("button", { name: "Imprimir" })).toBeInTheDocument();
    expect(api.callsTo("POST /vault/recovery-code")).toHaveLength(1);
  });

  it("saves the kit as PDF through the desktop bridge", async () => {
    const bridge = installBridge();
    renderSettings("account", { "POST /vault/recovery-code": { recovery_code: recoveryCode } });
    fireEvent.click(await screen.findByRole("button", { name: "Generar nuevo código" }));
    fireEvent.click(screen.getByRole("button", { name: "Generar código" }));
    const kit = await screen.findByRole("dialog", { name: "Guarda tu kit de recuperación" });
    fireEvent.click(within(kit).getByRole("button", { name: "Guardar PDF" }));
    await waitFor(() => expect(bridge.savePageAsPdf).toHaveBeenCalledWith({ suggestedName: "Kit de recuperación de Bento" }));
    expect(await within(kit).findByText("Guardado como «Kit de recuperación de Bento.pdf».")).toBeInTheDocument();
    expect(screen.getByTestId("recovery-kit-sheet")).toHaveTextContent("Kit de recuperación de Bento");
  });
});

describe("Respaldo", () => {
  const source = {
    bytes_pending: 1_610_612_736, enabled: true, error: null, files_done: 30, files_pending: 12, files_total: 42, id: "src_1", label: "Imágenes",
    last_scan_at: null, path: "/home/ana/Imágenes", state: "uploading",
  };
  const policy = { bandwidth_limit_kbps: 0, effective_paused: false, on_battery: false, pause_on_battery: true, paused: false };

  it("lists folders with progress and changes the policy right away", async () => {
    const { api } = renderSettings("backup", {
      "GET /backup/policy": policy,
      "GET /backup/sources": { items: [source] },
      "GET /backup/suggestions": { items: [{ kind: "documents", label: "Documentos", path: "/home/ana/Documentos" }] },
      "PATCH /backup/policy": ({ body }: { body: Record<string, unknown> }) => ({ ...policy, ...body }),
      "PATCH /backup/sources/src_1": { ...source, enabled: false },
      "POST /backup/sources": { ...source, id: "src_2", label: "Documentos", path: "/home/ana/Documentos" },
    });

    expect(await screen.findByText("Subiendo 12 archivos")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Progreso de «Imágenes»" })).toHaveAttribute("aria-valuenow", "71");
    expect(screen.getByText("30 de 42 archivos · faltan 1,5 GB")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Respaldar «Imágenes»" }));
    await waitFor(() => expect(api.callsTo("PATCH /backup/sources/src_1")[0]?.body).toEqual({ enabled: false }));

    fireEvent.click(await screen.findByRole("checkbox", { name: "Pausar respaldo" }));
    await waitFor(() => expect(api.callsTo("PATCH /backup/policy")[0]?.body).toEqual({ paused: true }));
    fireEvent.change(screen.getByRole("combobox", { name: "Velocidad de subida" }), { target: { value: "5000" } });
    await waitFor(() => expect(api.callsTo("PATCH /backup/policy")[1]?.body).toEqual({ bandwidth_limit_kbps: 5000 }));

    fireEvent.click(screen.getByRole("button", { name: "Documentos" }));
    await waitFor(() => expect(api.callsTo("POST /backup/sources")[0]?.body).toEqual({ label: "Documentos", path: "/home/ana/Documentos" }));
  });

  it("adds a typed folder in the browser and explains refusals", async () => {
    const { api } = renderSettings("backup", {
      "GET /backup/policy": policy,
      "GET /backup/sources": { items: [] },
      "GET /backup/suggestions": { items: [] },
      "POST /backup/sources": () => {
        throw new FakeHttpError(400, "backup_source_invalid", { reason: "filesystem_root" });
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Añadir carpeta…" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Ruta de la carpeta" }), { target: { value: "/" } });
    fireEvent.click(screen.getByRole("button", { name: "Añadir" }));
    expect(await screen.findByText("No se puede respaldar la raíz del disco. Elige una carpeta concreta.")).toBeInTheDocument();
    expect(api.callsTo("POST /backup/sources")[0].body).toEqual({ label: "/", path: "/" });
  });

  it("says when backup is paused by the battery", async () => {
    renderSettings("backup", {
      "GET /backup/policy": { ...policy, effective_paused: true, on_battery: true },
      "GET /backup/sources": { items: [] },
      "GET /backup/suggestions": { items: [] },
    });
    expect(await screen.findByText("El respaldo está en pausa porque el equipo está usando la batería.")).toBeInTheDocument();
  });
});

describe("Búsqueda inteligente", () => {
  it("maps two plain switches to the OCR and semantic search providers", () => {
    const state = controller();
    renderSettings("smart-search", {}, state);
    const ocr = screen.getByRole("checkbox", { name: "Texto en imágenes (OCR)" });
    const semantic = screen.getByRole("checkbox", { name: "Búsqueda por significado" });
    expect(ocr).not.toBeChecked();
    expect(semantic).toBeChecked();
    expect(screen.getByText("Activa")).toBeInTheDocument();
    fireEvent.click(ocr);
    expect(state.setValue).toHaveBeenCalledWith("ocr_provider", "rapidocr");
    fireEvent.click(semantic);
    expect(state.setValue).toHaveBeenCalledWith("embeddings_provider", "disabled");
  });

  it("keeps a development provider and saves through the settings bar", () => {
    const state = controller({
      dirty: true,
      draft: { embeddings_provider: "disabled", ocr_provider: "disabled" },
    });
    renderSettings("smart-search", {}, state);
    fireEvent.click(screen.getByRole("checkbox", { name: "Búsqueda por significado" }));
    expect(state.setValue).toHaveBeenCalledWith("embeddings_provider", "mock");
    const bar = screen.getByRole("region", { name: "Acciones para cambios sin guardar" });
    fireEvent.click(within(bar).getByRole("button", { name: /Guardar/ }));
    expect(state.save).toHaveBeenCalledOnce();
  });
});

describe("Avanzado", () => {
  it("groups registry settings, hides secrets and explains locked values", () => {
    renderSettings("advanced");
    expect(screen.getByRole("heading", { name: "Almacenamiento" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rendimiento" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Tareas simultáneas" })).toBeInTheDocument();
    expect(screen.queryByText("Token del bot")).not.toBeInTheDocument();
    expect(screen.getByText("STORAGE_BACKEND")).toBeInTheDocument();
    expect(screen.getByText("Modo navegador o servidor")).toBeInTheDocument();
  });

  it("asks to protect the data folder in file key mode and only offers supported probes", () => {
    const state = controller({ desktop: { arch: "x64", desktop: true, platform: "linux", recoveryMode: false, secureStorage: "file" as never, version: "2.0.0" } });
    renderSettings("advanced", {}, state);
    expect(screen.getByText("Protege esta carpeta")).toBeInTheDocument();
    const probes = screen.getAllByRole("button", { name: "Comprobar ahora" });
    expect(probes).toHaveLength(1);
    fireEvent.click(probes[0]);
    expect(state.probe).toHaveBeenCalledWith("data_dir", "writable_directory");
  });

  it("filters by search", () => {
    renderSettings("advanced");
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar en Ajustes" }), { target: { value: "tareas" } });
    expect(screen.getByRole("spinbutton", { name: "Tareas simultáneas" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Almacenamiento" })).not.toBeInTheDocument();
  });
});

describe("Acerca de", () => {
  it("states the Telegram API notice and the version", () => {
    renderSettings("about");
    expect(screen.getByText("Bento usa la API de Telegram y no está afiliado a Telegram.")).toBeInTheDocument();
    expect(screen.getByText("Versión 0.9.0")).toBeInTheDocument();
    expect(screen.getByText(/Telegram solo ve archivos cifrados/)).toBeInTheDocument();
  });
});
