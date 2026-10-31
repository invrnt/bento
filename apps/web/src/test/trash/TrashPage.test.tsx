import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TrashItem } from "../../api/trash";
import { clearToasts, ToastViewport } from "../../components/Toast";
import { TrashPage } from "../../features/trash/TrashPage";
import type { TrashApi } from "../../features/trash/useTrash";

const now = new Date("2026-10-31T12:00:00Z");

function item(overrides: Partial<TrashItem> = {}): TrashItem {
  return {
    deleted_at: "2026-10-20T10:00:00Z",
    id: "asset_1",
    name: "factura.pdf",
    purge_at: "2026-11-19T10:00:00Z",
    size_bytes: 2048,
    thumbnail_url: null,
    type: "asset",
    ...overrides,
  };
}

function createApi(items: TrashItem[], overrides: Partial<TrashApi> = {}): TrashApi {
  return {
    empty: vi.fn(async () => ({ purged: items.length })),
    list: vi.fn(async () => ({ items, next_cursor: null })),
    purge: vi.fn(async (ids: string[]) => ({ purged: ids.length })),
    restore: vi.fn(async (ids: string[]) => ({ restored: ids.length })),
    ...overrides,
  };
}

function renderTrash(api: TrashApi) {
  return render(
    <>
      <TrashPage api={api} now={now} />
      <ToastViewport />
    </>,
  );
}

describe("TrashPage", () => {
  afterEach(() => act(() => clearToasts()));

  it("lists deleted items with their deletion and purge dates", async () => {
    renderTrash(createApi([item(), item({ id: "folder_1", name: "Viajes", purge_at: "2026-11-01T10:00:00Z", type: "folder" })]));

    const list = await screen.findByRole("list", { name: "Elementos en la papelera" });
    expect(within(list).getByText("factura.pdf")).toBeInTheDocument();
    expect(within(list).getAllByText(/Eliminado el 20 de octubre/)).not.toHaveLength(0);
    expect(within(list).getAllByText("Se borrará el 19 de noviembre")).not.toHaveLength(0);
    expect(within(list).getAllByText("Se borrará el 1 de noviembre")[0]).toHaveClass("text-warning-ink");
    expect(screen.getByText("2 elementos · 4 KB")).toBeInTheDocument();
  });

  it("shows a calm empty state", async () => {
    renderTrash(createApi([]));

    expect(await screen.findByRole("heading", { name: "La papelera está vacía" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Vaciar papelera" })).not.toBeInTheDocument();
  });

  it("restores one item from its row", async () => {
    const api = createApi([item(), item({ id: "asset_2", name: "playa.jpg" })]);
    renderTrash(api);

    fireEvent.click(await screen.findByRole("button", { name: "Restaurar factura.pdf" }));

    await waitFor(() => expect(api.restore).toHaveBeenCalledWith(["asset_1"]));
    expect(await screen.findByText("Se restauró «factura.pdf»")).toBeInTheDocument();
    expect(screen.queryByText("factura.pdf")).not.toBeInTheDocument();
  });

  it("restores several selected items at once", async () => {
    const api = createApi([item(), item({ id: "asset_2", name: "playa.jpg" }), item({ id: "asset_3", name: "nota.txt" })]);
    renderTrash(api);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Seleccionar factura.pdf" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Seleccionar playa.jpg" }));
    const bar = screen.getByRole("region", { name: "Selección de la papelera" });
    expect(bar).toHaveTextContent("2 seleccionados");

    fireEvent.click(within(bar).getByRole("button", { name: "Restaurar" }));

    await waitFor(() => expect(api.restore).toHaveBeenCalledWith(["asset_1", "asset_2"]));
    expect(await screen.findByText("Se restauraron 2 elementos")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Selección de la papelera" })).not.toBeInTheDocument();
  });

  it("explains the consequence before deleting forever", async () => {
    const api = createApi([item(), item({ id: "asset_2", name: "playa.jpg" })]);
    renderTrash(api);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Seleccionar todo" }));
    fireEvent.click(within(screen.getByRole("region", { name: "Selección de la papelera" })).getByRole("button", { name: "Borrar para siempre" }));

    const dialog = screen.getByRole("dialog", { name: "Borrar para siempre" });
    expect(dialog).toHaveTextContent("2 elementos");
    expect(dialog).toHaveTextContent("de tu Telegram y de todos tus dispositivos. Esta acción no se puede deshacer.");

    fireEvent.click(within(dialog).getByRole("button", { name: "Borrar para siempre" }));

    await waitFor(() => expect(api.purge).toHaveBeenCalledWith(["asset_1", "asset_2"]));
    expect(await screen.findByText("Se borraron 2 elementos para siempre")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "La papelera está vacía" })).toBeInTheDocument();
  });

  it("deletes one item forever from its menu", async () => {
    const api = createApi([item()]);
    renderTrash(api);

    fireEvent.click(await screen.findByRole("button", { name: "Acciones para factura.pdf" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Borrar para siempre" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Borrar para siempre" }));

    await waitFor(() => expect(api.purge).toHaveBeenCalledWith(["asset_1"]));
    expect(await screen.findByText("Se borró «factura.pdf» para siempre")).toBeInTheDocument();
  });

  it("empties the trash after confirmation", async () => {
    const api = createApi([item(), item({ id: "asset_2", name: "playa.jpg" })]);
    renderTrash(api);

    fireEvent.click(await screen.findByRole("button", { name: "Vaciar papelera" }));
    const dialog = screen.getByRole("dialog", { name: "Vaciar la papelera" });
    expect(dialog).toHaveTextContent("Esta acción no se puede deshacer.");

    fireEvent.click(within(dialog).getByRole("button", { name: "Vaciar papelera" }));

    await waitFor(() => expect(api.empty).toHaveBeenCalled());
    expect(await screen.findByText("La papelera quedó vacía")).toBeInTheDocument();
  });

  it("loads more pages on demand", async () => {
    const list = vi
      .fn<TrashApi["list"]>()
      .mockResolvedValueOnce({ items: [item()], next_cursor: "page_2" })
      .mockResolvedValueOnce({ items: [item({ id: "asset_2", name: "playa.jpg" })], next_cursor: null });
    renderTrash(createApi([], { list }));

    fireEvent.click(await screen.findByRole("button", { name: "Mostrar más" }));

    expect(await screen.findByText("playa.jpg")).toBeInTheDocument();
    expect(list).toHaveBeenLastCalledWith({ cursor: "page_2", limit: 100 });
    expect(screen.queryByRole("button", { name: "Mostrar más" })).not.toBeInTheDocument();
  });

  it("offers a retry when the trash cannot load", async () => {
    const list = vi.fn<TrashApi["list"]>().mockRejectedValueOnce(new Error("down")).mockResolvedValue({ items: [], next_cursor: null });
    renderTrash(createApi([], { list }));

    fireEvent.click(await screen.findByRole("button", { name: "Reintentar" }));

    expect(await screen.findByRole("heading", { name: "La papelera está vacía" })).toBeInTheDocument();
  });
});
