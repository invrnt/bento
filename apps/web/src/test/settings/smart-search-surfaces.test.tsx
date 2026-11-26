import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { JobRecord } from "../../api/jobs";
import type { SettingDefinition } from "../../api/settings";
import type { SmartSearchStatus } from "../../api/smartSearch";
import { JobsPage } from "../../features/jobs/JobsPage";
import { AdvancedSection } from "../../features/settings/AdvancedSection";
import {
  actionErrorMessage,
  describeSmartSearch,
  formatModelBytes,
  nextAnnouncement,
  suggestInOnboarding,
} from "../../features/settings/smart-search/model";
import type { SettingsController } from "../../features/settings/useSettingsController";

vi.hoisted(() => Object.defineProperty(navigator, "language", { configurable: true, value: "es-ES" }));

const field = (overrides: Partial<SettingDefinition> & Pick<SettingDefinition, "key" | "group" | "type">): SettingDefinition => ({
  apply_mode: "restart_worker", availability: "both", constraints: { choices: [], maximum: null, minimum: null }, default: null, editable: true,
  env_aliases: [overrides.key.toUpperCase()], help_key: `settings.${overrides.key}.help`, label_key: `settings.${overrides.key}.label`, locked: false, probe: null,
  secret: false, source: "saved", ...overrides,
});

const fields: SettingDefinition[] = [
  field({ constraints: { choices: ["disabled", "managed", "custom", "mock"], maximum: null, minimum: null }, group: "ai", key: "embeddings_provider", type: "choice" }),
  field({ group: "ai", key: "custom_model_path", probe: "model_file", type: "path" }),
  field({ group: "ai", key: "custom_mmproj_path", type: "path" }),
  field({ group: "ai", key: "custom_query_prefix", type: "string" }),
  field({ group: "ai", key: "custom_document_prefix", type: "string" }),
  field({ constraints: { choices: ["mean", "last", "cls"], maximum: null, minimum: null }, group: "ai", key: "custom_pooling", type: "choice" }),
  field({ group: "ai", key: "llama_server_path", type: "path" }),
  field({ group: "ai", key: "embedding_server_url", type: "string" }),
  field({ constraints: { choices: [], maximum: 16, minimum: 1 }, group: "ai", key: "embedding_threads", type: "integer" }),
];

function controller(provider: string, overrides: Partial<SettingsController> = {}): SettingsController {
  const values = {
    custom_document_prefix: "", custom_mmproj_path: "", custom_model_path: "", custom_pooling: "mean", custom_query_prefix: "",
    embedding_server_url: "", embedding_threads: 2, embeddings_provider: provider, llama_server_path: "",
  };
  return {
    applyOutcome: null, applyProgress: [], conflict: false, dataMigration: null,
    desktop: { arch: "x64", desktop: true, platform: "linux", recoveryMode: false, secureStorage: "os", version: "2.0.0" },
    dirty: false, discard: vi.fn(), dismissImport: vi.fn(), draft: { ...values }, error: null, exportSafe: vi.fn(), fieldErrors: {}, importPreview: null,
    importPreviewFromFile: vi.fn(), importValues: vi.fn(), isApplying: false, isLoading: false, isReclaiming: false, isValidating: false, pickPath: vi.fn(), probe: vi.fn(),
    publicSettings: { storage_backend: "local" }, reclaim: vi.fn(), reclaimError: null, reclaimResult: null, refresh: vi.fn(), resetGroup: vi.fn(), save: vi.fn(),
    schema: { fields, revision: 1 }, setDataMigration: vi.fn(), setValue: vi.fn(), validate: vi.fn(), validation: null,
    values: {
      revision: 1,
      values: Object.fromEntries(Object.entries(values).map(([key, value]) => [key, { apply_mode: "restart_worker" as const, locked: false, source: "saved" as const, value }])),
    },
    ...overrides,
  };
}

const status = (overrides: Partial<SmartSearchStatus> = {}): SmartSearchStatus => ({
  download: { bytes_done: 0, bytes_total: 2000 }, error_code: null, failed_step: null, free_bytes: null, indexing: { done: 0, total: 0 }, locked: false, model: null,
  search_available: false, space_id: null, state: "downloading", update_available: null, waiting_network: false, ...overrides,
});

afterEach(() => {
  cleanup();
});

describe("Avanzado › Modelo propio", () => {
  it("groups the custom model settings with their own copy and GGUF file pickers", () => {
    const state = controller("custom");
    render(<AdvancedSection controller={state} />);

    const group = screen.getByRole("group", { name: "Modelo propio" });
    expect(within(group).getByText(/Para usar un modelo GGUF tuyo en lugar del que descarga Bento/)).toBeInTheDocument();
    for (const label of ["Archivo del modelo (GGUF)", "Archivo para imágenes (mmproj)", "Prefijo de las búsquedas", "Prefijo de los documentos"]) {
      expect(within(group).getByRole("textbox", { name: label })).toBeInTheDocument();
    }
    expect(within(group).getByRole("combobox", { name: "Agrupación (pooling)" })).toHaveValue("mean");
    expect(within(group).queryByRole("textbox", { name: "Programa llama-server" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Programa llama-server" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Núcleos para la búsqueda por significado" })).toBeInTheDocument();

    // Both model files open the GGUF file dialog; llama-server is typed, never picked as a folder.
    const pickers = within(group).getAllByRole("button", { name: "Elegir ruta" });
    expect(pickers).toHaveLength(2);
    fireEvent.click(pickers[0]);
    expect(state.pickPath).toHaveBeenCalledWith("custom_model_path", true);
    expect(screen.getAllByRole("button", { name: "Elegir ruta" })).toHaveLength(2);
  });

  it("never offers the managed provider in the form unless it is already on", () => {
    render(<AdvancedSection controller={controller("disabled")} />);
    let provider = screen.getByRole("combobox", { name: "Búsqueda semántica" });
    expect(within(provider).getAllByRole("option").map((option) => option.textContent)).toEqual(["Apagada", "Modelo propio", "Simulada"]);
    cleanup();

    render(<AdvancedSection controller={controller("managed")} />);
    provider = screen.getByRole("combobox", { name: "Búsqueda semántica" });
    expect(within(provider).getAllByRole("option").map((option) => option.textContent)).toEqual(["Apagada", "Gestionada por Bento", "Modelo propio", "Simulada"]);
    expect(provider).toHaveValue("managed");
  });

  it("finds the custom model settings by their own labels", () => {
    render(<AdvancedSection controller={controller("custom")} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar en Ajustes" }), { target: { value: "pooling" } });
    expect(screen.getByRole("combobox", { name: "Agrupación (pooling)" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Programa llama-server" })).not.toBeInTheDocument();
  });
});

describe("Trabajos", () => {
  it("labels the model download and re-embedding jobs", () => {
    const job = (id: string, type: string): JobRecord => ({
      attempts: 0, created_at: "2026-11-26T10:00:00Z", id, max_attempts: 3, priority: 1, status: "running", type: type as JobRecord["type"], updated_at: "2026-11-26T10:01:00Z",
    });
    render(<JobsPage jobs={[job("job-1", "model_download"), job("job-2", "reembed")]} onReindex={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByText("Descarga del modelo")).toBeInTheDocument();
    expect(screen.getByText("Revisión por significado")).toBeInTheDocument();
  });
});

describe("smart search model helpers", () => {
  it("states model sizes in decimal units like the model card", () => {
    expect(formatModelBytes(309_855_456)).toBe("310 MB");
    expect(formatModelBytes(52_000_000)).toBe("52 MB");
    expect(formatModelBytes(52_613_349_376)).toBe("52,6 GB");
    expect(formatModelBytes(0)).toBe("0 B");
    expect(formatModelBytes(null)).toBe("");
  });

  it("announces the first change, each state change and each new tenth of progress", () => {
    const first = nextAnnouncement(null, status({ download: { bytes_done: 10, bytes_total: 2000 } }));
    expect(first).toMatchObject({ bucket: 0, message: "" });
    expect(nextAnnouncement(first, status({ download: { bytes_done: 190, bytes_total: 2000 } }))).toBeNull();
    const tenth = nextAnnouncement(first, status({ download: { bytes_done: 200, bytes_total: 2000 } }));
    expect(tenth?.message).toBe("Descargando… 200 B de 2 KB, 10%");
    expect(nextAnnouncement(tenth, status({ download: { bytes_done: 390, bytes_total: 2000 } }))).toBeNull();
    const offline = nextAnnouncement(tenth, status({ download: { bytes_done: 390, bytes_total: 2000 }, waiting_network: true }));
    expect(offline?.message).toBe("Esperando conexión · se reanudará sola, 19%");
    const failed = nextAnnouncement(offline, status({ error_code: "checksum", failed_step: "downloading", state: "error" }));
    expect(failed?.message).toBe("El archivo descargado no es correcto y se borró.");
    expect(nextAnnouncement(failed, null)).toBeNull();
  });

  it("describes every state", () => {
    expect(describeSmartSearch(status({ state: "off" })).text).toBe("Apagada");
    expect(describeSmartSearch(status({ state: "ready" })).badge).toMatchObject({ label: "Lista", tone: "success" });
    expect(describeSmartSearch(status({ state: "verifying" }))).toMatchObject({ indeterminate: true, progress: null });
    expect(describeSmartSearch(status({ indexing: { done: 5, total: 20 }, state: "indexing" })).progress).toEqual({ kind: "indexing", percent: 25 });
    expect(describeSmartSearch(status({ error_code: "runtime", failed_step: "starting", state: "error" })).text).toBe("El motor de búsqueda no pudo iniciar en este equipo.");
  });

  it("maps refusals to clear messages", () => {
    const refusal = (code: string, details: Record<string, unknown> = {}) => new ApiError("Conflict", 409, { error: { code, details, message: code } });
    expect(actionErrorMessage(refusal("smart_search_state_conflict", { event: "pause", state: "paused" }))).toBe("El estado cambió mientras tanto. Ya ves el actual.");
    expect(actionErrorMessage(refusal("settings_source_locked"))).toBe("Esta opción la controla la configuración de este equipo.");
    expect(actionErrorMessage(refusal("smart_search_no_space", { free_bytes: 100_000_000, required_bytes: 340_841_002 }))).toBe("Necesitas 341 MB libres. Ahora tienes 100 MB.");
    expect(actionErrorMessage(refusal("smart_search_no_space"))).toBe("No hay espacio suficiente en este equipo.");
    expect(actionErrorMessage(new ApiError("Bad Request", 400, { error: { code: "invalid_model_spec", message: "" } }))).toBe("No se pudo completar la acción. Inténtalo otra vez.");
  });

  it("suggests smart search in onboarding only on known capable machines", () => {
    const gib = 1024 ** 3;
    expect(suggestInOnboarding({ cores: 4, ramBytes: 8 * gib })).toBe(true);
    expect(suggestInOnboarding({ cores: 3, ramBytes: 16 * gib })).toBe(false);
    expect(suggestInOnboarding({ cores: 8, ramBytes: 4 * gib })).toBe(false);
    expect(suggestInOnboarding({ cores: 8, ramBytes: null })).toBe(false);
    expect(suggestInOnboarding({ cores: null, ramBytes: 8 * gib })).toBe(false);
  });
});
