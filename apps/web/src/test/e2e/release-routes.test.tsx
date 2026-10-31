import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";

describe("release route smoke", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it.each([
    { heading: "Drive", path: "/drive" },
    { heading: "Fotos", path: "/photos" },
    { heading: "Búsqueda", path: "/search?q=factura" },
    { heading: "Trabajos", path: "/jobs" },
    { heading: "Ajustes", path: "/settings" },
  ])("renders $heading at $path", async ({ heading, path }) => {
    stubApi();
    window.history.pushState({}, "", path);

    render(<App />);

    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("keeps upload entrypoints visible in Drive and Photos", async () => {
    stubApi();
    window.history.pushState({}, "", "/drive");
    const { rerender } = render(<App />);

    expect(await screen.findByRole("button", { name: "Subir archivos" })).toBeInTheDocument();

    window.history.pushState({}, "", "/photos");
    window.dispatchEvent(new Event("popstate"));
    rerender(<App />);

    expect(await screen.findByRole("button", { name: "Subir fotos" })).toBeInTheDocument();
  });
});

function stubApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      const body = responseFor(url);

      return new Response(JSON.stringify(body), {
        headers: { "content-type": "application/json" },
        status: 200,
      });
    }),
  );
}

function responseFor(url: string): unknown {
  if (url.includes("/drive/items")) {
    return { breadcrumbs: [], items: [], next_cursor: null };
  }

  if (url.includes("/photos/timeline")) {
    return { groups: [], next_cursor: null };
  }

  if (url.includes("/search")) {
    return { facets: [], items: [], next_cursor: null };
  }

  if (url.includes("/jobs")) {
    return { items: [], next_cursor: null };
  }

  if (url.includes("/settings")) {
    return {
      data_paths: { db: "data/db", uploads: "data/uploads" },
      embeddings_state: "disabled",
      model_available: false,
      ocr_state: "disabled",
      storage_backend: "local",
      telegram_configured: false,
      telegram_enabled: false,
      worker_concurrency: 1,
      worker_status: "running",
    };
  }

  return {};
}
