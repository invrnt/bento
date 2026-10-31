import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Dialog } from "../../components/Dialog";
import { QuickLook } from "../../features/quicklook/QuickLook";
import { quickLookKeyHandlers, quickLookKind, useQuickLook } from "../../features/quicklook/quickLookModel";
import type { QuickLookItem } from "../../features/quicklook/quickLookModel";

const items: QuickLookItem[] = [
  { id: "asset_photo", kind: "image", name: "playa.jpg", previewUrl: "/api/assets/asset_photo/preview", sizeBytes: 2048 },
  { id: "asset_clip", kind: "video", name: "clip.mp4", posterUrl: "/api/assets/asset_clip/thumbnail", sizeBytes: 5_242_880 },
  { id: "asset_zip", kind: "other", name: "fotos.zip" },
];

function Harness({ extraDialog = false }: { extraDialog?: boolean }) {
  const quickLook = useQuickLook(items);
  const [shareOpen, setShareOpen] = useState(false);

  return (
    <div>
      {items.map((item) => (
        <button key={item.id} onClick={() => quickLook.open(item.id)} type="button" {...quickLookKeyHandlers(() => quickLook.open(item.id))}>
          {`Abrir ${item.name}`}
        </button>
      ))}
      <QuickLook
        actions={() =>
          extraDialog ? (
            <button onClick={() => setShareOpen(true)} type="button">
              Compartir
            </button>
          ) : null
        }
        controller={quickLook}
      />
      <Dialog onOpenChange={setShareOpen} open={shareOpen} title="Compartir">
        <input aria-label="Buscar" data-autofocus />
      </Dialog>
    </div>
  );
}

describe("Quick Look", () => {
  it("opens with Space on the focused item and closes with Escape, returning focus", async () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Abrir playa.jpg" });
    opener.focus();

    fireEvent.keyDown(opener, { key: " " });
    const viewer = screen.getByRole("dialog", { name: "playa.jpg" });
    expect(viewer).toHaveFocus();
    expect(within(viewer).getByRole("img", { name: "playa.jpg" })).toHaveAttribute("src", "/api/assets/asset_photo/preview");
    expect(viewer).toHaveTextContent("Imagen · 2 KB · 1 de 3");

    fireEvent.keyDown(viewer, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });

  it("moves between items with the arrows and closes with Space", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir playa.jpg" }));
    const viewer = screen.getByRole("dialog");

    fireEvent.keyDown(viewer, { key: "ArrowLeft" });
    expect(screen.getByRole("dialog", { name: "playa.jpg" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();

    fireEvent.keyDown(viewer, { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "clip.mp4" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(screen.getByRole("dialog", { name: "fotos.zip" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();

    fireEvent.keyDown(screen.getByRole("dialog"), { key: " " });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("streams videos from /content with native controls and a thumbnail poster", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir clip.mp4" }));

    const video = screen.getByLabelText("clip.mp4", { selector: "video" });
    expect(video).toHaveAttribute("src", "/api/assets/asset_clip/content");
    expect(video).toHaveAttribute("controls");
    expect(video).toHaveAttribute("preload", "metadata");
    expect(video).toHaveAttribute("poster", "/api/assets/asset_clip/thumbnail");

    // Arrow keys seek inside the focused video instead of changing items.
    video.focus();
    fireEvent.keyDown(video, { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "clip.mp4" })).toBeInTheDocument();
  });

  it("offers a download when a file has no preview", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir fotos.zip" }));

    const viewer = screen.getByRole("dialog", { name: "fotos.zip" });
    expect(viewer).toHaveTextContent("Sin vista previa");
    const downloads = within(viewer).getAllByRole("link", { name: "Descargar" });
    expect(downloads[0]).toHaveAttribute("href", "/api/assets/asset_zip/download");
  });

  it("traps focus inside the viewer", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir playa.jpg" }));
    const viewer = screen.getByRole("dialog");
    const close = within(viewer).getByRole("button", { name: "Cerrar" });
    const next = within(viewer).getByRole("button", { name: "Siguiente" });

    next.focus();
    fireEvent.keyDown(next, { key: "Tab" });
    expect(within(viewer).getByRole("link", { name: "Descargar" })).toHaveFocus();

    within(viewer).getByRole("link", { name: "Descargar" }).focus();
    fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
    expect(next).toHaveFocus();
    expect(close).toBeInTheDocument();
  });

  it("leaves the keyboard to a dialog opened on top of it", async () => {
    render(<Harness extraDialog />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir playa.jpg" }));
    fireEvent.click(screen.getByRole("button", { name: "Compartir" }));

    const search = screen.getByRole("textbox", { name: "Buscar" });
    expect(search).toHaveFocus();
    fireEvent.keyDown(search, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Compartir" })).not.toBeInTheDocument());
    expect(screen.getByRole("dialog", { name: "playa.jpg" })).toBeInTheDocument();
  });

  it("resolves the viewer kind from names and MIME types", () => {
    expect(quickLookKind("informe.PDF")).toBe("pdf");
    expect(quickLookKind("notas.md")).toBe("text");
    expect(quickLookKind("audio", "audio/mpeg")).toBe("audio");
    expect(quickLookKind("presentacion.pptx")).toBe("other");
  });

  it("does not hijack modified Space presses", () => {
    const open = vi.fn();
    const handlers = quickLookKeyHandlers(open);
    const event = { altKey: false, ctrlKey: true, key: " ", metaKey: false, preventDefault: vi.fn(), repeat: false, shiftKey: false };

    handlers.onKeyDown(event as never);
    expect(open).not.toHaveBeenCalled();
    handlers.onKeyDown({ ...event, ctrlKey: false } as never);
    expect(open).toHaveBeenCalledTimes(1);
  });
});
