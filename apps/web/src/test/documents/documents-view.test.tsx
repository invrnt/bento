import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SearchApi, SearchHit, SearchRequest } from "../../api/search";
import { DocumentsView } from "../../features/documents";
import { documentQuickLookItems } from "../../features/documents/DocumentsView";

const invoice: SearchHit = {
  asset_id: "asset_invoice",
  id: "hit_invoice",
  processing_state: "indexed",
  reason: "Texto: «total a pagar»",
  score: 0.82,
  title: "factura.pdf",
  type: "document",
};

describe("DocumentsView", () => {
  it("applies a document search filter by default", async () => {
    window.history.pushState({}, "", "/documents");
    const calls: SearchRequest[] = [];

    render(<DocumentsView client={makeClient(calls)} />);

    await waitFor(() => expect(calls[0]).toEqual(expect.objectContaining({ type: "document" })));
    expect(await screen.findByRole("heading", { name: "Documentos" })).toBeInTheDocument();
  });

  it("can switch the filtered document view to PDF pages", async () => {
    window.history.pushState({}, "", "/documents?type=document");
    const calls: SearchRequest[] = [];

    render(<DocumentsView client={makeClient(calls)} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Tipo" }), { target: { value: "pdf_page" } });

    await waitFor(() => expect(calls).toContainEqual(expect.objectContaining({ type: "pdf_page" })));
    expect(window.location.search).toContain("type=pdf_page");
  });

  it("opens a document in Quick Look from its result", async () => {
    window.history.pushState({}, "", "/documents");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ blob: async () => new Blob(["%PDF"]), ok: true, status: 200, text: async () => "" })),
    );

    try {
      render(<DocumentsView client={makeClient([], [invoice])} />);
      fireEvent.click(await screen.findByRole("button", { name: "factura.pdf" }));

      expect(await screen.findByRole("dialog", { name: "factura.pdf" })).toBeInTheDocument();
      await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/assets/asset_invoice/content", expect.anything()));
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("sends a document by Telegram from its menu", async () => {
    window.history.pushState({}, "", "/documents");
    const listChats = vi.fn(async () => ({ items: [] }));

    render(<DocumentsView client={makeClient([], [invoice])} shareApi={{ listChats }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Acciones para factura.pdf" }));
    expect(screen.getByRole("menuitem", { name: "Vista rápida" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "Enviar por Telegram…" }));

    expect(await screen.findByRole("dialog", { name: "Enviar por Telegram" })).toHaveTextContent("factura.pdf");
  });

  it("collapses several hits of one file into a single Quick Look item", () => {
    const items = documentQuickLookItems([
      { ...invoice, id: "p1", type: "pdf_page" },
      { ...invoice, id: "p2", type: "pdf_page" },
      { ...invoice, asset_id: undefined, id: "orphan" },
    ]);

    expect(items).toEqual([{ id: "asset_invoice", kind: "pdf", name: "factura.pdf" }]);
  });
});

function makeClient(calls: SearchRequest[], items: SearchHit[] = []): SearchApi {
  return {
    search: vi.fn(async (request: SearchRequest) => {
      calls.push(request);

      return {
        facets: [],
        items,
        next_cursor: null,
      };
    }),
  };
}
