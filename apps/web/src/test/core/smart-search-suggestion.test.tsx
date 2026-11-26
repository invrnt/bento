import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SmartSearchStatus } from "../../api/smartSearch";
import { SmartSearchSuggestion } from "../../features/onboarding/SmartSearchSuggestion";
import { fakeApi } from "./testkit";

vi.hoisted(() => Object.defineProperty(navigator, "language", { configurable: true, value: "es-ES" }));

const offer = {
  dims: 512, display_name: "EmbeddingGemma 2", download_host: "huggingface.co", license_spdx: "Apache-2.0", license_url: "/api/smart-search/license",
  model_id: "embeddinggemma-2-q8_0", size_bytes: 309_855_456,
};
const statusOf = (overrides: Partial<SmartSearchStatus> = {}): SmartSearchStatus => ({
  can_use_now: false, download: { bytes_done: 0, bytes_total: 0 }, error_code: null, failed_step: null, free_bytes: 52_613_349_376, indexing: { done: 0, total: 0 }, locked: false,
  model: offer, search_available: false, space_id: null, state: "off", suggest_in_onboarding: true, update_available: null,
  waiting_network: false, ...overrides,
});

function setup(status: SmartSearchStatus = statusOf()) {
  const api = fakeApi({
    "GET /smart-search": () => status,
    "POST /smart-search/activate": () => statusOf({ download: { bytes_done: 0, bytes_total: offer.size_bytes }, state: "downloading" }),
  });
  render(<SmartSearchSuggestion client={api.client} />);
  return api;
}

afterEach(() => {
  cleanup();
  for (const key of ["deviceMemory", "hardwareConcurrency"]) Reflect.deleteProperty(navigator, key);
});

describe("onboarding smart search suggestion (D8)", () => {
  it("suggests it when the API says this machine qualifies and downloads nothing without consent", async () => {
    const api = setup();
    expect(await screen.findByRole("heading", { name: "¿Quieres buscar por significado?" })).toBeInTheDocument();
    expect(screen.getByText(/Nada se descarga hasta que lo confirmes\./)).toBeInTheDocument();

    const details = screen.getByRole("button", { name: "Ver detalles" });
    details.focus();
    fireEvent.click(details);
    let sheet = screen.getByRole("dialog", { name: "Activar la búsqueda por significado" });
    expect(within(sheet).getByText(/un modelo de 296 MB desde huggingface\.co/)).toBeInTheDocument();
    expect(within(sheet).getByText("Modelo: EmbeddingGemma 2 · Licencia Apache-2.0")).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "Política de uso del modelo" })).toBeInTheDocument();

    fireEvent.click(within(sheet).getByRole("button", { name: "Ahora no" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(details).toHaveFocus();
    expect(api.callsTo("POST /smart-search/activate")).toHaveLength(0);

    fireEvent.click(details);
    sheet = screen.getByRole("dialog", { name: "Activar la búsqueda por significado" });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/activate")).toHaveLength(0);

    fireEvent.click(details);
    sheet = screen.getByRole("dialog", { name: "Activar la búsqueda por significado" });
    fireEvent.click(within(sheet).getByRole("button", { name: "Descargar y activar" }));

    const started = await screen.findByText("La descarga sigue en segundo plano. Puedes verla en Ajustes › Búsqueda inteligente.");
    await waitFor(() => expect(started.closest("[role=status]")).toHaveFocus());
    expect(api.callsTo("POST /smart-search/activate")).toEqual([{ body: {}, method: "POST", path: "/smart-search/activate" }]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("hides the suggestion when the person says not now", async () => {
    const api = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Ahora no" }));
    expect(screen.queryByRole("heading", { name: "¿Quieres buscar por significado?" })).not.toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/activate")).toHaveLength(0);
  });

  it("follows the API, not the browser's hardware hints", async () => {
    // Firefox and Safari have no `deviceMemory`; Chromium caps it. Neither decides here.
    Object.defineProperty(navigator, "deviceMemory", { configurable: true, value: 2 });
    Object.defineProperty(navigator, "hardwareConcurrency", { configurable: true, value: 2 });
    setup();
    expect(await screen.findByRole("heading", { name: "¿Quieres buscar por significado?" })).toBeInTheDocument();
  });

  it.each<[string, SmartSearchStatus]>([
    ["the API says this machine does not qualify", statusOf({ suggest_in_onboarding: false })],
    ["already on", statusOf({ search_available: true, state: "ready" })],
    ["controlled by the environment", statusOf({ locked: true })],
    ["without a model for this platform", statusOf({ model: null })],
  ])("does not suggest it when %s", async (_name, status) => {
    const api = setup(status);
    await waitFor(() => expect(api.callsTo("GET /smart-search")).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("heading", { name: "¿Quieres buscar por significado?" })).not.toBeInTheDocument();
    expect(api.callsTo("POST /smart-search/activate")).toHaveLength(0);
  });
});
