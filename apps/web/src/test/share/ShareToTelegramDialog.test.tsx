import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { TelegramChat } from "../../api/telegram";
import { clearToasts, ToastViewport } from "../../components/Toast";
import { ShareToTelegramDialog } from "../../features/share/ShareToTelegramDialog";
import type { ShareApi } from "../../features/share/ShareToTelegramDialog";

const chats: TelegramChat[] = [
  { id: 2, kind: "user", title: "Carlos Ruiz" },
  { id: 1, kind: "saved", title: "Saved Messages" },
  { id: -3, kind: "group", title: "Familia" },
  { id: -4, kind: "channel", title: "Recetas" },
];

function renderShare(api: ShareApi, onClose = vi.fn()) {
  render(
    <>
      <ShareToTelegramDialog api={api} onClose={onClose} target={{ id: "asset_1", name: "factura.pdf" }} />
      <ToastViewport />
    </>,
  );
  return onClose;
}

describe("ShareToTelegramDialog", () => {
  afterEach(() => act(() => clearToasts()));

  it("lists recent chats with Saved Messages first and kind labels", async () => {
    renderShare({ listChats: vi.fn(async () => ({ items: chats })) });

    const radios = await screen.findAllByRole("radio");
    expect(radios.map((radio) => radio.closest("label")?.textContent)).toEqual([
      "Mensajes guardadosSolo tú",
      "Carlos RuizPersona",
      "FamiliaGrupo",
      "RecetasCanal",
    ]);
    expect(screen.getByText("Se enviará una copia sin cifrar a ese chat.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
  });

  it("searches chats as you type", async () => {
    const listChats = vi.fn(async ({ query }: { query?: string }) => ({
      items: query ? chats.filter((chat) => chat.title.toLowerCase().includes(query.toLowerCase())) : chats,
    }));
    renderShare({ listChats });
    await screen.findAllByRole("radio");

    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar chat" }), { target: { value: "fam" } });

    await waitFor(() => expect(listChats).toHaveBeenLastCalledWith({ limit: 30, query: "fam" }));
    await waitFor(() => expect(screen.getAllByRole("radio")).toHaveLength(1));
    expect(screen.getByRole("radio", { name: /Familia/ })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar chat" }), { target: { value: "zzz" } });
    expect(await screen.findByText("No encontramos chats con ese nombre.")).toBeInTheDocument();
  });

  it("sends with an optional caption and confirms with a toast", async () => {
    const share = vi.fn(async () => ({ sent: true }));
    const onClose = renderShare({ listChats: vi.fn(async () => ({ items: chats })), share });

    fireEvent.click(await screen.findByRole("radio", { name: /Familia/ }));
    fireEvent.change(screen.getByLabelText("Mensaje (opcional)"), { target: { value: "  La factura de octubre  " } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    await waitFor(() => expect(share).toHaveBeenCalledWith("asset_1", -3, "La factura de octubre"));
    expect(onClose).toHaveBeenCalled();
    expect(await screen.findByText("Enviado a Familia")).toBeInTheDocument();
  });

  it("sends without a caption when it is empty", async () => {
    const share = vi.fn(async () => ({ sent: true }));
    renderShare({ listChats: vi.fn(async () => ({ items: chats })), share });

    fireEvent.click(await screen.findByRole("radio", { name: /Mensajes guardados/ }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    await waitFor(() => expect(share).toHaveBeenCalledWith("asset_1", 1, undefined));
    expect(await screen.findByText("Enviado a Mensajes guardados")).toBeInTheDocument();
  });

  it("explains a Telegram flood wait and keeps the dialog open", async () => {
    const share = vi.fn(async () => {
      throw new ApiError("Too Many Requests", 429, {
        error: { code: "telegram_flood_wait", details: { retry_after_seconds: 120 }, message: "wait" },
      });
    });
    const onClose = renderShare({ listChats: vi.fn(async () => ({ items: chats })), share });

    fireEvent.click(await screen.findByRole("radio", { name: /Carlos/ }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    const dialog = screen.getByRole("dialog", { name: "Enviar por Telegram" });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Telegram pidió esperar 2 min. Inténtalo después.");
    expect(onClose).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("button", { name: "Enviar" })).toBeEnabled();
  });

  it("asks to connect Telegram when chats are unavailable, with a retry", async () => {
    const listChats = vi
      .fn<NonNullable<ShareApi["listChats"]>>()
      .mockRejectedValueOnce(new ApiError("Service Unavailable", 503, { error: { code: "telegram_not_authorized", message: "x" } }))
      .mockResolvedValue({ items: chats });
    renderShare({ listChats });

    expect(await screen.findByText(/Conecta tu Telegram en Ajustes para usar esta función./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findAllByRole("radio")).toHaveLength(4);
  });
});
