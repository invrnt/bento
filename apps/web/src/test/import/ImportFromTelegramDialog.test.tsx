import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TelegramChat, TelegramMediaItem } from "../../api/telegram";
import { clearToasts, ToastViewport } from "../../components/Toast";
import { ImportFromTelegramDialog } from "../../features/import/ImportFromTelegramDialog";
import type { ImportApi } from "../../features/import/ImportFromTelegramDialog";

const chats: TelegramChat[] = [
  { id: 2, kind: "user", title: "Carlos Ruiz" },
  { id: 1, kind: "saved", title: "Saved Messages" },
];

function media(id: number, overrides: Partial<TelegramMediaItem> = {}): TelegramMediaItem {
  return { date: "2026-10-03T10:00:00Z", filename: `foto-${id}.jpg`, kind: "photo", message_id: id, size_bytes: 2_500_000, ...overrides };
}

function setup(apiOverrides: Partial<ImportApi> = {}) {
  const api: ImportApi = {
    importMedia: vi.fn(async (request) => ({ job_id: "job_import", queued: request.message_ids?.length ?? 40 })),
    listChats: vi.fn(async () => ({ items: chats })),
    listMedia: vi.fn(async () => ({ items: [media(10), media(11, { filename: "", kind: "video" }), media(12, { filename: "acta.pdf", kind: "document" })], next_cursor: null })),
    ...apiOverrides,
  };
  const onClose = vi.fn();
  const onNavigate = vi.fn();
  render(
    <>
      <ImportFromTelegramDialog api={api} onClose={onClose} onNavigate={onNavigate} open />
      <ToastViewport />
    </>,
  );
  return { api, onClose, onNavigate };
}

async function chooseSavedMessages() {
  fireEvent.click(await screen.findByRole("radio", { name: /Mensajes guardados/ }));
  fireEvent.click(screen.getByRole("button", { name: "Continuar" }));
  return screen.findByRole("group", { name: "Contenido del chat" });
}

describe("ImportFromTelegramDialog", () => {
  afterEach(() => act(() => clearToasts()));

  it("starts with the chat picker, Saved Messages first", async () => {
    setup();

    const radios = await screen.findAllByRole("radio");
    expect(radios[0]).toHaveAccessibleName(/Mensajes guardados/);
    expect(screen.getByRole("button", { name: "Continuar" })).toBeDisabled();
  });

  it("shows the chat's media and imports the selection", async () => {
    const { api, onClose, onNavigate } = setup();
    const grid = await chooseSavedMessages();

    expect(api.listMedia).toHaveBeenCalledWith({ chat_id: 1, kind: "all" });
    expect(screen.getByRole("dialog", { name: "Importar de Telegram" })).toHaveTextContent("Desde Mensajes guardados");
    const tiles = within(grid).getAllByRole("checkbox");
    expect(tiles.map((tile) => tile.getAttribute("aria-label"))).toEqual([
      "Seleccionar foto-10.jpg",
      "Seleccionar Video",
      "Seleccionar acta.pdf",
    ]);
    expect(screen.getByRole("button", { name: "Importar 1 elemento" })).toBeDisabled();

    fireEvent.click(tiles[0]);
    fireEvent.click(tiles[2]);
    expect(tiles[0]).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("2 seleccionados")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Importar 2 elementos" }));

    await waitFor(() => expect(api.importMedia).toHaveBeenCalledWith({ chat_id: 1, message_ids: [10, 12] }));
    expect(onClose).toHaveBeenCalled();
    const toasts = screen.getByRole("region", { name: "Notificaciones" });
    expect(await within(toasts).findByText("Importando 2 archivos")).toBeInTheDocument();
    fireEvent.click(within(toasts).getByRole("button", { name: "Ver progreso" }));
    expect(onNavigate).toHaveBeenCalledWith("/activity");
  });

  it("filters by kind and selects everything visible", async () => {
    const listMedia = vi.fn(async ({ kind }: { kind?: string }) => ({
      items: kind === "video" ? [media(20, { kind: "video" }), media(21, { kind: "video" })] : [media(10)],
      next_cursor: null,
    }));
    const { api } = setup({ listMedia });
    await chooseSavedMessages();

    fireEvent.click(screen.getByRole("radio", { name: "Videos" }));
    await waitFor(() => expect(listMedia).toHaveBeenLastCalledWith({ chat_id: 1, kind: "video" }));
    await waitFor(() => expect(screen.getAllByRole("checkbox", { name: /Seleccionar foto-2/ })).toHaveLength(2));

    fireEvent.click(screen.getByRole("checkbox", { name: "Seleccionar todo" }));
    expect(screen.getByText("2 seleccionados")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Importar 2 elementos" }));
    await waitFor(() => expect(api.importMedia).toHaveBeenCalledWith({ chat_id: 1, message_ids: [20, 21] }));
  });

  it("pages through media and can import the whole chat", async () => {
    const listMedia = vi
      .fn<NonNullable<ImportApi["listMedia"]>>()
      .mockResolvedValueOnce({ items: [media(10), media(11)], next_cursor: "c2" })
      .mockResolvedValueOnce({ items: [media(12)], next_cursor: "c3" });
    const { api } = setup({ listMedia });
    await chooseSavedMessages();

    fireEvent.click(screen.getByRole("button", { name: "Cargar más" }));
    await waitFor(() => expect(screen.getAllByRole("checkbox", { name: /Seleccionar foto/ })).toHaveLength(3));
    expect(listMedia).toHaveBeenLastCalledWith({ chat_id: 1, cursor: "c2", kind: "all" });

    fireEvent.click(screen.getByRole("checkbox", { name: "Seleccionar todo" }));
    expect(screen.getByText("Seleccionaste los 3 elementos visibles.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Seleccionar todo el chat" }));
    expect(screen.getByText("Se importará todo el contenido de este chat.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Importar todo" }));
    await waitFor(() => expect(api.importMedia).toHaveBeenCalledWith({ all: true, chat_id: 1 }));
    expect(await screen.findByText("Importando 40 archivos")).toBeInTheDocument();
  });

  it("goes back to change the chat and explains an empty chat", async () => {
    setup({ listMedia: vi.fn(async () => ({ items: [], next_cursor: null })) });
    await screen.findAllByRole("radio");
    fireEvent.click(screen.getByRole("radio", { name: /Carlos/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByText("No hay nada para importar en este chat.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cambiar chat" }));
    expect(await screen.findByRole("radio", { name: /Carlos/ })).toBeChecked();
  });

  it("keeps the selection when the import request fails", async () => {
    const { onClose } = setup({ importMedia: vi.fn(async () => Promise.reject(new Error("offline"))) });
    const grid = await chooseSavedMessages();

    fireEvent.click(within(grid).getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByRole("button", { name: "Importar 1 elemento" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo completar la acción. Inténtalo otra vez.");
    expect(onClose).not.toHaveBeenCalled();
    expect(within(grid).getAllByRole("checkbox")[0]).toHaveAttribute("aria-checked", "true");
  });
});
