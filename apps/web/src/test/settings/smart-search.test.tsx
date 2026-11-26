import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SettingDefinition } from "../../api/settings";
import type { SmartSearchErrorCode, SmartSearchState, SmartSearchStatus } from "../../api/smartSearch";
import { SmartSearchSection } from "../../features/settings/SmartSearchSection";
import type { SettingsController } from "../../features/settings/useSettingsController";
import { FakeHttpError, fakeApi } from "../core/testkit";
import type { Route } from "../core/testkit";

// The dictionary picks the locale at import time and jsdom reports en-US: pin Spanish first.
vi.hoisted(() => Object.defineProperty(navigator, "language", { configurable: true, value: "es-ES" }));

const model = {
  dims: 512,
  display_name: "EmbeddingGemma 2",
  download_host: "huggingface.co",
  license_spdx: "Apache-2.0",
  license_url: "/api/smart-search/license",
  model_id: "embeddinggemma-2-q8_0",
  size_bytes: 309_855_456,
};
const spaceId = "embeddinggemma-2-q8_0@6ea3e3a309d12a4779cfda98b8c19800d2d5da71/512";

const statusOf = (overrides: Partial<SmartSearchStatus> = {}): SmartSearchStatus => ({
  can_use_now: false,
  download: { bytes_done: 0, bytes_total: 0 },
  error_code: null,
  failed_step: null,
  free_bytes: 52_613_349_376,
  indexing: { done: 0, total: 0 },
  locked: false,
  model,
  search_available: false,
  space_id: null,
  state: "off",
  suggest_in_onboarding: false,
  update_available: null,
  waiting_network: false,
  ...overrides,
});
const downloading = (bytesDone = 0, overrides: Partial<SmartSearchStatus> = {}) =>
  statusOf({ download: { bytes_done: bytesDone, bytes_total: model.size_bytes }, space_id: spaceId, state: "downloading", ...overrides });
const ready = (overrides: Partial<SmartSearchStatus> = {}) =>
  statusOf({ download: { bytes_done: model.size_bytes, bytes_total: model.size_bytes }, search_available: true, space_id: spaceId, state: "ready", ...overrides });

const ocrField: SettingDefinition = {
  apply_mode: "restart_worker", availability: "both", constraints: { choices: ["disabled", "mock", "rapidocr"], maximum: null, minimum: null }, default: "disabled",
  editable: true, env_aliases: ["OCR_PROVIDER"], group: "ai", help_key: "settings.ocr_provider.help", key: "ocr_provider", label_key: "settings.ocr_provider.label",
  locked: false, probe: null, secret: false, source: "saved", type: "choice",
};

function controller(overrides: Partial<SettingsController> = {}): SettingsController {
  return {
    applyOutcome: null, applyProgress: [], conflict: false, dataMigration: null, desktop: null, dirty: false, discard: vi.fn(), dismissImport: vi.fn(),
    draft: { embeddings_provider: "disabled", ocr_provider: "disabled" }, error: null, exportSafe: vi.fn(), fieldErrors: {}, importPreview: null,
    importPreviewFromFile: vi.fn(), importValues: vi.fn(), isApplying: false, isLoading: false, isReclaiming: false, isValidating: false, pickPath: vi.fn(), probe: vi.fn(),
    publicSettings: { embeddings_state: "disabled", ocr_state: "disabled", storage_backend: "telegram" }, reclaim: vi.fn(), reclaimError: null, reclaimResult: null,
    refresh: vi.fn(), resetGroup: vi.fn(), save: vi.fn(), schema: { fields: [ocrField], revision: 3 }, setDataMigration: vi.fn(), setValue: vi.fn(), validate: vi.fn(),
    validation: null,
    values: {
      revision: 3,
      values: {
        embeddings_provider: { apply_mode: "restart_services", locked: false, source: "saved", value: "disabled" },
        ocr_provider: { apply_mode: "restart_worker", locked: false, source: "saved", value: "disabled" },
      },
    },
    ...overrides,
  };
}

/** A fake `/api/smart-search` that follows the contract's state machine for the happy paths. */
function smartSearchServer(initial: SmartSearchStatus, routes: Record<string, Route> = {}) {
  let current = initial;
  const set = (next: SmartSearchStatus) => {
    current = next;
    return current;
  };
  const api = fakeApi({
    "DELETE /smart-search/model": () => set(statusOf()),
    "GET /smart-search": () => current,
    "POST /smart-search/activate": () => set(downloading(0)),
    "POST /smart-search/cancel": () => set(statusOf()),
    "POST /smart-search/pause": () => set({ ...current, state: "paused", waiting_network: false }),
    "POST /smart-search/resume": () => set({ ...current, state: "downloading" }),
    "POST /smart-search/retry": () => {
      const step = current.failed_step ?? "downloading";
      const download = current.error_code === "checksum" ? { ...current.download, bytes_done: 0 } : current.download;
      return set({ ...current, download, error_code: null, failed_step: null, state: step });
    },
    "POST /smart-search/update": () =>
      set({ ...current, update: { progress: { bytes_done: 0, bytes_total: current.update_available?.size_bytes ?? 0, state: "downloading" } } }),
    ...routes,
  });
  return { api, current: () => current, set };
}

type RenderOptions = { idlePollIntervalMs?: number | null; pollIntervalMs?: number; state?: SettingsController };

function renderSection(initial: SmartSearchStatus, routes: Record<string, Route> = {}, options: RenderOptions = {}) {
  const server = smartSearchServer(initial, routes);
  const state = options.state ?? controller();
  render(
    <SmartSearchSection
      client={server.api.client}
      controller={state}
      idlePollIntervalMs={options.idlePollIntervalMs ?? null}
      pollIntervalMs={options.pollIntervalMs ?? 60_000}
    />,
  );
  return { ...server, state };
}

async function semanticSwitch() {
  const control = await screen.findByRole("checkbox", { name: "Buscar por significado" });
  await waitFor(() => expect(control).toBeEnabled());
  return control;
}

/** Keyboard activation of a focused native control: it must be reachable, then Space/Enter dispatches a click. */
function pressWithKeyboard(element: HTMLElement) {
  element.focus();
  expect(element).toHaveFocus();
  fireEvent.click(element);
}

afterEach(() => {
  cleanup();
});

describe("Búsqueda inteligente › Buscar por significado", () => {
  it("shows the size, host, license and use policy before anything downloads", async () => {
    const { api, state } = renderSection(statusOf());
    const control = await semanticSwitch();
    expect(control).not.toBeChecked();
    expect(screen.getByText(/Encuentra cosas aunque no recuerdes las palabras exactas, como «cumpleaños en la playa»/)).toBeInTheDocument();

    fireEvent.click(control);
    const sheet = screen.getByRole("dialog", { name: "Activar la búsqueda por significado" });
    expect(within(sheet).getByText(/Bento descargará un modelo de 296 MB desde huggingface\.co y lo guardará en este equipo\./)).toBeInTheDocument();
    expect(within(sheet).getByText(/Tus archivos no salen de este equipo\./)).toBeInTheDocument();
    expect(within(sheet).getByText("Modelo: EmbeddingGemma 2 · Licencia Apache-2.0")).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "Leer la licencia" })).toHaveAttribute("href", "/api/smart-search/license");
    expect(within(sheet).getByRole("link", { name: "Política de uso del modelo" })).toHaveAttribute("href", "https://ai.google.dev/gemma/prohibited_use_policy");
    expect(within(sheet).getByRole("button", { name: "Descargar y activar" })).toBeEnabled();
    expect(control).not.toBeChecked();

    fireEvent.click(within(sheet).getByRole("button", { name: "Ahora no" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/activate")).toHaveLength(0);
    // The managed capability is never saved through the settings form.
    expect(state.setValue).not.toHaveBeenCalledWith("embeddings_provider", expect.anything());
  });

  it("turns on, pauses and resumes with the keyboard only", async () => {
    const { api } = renderSection(statusOf());
    const control = await semanticSwitch();

    pressWithKeyboard(control);
    const sheet = screen.getByRole("dialog", { name: "Activar la búsqueda por significado" });
    expect(sheet).toContainElement(document.activeElement as HTMLElement);
    pressWithKeyboard(within(sheet).getByRole("button", { name: "Descargar y activar" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(control).toHaveFocus();
    expect(control).toBeChecked();
    expect(api.callsTo("POST /smart-search/activate")).toEqual([{ body: {}, method: "POST", path: "/smart-search/activate" }]);
    expect(screen.getByText("Descargando… 0 B de 296 MB")).toBeInTheDocument();

    pressWithKeyboard(screen.getByRole("button", { name: "Pausar" }));
    const resume = await screen.findByRole("button", { name: "Reanudar" });
    expect(resume).toHaveFocus();
    expect(screen.getByText("En pausa · 0 B de 296 MB")).toBeInTheDocument();

    pressWithKeyboard(resume);
    const pause = await screen.findByRole("button", { name: "Pausar" });
    expect(pause).toHaveFocus();
    expect(api.callsTo("POST /smart-search/pause")).toHaveLength(1);
    expect(api.callsTo("POST /smart-search/resume")).toHaveLength(1);
  });

  it("exposes the download as a progressbar with a text equivalent", async () => {
    renderSection(downloading(104_857_600));
    const bar = await screen.findByRole("progressbar", { name: "Progreso de la descarga" });
    expect(bar).toHaveAttribute("aria-valuenow", "33");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(screen.getByText("Descargando… 100 MB de 296 MB")).toBeInTheDocument();
    expect(screen.getByText("33%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pausar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
  });

  it("exposes indexing progress with counts", async () => {
    renderSection(statusOf({ indexing: { done: 1240, total: 3000 }, search_available: true, space_id: spaceId, state: "indexing" }));
    const bar = await screen.findByRole("progressbar", { name: "Progreso de la revisión" });
    expect(bar).toHaveAttribute("aria-valuenow", "41");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(screen.getByText("Revisando tus archivos · 1.240 de 3.000")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quitar el modelo y liberar 296 MB" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
  });

  it.each<[string, SmartSearchStatus, string, string[]]>([
    ["waiting for the network", downloading(52_000_000, { waiting_network: true }), "Esperando conexión · se reanudará sola", ["Pausar", "Cancelar"]],
    ["paused", downloading(52_000_000, { state: "paused" }), "En pausa · 49,6 MB de 296 MB", ["Reanudar", "Cancelar"]],
    ["verifying", downloading(model.size_bytes, { state: "verifying" }), "Comprobando el archivo…", ["Cancelar"]],
    ["starting", downloading(model.size_bytes, { state: "starting" }), "Preparando…", ["Cancelar"]],
    ["indexing before the backlog is counted", statusOf({ space_id: spaceId, state: "indexing" }), "Revisando tus archivos…", ["Quitar el modelo y liberar 296 MB"]],
  ])("shows %s with its actions", async (_name, status, text, buttons) => {
    renderSection(status);
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(await semanticSwitch()).toBeChecked();
    for (const name of buttons) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    expect(screen.getAllByRole("button").filter((button) => !button.closest("[role=dialog]"))).toHaveLength(buttons.length);
  });

  it("shows the ready state with the installed model and an update when one exists", async () => {
    const { api } = renderSection(ready({ update_available: { revision: "abc123", size_bytes: 320_000_000 } }));
    expect(await screen.findByText("Lista")).toBeInTheDocument();
    expect(screen.getByText("EmbeddingGemma 2 · 296 MB en este equipo")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText("Hay una versión nueva del modelo (305 MB)")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
    // The installed model keeps serving search: the status stays ready, with a secondary progress line.
    expect(await screen.findByText("Descargando la versión nueva… 0 B de 305 MB")).toBeInTheDocument();
    expect(screen.getByText("Lista")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Progreso de la actualización" })).toHaveAttribute("aria-valuenow", "0");
    expect(screen.queryByRole("button", { name: "Actualizar" })).not.toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/update")).toHaveLength(1);
  });

  it("shows a running update under the ready state", async () => {
    renderSection(
      ready({ update_available: { progress: { bytes_done: 160_000_000, bytes_total: 320_000_000, state: "downloading" }, revision: "abc123", size_bytes: 320_000_000 } }),
    );
    expect(await screen.findByText("Descargando la versión nueva… 153 MB de 305 MB")).toBeInTheDocument();
    expect(screen.getByText("Lista")).toBeInTheDocument();
    const line = screen.getByTestId("smart-search-update-progress");
    expect(within(line).getByText("50%")).toBeInTheDocument();
    expect(within(line).getByRole("progressbar", { name: "Progreso de la actualización" })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.queryByRole("button", { name: "Actualizar" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quitar el modelo y liberar 296 MB" })).toBeInTheDocument();
    cleanup();

    renderSection(ready({ update: { progress: { bytes_done: 320_000_000, bytes_total: 320_000_000, state: "downloading" } } }));
    expect(await screen.findByText("Comprobando la versión nueva…")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("offers «Usar ya» during a re-embed and asks before switching", async () => {
    const reembedding = statusOf({ can_use_now: true, indexing: { done: 400, total: 1000 }, search_available: true, space_id: spaceId, state: "indexing" });
    const { api, set } = renderSection(reembedding, { "POST /smart-search/use-now": () => set(ready()) });
    const control = await semanticSwitch();
    expect(screen.getByText("El modelo nuevo está revisando tus archivos. Mientras tanto, la búsqueda sigue usando el anterior.")).toBeInTheDocument();
    const useNow = screen.getByRole("button", { name: "Usar ya" });

    pressWithKeyboard(useNow);
    let dialog = screen.getByRole("dialog", { name: "¿Usar ya el modelo nuevo?" });
    expect(within(dialog).getByText(/Verás los resultados del modelo nuevo desde ahora, pero por un tiempo encontrará menos archivos/)).toBeInTheDocument();
    const keep = within(dialog).getByRole("button", { name: "Esperar a que termine" });
    expect(keep).toHaveFocus();
    fireEvent.click(keep);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(useNow).toHaveFocus();
    expect(api.callsTo("POST /smart-search/use-now")).toHaveLength(0);

    pressWithKeyboard(useNow);
    dialog = screen.getByRole("dialog", { name: "¿Usar ya el modelo nuevo?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Usar ya" }));
    expect(await screen.findByText("Lista")).toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/use-now")).toEqual([{ body: undefined, method: "POST", path: "/smart-search/use-now" }]);
    expect(screen.queryByRole("button", { name: "Usar ya" })).not.toBeInTheDocument();
    await waitFor(() => expect(control).toHaveFocus());
  });

  it("re-reads the status when «Usar ya» is refused", async () => {
    const { api, set } = renderSection(statusOf({ can_use_now: true, search_available: true, space_id: spaceId, state: "indexing" }), {
      "POST /smart-search/use-now": () => {
        set(ready());
        throw new FakeHttpError(409, "smart_search_state_conflict", { event: "use_now", state: "ready" });
      },
    });
    await semanticSwitch();
    fireEvent.click(screen.getByRole("button", { name: "Usar ya" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "¿Usar ya el modelo nuevo?" })).getByRole("button", { name: "Usar ya" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El estado cambió mientras tanto. Ya ves el actual.");
    expect(await screen.findByText("Lista")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usar ya" })).not.toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/use-now")).toHaveLength(1);
  });

  it("announces state changes politely, and progress at most every 10 %", async () => {
    const total = 2000;
    const at = (done: number, state: SmartSearchState = "downloading") => statusOf({ download: { bytes_done: done, bytes_total: total }, space_id: spaceId, state });
    const { api, set } = renderSection(at(0), {}, { idlePollIntervalMs: 10, pollIntervalMs: 10 });
    const announcer = screen.getByTestId("smart-search-announcer");
    expect(announcer).toHaveAttribute("role", "status");
    expect(announcer).toHaveAttribute("aria-live", "polite");

    await screen.findByText("Descargando… 0 B de 2 KB");
    expect(announcer).toBeEmptyDOMElement();

    set(at(100));
    await screen.findByText("Descargando… 100 B de 2 KB");
    expect(announcer).toBeEmptyDOMElement();

    set(at(240));
    await waitFor(() => expect(announcer).toHaveTextContent("Descargando… 240 B de 2 KB, 12%"));

    set(at(300));
    await screen.findByText("Descargando… 300 B de 2 KB");
    const polls = api.callsTo("GET /smart-search").length;
    await waitFor(() => expect(api.callsTo("GET /smart-search").length).toBeGreaterThan(polls + 2));
    expect(announcer).toHaveTextContent("Descargando… 240 B de 2 KB, 12%");

    set(at(300, "paused"));
    await waitFor(() => expect(announcer).toHaveTextContent("En pausa · 300 B de 2 KB, 15%"));

    set(at(total, "verifying"));
    await waitFor(() => expect(announcer).toHaveTextContent("Comprobando el archivo…"));
  });

  it("asks before removing the model and returns focus", async () => {
    const { api } = renderSection(ready());
    const control = await semanticSwitch();
    const remove = screen.getByRole("button", { name: "Quitar el modelo y liberar 296 MB" });

    pressWithKeyboard(remove);
    let dialog = screen.getByRole("dialog", { name: "Quitar el modelo y liberar 296 MB" });
    expect(within(dialog).getByText("La búsqueda por nombre, fecha y texto seguirá funcionando. Puedes volver a activarla cuando quieras.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Conservar" })).toHaveFocus();
    fireEvent.click(within(dialog).getByRole("button", { name: "Conservar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(remove).toHaveFocus();
    expect(api.callsTo("DELETE /smart-search/model")).toHaveLength(0);

    pressWithKeyboard(remove);
    dialog = screen.getByRole("dialog", { name: "Quitar el modelo y liberar 296 MB" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Quitar el modelo" }));

    await waitFor(() => expect(control).not.toBeChecked());
    await waitFor(() => expect(control).toHaveFocus());
    expect(api.callsTo("DELETE /smart-search/model")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Quitar el modelo/ })).not.toBeInTheDocument();
  });

  it("asks before removing when the switch is turned off on a ready model", async () => {
    const { api } = renderSection(ready());
    const control = await semanticSwitch();
    pressWithKeyboard(control);
    const dialog = screen.getByRole("dialog", { name: "Quitar el modelo y liberar 296 MB" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Conservar" }));
    expect(control).toHaveFocus();
    expect(control).toBeChecked();
    expect(api.callsTo("DELETE /smart-search/model")).toHaveLength(0);
  });

  it("cancels a download when the switch is turned off, keeping focus on it", async () => {
    const { api } = renderSection(downloading(52_000_000));
    const control = await semanticSwitch();
    pressWithKeyboard(control);
    await waitFor(() => expect(control).not.toBeChecked());
    expect(control).toHaveFocus();
    expect(api.callsTo("POST /smart-search/cancel")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Pausar" })).not.toBeInTheDocument();
  });

  it("moves focus to the switch when Cancelar removes its own button", async () => {
    const { api } = renderSection(downloading(52_000_000, { state: "paused" }));
    const control = await semanticSwitch();
    pressWithKeyboard(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(control).not.toBeChecked());
    await waitFor(() => expect(control).toHaveFocus());
    expect(api.callsTo("POST /smart-search/cancel")).toHaveLength(1);
  });

  it.each<[SmartSearchErrorCode, SmartSearchState, string, string]>([
    ["download", "downloading", "No se pudo descargar el modelo.", "Descargando… 49,6 MB de 296 MB"],
    ["checksum", "downloading", "El archivo descargado no es correcto y se borró.", "Descargando… 0 B de 296 MB"],
    ["space", "downloading", "No hay espacio suficiente en este equipo.", "Descargando… 49,6 MB de 296 MB"],
    ["runtime", "starting", "El motor de búsqueda no pudo iniciar en este equipo.", "Preparando…"],
  ])("explains a %s error and retries the step that failed", async (code, failedStep, message, after) => {
    const { api } = renderSection(downloading(52_000_000, { error_code: code, failed_step: failedStep, state: "error" }));
    const control = await semanticSwitch();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(screen.getByText("Con problemas")).toBeInTheDocument();
    expect(control).toBeChecked();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument();

    pressWithKeyboard(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText(after)).toBeInTheDocument();
    expect(screen.queryByText(message)).not.toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/retry")).toHaveLength(1);
    // The retry button turns into "Pausar" in place; when no action is left, focus falls back to the switch.
    if (failedStep === "downloading") expect(screen.getByRole("button", { name: "Pausar" })).toHaveFocus();
    else await waitFor(() => expect(control).toHaveFocus());
  });

  it("shows the space check in the sheet and keeps the download from starting", async () => {
    const { api } = renderSection(statusOf({ free_bytes: 200_000_000 }));
    fireEvent.click(await semanticSwitch());
    const sheet = screen.getByRole("dialog", { name: "Activar la búsqueda por significado" });
    expect(within(sheet).getByRole("alert")).toHaveTextContent("Necesitas 325 MB libres. Ahora tienes 191 MB.");
    expect(within(sheet).getByRole("button", { name: "Descargar y activar" })).toBeDisabled();
    expect(api.callsTo("POST /smart-search/activate")).toHaveLength(0);
  });

  it("explains a refused activation inside the sheet", async () => {
    const { api } = renderSection(statusOf({ free_bytes: null }), {
      "POST /smart-search/activate": () => {
        throw new FakeHttpError(409, "smart_search_no_space", { free_bytes: 300_000_000, required_bytes: 340_841_002 });
      },
    });
    fireEvent.click(await semanticSwitch());
    const sheet = screen.getByRole("dialog", { name: "Activar la búsqueda por significado" });
    fireEvent.click(within(sheet).getByRole("button", { name: "Descargar y activar" }));
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("Necesitas 325 MB libres. Ahora tienes 286 MB.");
    expect(screen.getByRole("dialog", { name: "Activar la búsqueda por significado" })).toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/activate")).toHaveLength(1);
  });

  it("re-reads the status after a state conflict", async () => {
    const { api, set } = renderSection(downloading(52_000_000), {
      "POST /smart-search/pause": () => {
        set(downloading(52_000_000, { state: "paused" }));
        throw new FakeHttpError(409, "smart_search_state_conflict", { event: "pause", state: "paused" });
      },
    });
    await semanticSwitch();
    fireEvent.click(screen.getByRole("button", { name: "Pausar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El estado cambió mientras tanto. Ya ves el actual.");
    expect(await screen.findByRole("button", { name: "Reanudar" })).toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/pause")).toHaveLength(1);
  });

  it("shows a read-only switch without actions when an environment variable controls it", async () => {
    const { api } = renderSection(ready({ can_use_now: true, locked: true }));
    const control = await screen.findByRole("checkbox", { name: "Buscar por significado" });
    await screen.findByText("Lista");
    expect(control).toBeDisabled();
    expect(control).toBeChecked();
    expect(screen.getByText("Esta opción la controla la configuración de este equipo.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Quitar el modelo/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usar ya" })).not.toBeInTheDocument();
    fireEvent.click(control);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.callsTo("DELETE /smart-search/model")).toHaveLength(0);
  });

  it("keeps a locked, off switch closed and explains an env lock refusal", async () => {
    renderSection(statusOf({ locked: true }));
    const control = await screen.findByRole("checkbox", { name: "Buscar por significado" });
    await waitFor(() => expect(screen.getByText("Esta opción la controla la configuración de este equipo.")).toBeInTheDocument());
    expect(control).toBeDisabled();
    fireEvent.click(control);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    cleanup();

    renderSection(statusOf(), {
      "POST /smart-search/activate": () => {
        throw new FakeHttpError(409, "settings_source_locked");
      },
    });
    fireEvent.click(await semanticSwitch());
    const sheet = screen.getByRole("dialog", { name: "Activar la búsqueda por significado" });
    fireEvent.click(within(sheet).getByRole("button", { name: "Descargar y activar" }));
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("Esta opción la controla la configuración de este equipo.");
  });

  it("offers to try again when the status cannot be read", async () => {
    let fail = true;
    renderSection(statusOf(), {
      "GET /smart-search": () => {
        if (fail) throw new FakeHttpError(500, "server_error");
        return statusOf();
      },
    });
    expect(await screen.findByText("No se pudo consultar la búsqueda por significado.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Buscar por significado" })).toBeDisabled();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await semanticSwitch();
    expect(screen.queryByText("No se pudo consultar la búsqueda por significado.")).not.toBeInTheDocument();
  });

  it("keeps OCR as a plain switch saved with the settings bar", async () => {
    const { state } = renderSection(statusOf());
    await semanticSwitch();
    fireEvent.click(screen.getByRole("checkbox", { name: "Texto en imágenes (OCR)" }));
    expect(state.setValue).toHaveBeenCalledWith("ocr_provider", "rapidocr");
  });
});
