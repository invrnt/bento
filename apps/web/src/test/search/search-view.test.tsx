import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SearchApi, SearchRequest, SearchResponse } from "../../api/search";
import { TopSearch } from "../../components/TopSearch";
import { SearchView } from "../../features/search";

const groupedResponse: SearchResponse = {
  facets: [
    { count: 1, type: "document" },
    { count: 1, type: "photo" },
  ],
  items: [
    {
      asset_id: "asset-photo",
      id: "photo-hit",
      processing_state: "indexed",
      reason: "Coincidio por metadata visual",
      score: 0.4,
      subtitle: "Mar 2026",
      thumbnail_url: "/api/assets/asset-photo/thumbnail",
      title: "IMG_001.jpg",
      type: "photo",
    },
    {
      asset_id: "asset-doc",
      id: "document-hit",
      processing_state: "indexed",
      reason: "Coincidio por OCR y tipo de documento",
      score: 0.91,
      subtitle: "Factura / 2026",
      thumbnail_url: "/api/assets/asset-doc/thumbnail",
      title: "Factura enero.pdf",
      type: "document",
    },
  ],
  next_cursor: null,
};

describe("SearchView", () => {
  it("renders grouped results with explanations and thumbnails", async () => {
    render(<SearchView client={makeClient(groupedResponse)} />);

    expect(await screen.findByRole("heading", { name: "Documento" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Foto" })).toBeInTheDocument();
    expect(screen.getByText("Coincidio por OCR y tipo de documento")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Factura enero.pdf" })).toHaveAttribute(
      "src",
      "/api/assets/asset-doc/thumbnail",
    );
  });

  it("updates query parameters and API filters when filters change", async () => {
    window.history.pushState({}, "", "/search?q=factura");
    const calls: SearchRequest[] = [];
    const client = makeClient({ facets: [], items: [], next_cursor: null }, calls);

    render(<SearchView client={client} />);

    await waitFor(() => expect(calls[0]).toEqual(expect.objectContaining({ q: "factura" })));

    fireEvent.change(screen.getByRole("combobox", { name: "Tipo" }), { target: { value: "document" } });
    fireEvent.change(screen.getByLabelText("Carpeta"), { target: { value: "folder-7" } });
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-02-01" } });

    await waitFor(() =>
      expect(calls).toContainEqual(
        expect.objectContaining({
          dateFrom: "2026-02-01",
          folderId: "folder-7",
          q: "factura",
          type: "document",
        }),
      ),
    );
    expect(window.location.search).toContain("type=document");
    expect(window.location.search).toContain("folder_id=folder-7");
    expect(window.location.search).toContain("date_from=2026-02-01");
  });

  it("counts active filters and clears them while keeping the query", async () => {
    window.history.pushState({}, "", "/search?q=factura&folder_id=folder-7&date_from=2026-02-01");

    render(<SearchView client={makeClient({ facets: [], items: [], next_cursor: null })} />);

    expect(await screen.findByText("2 filtros activos")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));

    expect(screen.getByLabelText("Carpeta")).toHaveValue("");
    expect(screen.queryByText(/filtros? activos?/)).not.toBeInTheDocument();
    expect(window.location.search).toBe("?q=factura");
  });

  it("renders pending and disabled indexing states", async () => {
    render(
      <SearchView
        client={makeClient({
          facets: [],
          items: [
            {
              id: "pending",
              processing_state: "pending",
              reason: "Coincidio por nombre de archivo",
              score: 0.7,
              title: "contrato.docx",
              type: "document",
            },
            {
              id: "disabled",
              processing_state: "disabled",
              reason: "Embeddings desactivados, coincidencia por metadata",
              score: null,
              title: "pasaporte.pdf",
              type: "document",
            },
          ],
          next_cursor: null,
        })}
      />,
    );

    expect(await screen.findByText("Indexación pendiente")).toBeInTheDocument();
    expect(screen.getByText("Indexación desactivada")).toBeInTheDocument();
  });

  it("focuses the global search input with Ctrl+K", () => {
    render(<TopSearch onSubmit={vi.fn()} />);

    fireEvent.keyDown(document, { ctrlKey: true, key: "k" });

    expect(screen.getByRole("searchbox", { name: "Búsqueda global" })).toHaveFocus();
  });
});

function makeClient(response: SearchResponse, calls: SearchRequest[] = []): SearchApi {
  return {
    search: vi.fn(async (request: SearchRequest) => {
      calls.push(request);
      return response;
    }),
  };
}
