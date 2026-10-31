import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DriveApi, DriveAsset, DriveFolder, DriveItemsResponse, DriveSearchResponse } from "../../api/drive";
import { clearToasts, ToastViewport } from "../../components/Toast";
import { DriveBrowser } from "../../features/drive/DriveBrowser";
import type { DriveBrowserProps } from "../../features/drive/DriveBrowser";

const folder: DriveFolder = {
  created_at: "2026-01-01T00:00:00Z",
  id: "folder_docs",
  name: "Documentos",
  parent_id: null,
  updated_at: "2026-01-01T00:00:00Z",
};

const asset: DriveAsset = {
  created_at: "2026-01-01T00:00:00Z",
  favorite: false,
  filename: "factura.pdf",
  folder_id: null,
  id: "asset_invoice",
  kind: "document",
  mime_type: "application/pdf",
  mode: "drive",
  processing_state: "thumbnail_pending",
  sha256: "abc",
  size_bytes: 2048,
  updated_at: "2026-01-01T00:00:00Z",
};

const textAsset: DriveAsset = {
  ...asset,
  filename: "README.md",
  id: "asset_readme",
  mime_type: "text/markdown",
};

const imageAsset: DriveAsset = {
  ...asset,
  filename: "foto.jpg",
  id: "asset_photo",
  kind: "image",
  mime_type: "image/jpeg",
  processing_state: "indexed",
  thumbnail_url: "/api/assets/asset_photo/thumbnail",
};

function createApi(overrides: Partial<DriveApi> = {}): DriveApi {
  return {
    createFolder: vi.fn(async ({ name, parentId }) => ({
      created_at: "2026-01-01T00:00:00Z",
      id: "folder_new",
      name,
      parent_id: parentId,
      updated_at: "2026-01-01T00:00:00Z",
    })),
    deleteAsset: vi.fn(async () => asset),
    deleteFolder: vi.fn(async () => folder),
    downloadUrl: (assetId) => `/api/assets/${assetId}/download`,
    listItems: vi.fn(async (): Promise<DriveItemsResponse> => ({
      breadcrumbs: [],
      items: [
        { folder, type: "folder" },
        { asset, type: "asset" },
      ],
      next_cursor: null,
    })),
    moveAsset: vi.fn(async () => asset),
    moveFolder: vi.fn(async () => folder),
    previewUrl: (assetId) => `/api/assets/${assetId}/preview`,
    renameAsset: vi.fn(async ({ name }) => ({ ...asset, filename: name })),
    renameFolder: vi.fn(async ({ name }) => ({ ...folder, name })),
    search: vi.fn(async (): Promise<DriveSearchResponse> => ({
      facets: [],
      items: [],
      next_cursor: null,
    })),
    thumbnailUrl: (assetId) => `/api/assets/${assetId}/thumbnail`,
    uploadFiles: vi.fn(async () => [asset]),
    ...overrides,
  };
}

function renderDrive(props: DriveBrowserProps) {
  return render(
    <>
      <DriveBrowser {...props} />
      <ToastViewport />
    </>,
  );
}

describe("DriveBrowser", () => {
  afterEach(() => {
    act(() => clearToasts());
    vi.unstubAllGlobals();
  });

  it("renders folder listings with breadcrumbs and toggles list layout", async () => {
    const api = createApi();
    render(<DriveBrowser api={api} />);

    expect(await screen.findByRole("heading", { name: "Drive" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Ruta de Drive" })).toHaveTextContent("Raíz");
    expect(await screen.findAllByText("Documentos")).not.toHaveLength(0);
    expect(screen.getByRole("complementary", { name: "Árbol de archivos de Drive" })).toBeInTheDocument();
    expect(screen.getByText("factura.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abrir factura.pdf" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Lista" }));

    expect(screen.getAllByRole("list")).toHaveLength(2);
  });

  it("uploads files from the file picker and drag-and-drop", async () => {
    const api = createApi();
    render(<DriveBrowser api={api} />);
    await screen.findByText("factura.pdf");

    const picker = screen.getByTestId("drive-file-input");
    const picked = new File(["uno"], "uno.txt", { type: "text/plain" });
    fireEvent.change(picker, { target: { files: [picked] } });

    await waitFor(() => expect(api.uploadFiles).toHaveBeenCalledWith({ files: [picked], folderId: null }));

    const dropped = new File(["dos"], "dos.txt", { type: "text/plain" });
    fireEvent.drop(screen.getByRole("region", { name: "Drive" }), {
      dataTransfer: { files: [dropped] },
    });

    await waitFor(() => expect(api.uploadFiles).toHaveBeenCalledWith({ files: [dropped], folderId: null }));
  });

  it("uploads a selected folder into newly created nested folders", async () => {
    const createFolder = vi.fn(async ({ name, parentId }: { name: string; parentId: string | null }) => ({
      created_at: "2026-01-01T00:00:00Z",
      id: name === "Proyecto" ? "folder_project" : "folder_reports",
      name,
      parent_id: parentId,
      updated_at: "2026-01-01T00:00:00Z",
    }));
    const api = createApi({ createFolder });
    render(<DriveBrowser api={api} />);
    await screen.findByText("factura.pdf");

    const report = new File(["report"], "informe.pdf", { type: "application/pdf" });
    Object.defineProperty(report, "webkitRelativePath", { value: "Proyecto/Informes/informe.pdf" });
    fireEvent.change(screen.getByTestId("drive-folder-input"), { target: { files: [report] } });

    await waitFor(() => expect(createFolder).toHaveBeenCalledTimes(2));
    expect(createFolder).toHaveBeenNthCalledWith(1, { name: "Proyecto", parentId: null });
    expect(createFolder).toHaveBeenNthCalledWith(2, { name: "Informes", parentId: "folder_project" });
    await waitFor(() =>
      expect(api.uploadFiles).toHaveBeenCalledWith({ files: [report], folderId: "folder_reports" }),
    );
    expect(await screen.findByText("Carga finalizada")).toBeInTheDocument();
  });

  it("renames assets and folders from the action menu", async () => {
    const api = createApi();
    const assetView = render(<DriveBrowser api={api} />);
    await screen.findByText("factura.pdf");

    openMenu("Acciones factura.pdf");
    fireEvent.click(screen.getByRole("menuitem", { name: "Renombrar" }));
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "recibo.pdf" } });
    submitDialog("Guardar");

    await waitFor(() => expect(api.renameAsset).toHaveBeenCalledWith({ assetId: "asset_invoice", name: "recibo.pdf" }));
    assetView.unmount();

    const folderView = render(<DriveBrowser api={api} />);
    await screen.findAllByText("Documentos");

    openMenu("Acciones Documentos");
    fireEvent.click(screen.getByRole("menuitem", { name: "Renombrar" }));
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Archivo" } });
    submitDialog("Guardar");

    await waitFor(() => expect(api.renameFolder).toHaveBeenCalledWith({ folderId: "folder_docs", name: "Archivo" }));
    folderView.unmount();
  });

  it("moves assets and folders from the action menu", async () => {
    const api = createApi();
    const assetView = render(<DriveBrowser api={api} />);
    await screen.findByText("factura.pdf");

    openMenu("Acciones factura.pdf");
    fireEvent.click(screen.getByRole("menuitem", { name: "Mover" }));
    fireEvent.change(await screen.findByLabelText("ID de carpeta destino"), { target: { value: "folder_docs" } });
    submitDialog("Guardar");

    await waitFor(() => expect(api.moveAsset).toHaveBeenCalledWith({ assetId: "asset_invoice", folderId: "folder_docs" }));
    assetView.unmount();

    const folderView = render(<DriveBrowser api={api} />);
    await screen.findAllByText("Documentos");

    openMenu("Acciones Documentos");
    fireEvent.click(screen.getByRole("menuitem", { name: "Mover" }));
    fireEvent.change(await screen.findByLabelText("ID de carpeta destino"), { target: { value: "" } });
    submitDialog("Guardar");

    await waitFor(() => expect(api.moveFolder).toHaveBeenCalledWith({ folderId: "folder_docs", parentId: null }));
    folderView.unmount();
  });

  it("moves assets and folders to trash at once and undoes from the toast", async () => {
    const api = createApi();
    const restoreFromTrash = vi.fn(async () => ({ restored: 1 }));
    const assetView = renderDrive({ api, restoreFromTrash });
    await screen.findByText("factura.pdf");

    openMenu("Acciones factura.pdf");
    fireEvent.click(screen.getByRole("menuitem", { name: "Eliminar" }));

    await waitFor(() => expect(api.deleteAsset).toHaveBeenCalledWith("asset_invoice"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const toasts = screen.getByRole("region", { name: "Notificaciones" });
    expect(await within(toasts).findByText("Movido a la papelera")).toBeInTheDocument();

    fireEvent.click(within(toasts).getByRole("button", { name: "Deshacer" }));
    await waitFor(() => expect(restoreFromTrash).toHaveBeenCalledWith(["asset_invoice"]));
    expect(await within(toasts).findByText("Listo, está otra vez en su sitio")).toBeInTheDocument();
    assetView.unmount();

    const folderView = renderDrive({ api, restoreFromTrash });
    await screen.findAllByText("Documentos");

    openMenu("Acciones Documentos");
    fireEvent.click(screen.getByRole("menuitem", { name: "Eliminar" }));

    await waitFor(() => expect(api.deleteFolder).toHaveBeenCalledWith("folder_docs"));
    folderView.unmount();
  });

  it("undoes the latest delete with Ctrl+Z", async () => {
    const api = createApi();
    const restoreFromTrash = vi.fn(async () => ({ restored: 1 }));
    renderDrive({ api, restoreFromTrash });
    await screen.findByText("factura.pdf");

    openMenu("Acciones factura.pdf");
    fireEvent.click(screen.getByRole("menuitem", { name: "Eliminar" }));
    await screen.findByText("Movido a la papelera");

    fireEvent.keyDown(document.body, { ctrlKey: true, key: "z" });

    await waitFor(() => expect(restoreFromTrash).toHaveBeenCalledWith(["asset_invoice"]));
  });

  it("selects files and folders together and moves them in bulk", async () => {
    const api = createApi();
    render(<DriveBrowser api={api} />);
    await screen.findByText("factura.pdf");

    fireEvent.click(screen.getByRole("checkbox", { name: "Seleccionar Documentos" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Seleccionar factura.pdf" }));
    expect(screen.getByText("2 seleccionados")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mover seleccionados" }));
    fireEvent.change(await screen.findByLabelText("ID de carpeta destino"), { target: { value: "folder_archive" } });
    submitDialog("Guardar");

    await waitFor(() => {
      expect(api.moveFolder).toHaveBeenCalledWith({ folderId: "folder_docs", parentId: "folder_archive" });
      expect(api.moveAsset).toHaveBeenCalledWith({ assetId: "asset_invoice", folderId: "folder_archive" });
    });
    expect(screen.queryByText("2 seleccionados")).not.toBeInTheDocument();
  });

  it("moves selected files and folders to trash in bulk, keeping partial failures undoable", async () => {
    const api = createApi({ deleteFolder: vi.fn(async () => Promise.reject(new Error("busy"))) });
    const restoreFromTrash = vi.fn(async () => ({ restored: 1 }));
    renderDrive({ api, restoreFromTrash });
    await screen.findByText("factura.pdf");

    fireEvent.click(screen.getByRole("checkbox", { name: "Seleccionar Documentos" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Seleccionar factura.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Eliminar seleccionados" }));

    await waitFor(() => {
      expect(api.deleteFolder).toHaveBeenCalledWith("folder_docs");
      expect(api.deleteAsset).toHaveBeenCalledWith("asset_invoice");
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByText("Movido a la papelera")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("1 elemento no se pudo mover a la papelera.");
    expect(screen.queryByText("2 seleccionados")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Deshacer" }));
    await waitFor(() => expect(restoreFromTrash).toHaveBeenCalledWith(["asset_invoice"]));
  });

  it("downloads selected assets without trying to download selected folders", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const api = createApi();

    try {
      render(<DriveBrowser api={api} />);
      await screen.findByText("factura.pdf");

      fireEvent.click(screen.getByRole("checkbox", { name: "Seleccionar Documentos" }));
      fireEvent.click(screen.getByRole("checkbox", { name: "Seleccionar factura.pdf" }));
      fireEvent.click(screen.getByRole("button", { name: "Descargar seleccionados" }));

      expect(openSpy).toHaveBeenCalledWith("/api/assets/asset_invoice/download", "_blank", "noopener,noreferrer");
    } finally {
      openSpy.mockRestore();
    }
  });

  it("exposes file actions in the contextual menu", async () => {
    const api = createApi();
    render(<DriveBrowser api={api} />);
    await screen.findByText("factura.pdf");

    fireEvent.click(screen.getByRole("button", { name: "Acciones factura.pdf" }));
    expect(screen.getByRole("menuitem", { name: "Vista rápida" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Enviar por Telegram…" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Descargar" })).toBeInTheDocument();
  });

  it("opens the same file actions with the right mouse button", async () => {
    const api = createApi();
    render(<DriveBrowser api={api} />);
    await screen.findByText("factura.pdf");

    fireEvent.contextMenu(screen.getByRole("button", { name: "Abrir factura.pdf" }));

    expect(await screen.findByRole("menuitem", { name: "Vista rápida" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Enviar por Telegram…" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Descargar" })).toBeInTheDocument();
  });

  it("loads Markdown and plain text into Quick Look from the streaming endpoint", async () => {
    const fetchMock = vi.fn(async () => ({
      blob: async () => new Blob(),
      ok: true,
      status: 200,
      text: async () => "# Bento\n\nconst answer = 42;",
    }));
    vi.stubGlobal("fetch", fetchMock);
    const api = createApi({
      listItems: vi.fn(async (): Promise<DriveItemsResponse> => ({
        breadcrumbs: [],
        items: [{ asset: textAsset, type: "asset" }],
        next_cursor: null,
      })),
    });

    try {
      render(<DriveBrowser api={api} />);
      await screen.findByText("README.md");
      fireEvent.click(screen.getByRole("button", { name: "Abrir README.md" }));

      expect(await screen.findByText(/# Bento/)).toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/assets/asset_readme/content",
        expect.objectContaining({ headers: { Range: "bytes=0-262143" }, signal: expect.any(AbortSignal) }),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("loads PDFs into Quick Look as an embedded preview", async () => {
    const fetchMock = vi.fn(async () => ({
      blob: async () => new Blob(["pdf"], { type: "application/pdf" }),
      ok: true,
      status: 200,
      text: async () => "",
    }));
    const createObjectURL = vi.fn(() => "blob:pdf-preview");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });

    try {
      const api = createApi();
      render(<DriveBrowser api={api} />);
      await screen.findByText("factura.pdf");
      fireEvent.click(screen.getByRole("button", { name: "Abrir factura.pdf" }));

      expect(await screen.findByTitle("factura.pdf · Vista rápida")).toHaveAttribute("src", "blob:pdf-preview");
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/assets/asset_invoice/content",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("opens images in a large centered viewer when the card is tapped", async () => {
    const api = createApi({
      listItems: vi.fn(async (): Promise<DriveItemsResponse> => ({
        breadcrumbs: [],
        items: [{ asset: imageAsset, type: "asset" }],
        next_cursor: null,
      })),
    });

    const view = render(<DriveBrowser api={api} />);
    await screen.findByText("foto.jpg");
    expect(view.container.querySelector('[data-file-type="image"] img')).toHaveClass("h-full", "w-full", "object-cover");
    fireEvent.click(screen.getByRole("button", { name: "Abrir foto.jpg" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "foto.jpg" })).toHaveAttribute(
      "src",
      "/api/assets/asset_photo/preview",
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the context menu with the keyboard and returns focus on escape", async () => {
    const api = createApi();
    render(<DriveBrowser api={api} />);
    await screen.findByText("factura.pdf");

    const menuButton = screen.getByRole("button", { name: "Acciones factura.pdf" });
    menuButton.focus();
    fireEvent.click(menuButton);

    expect(screen.getByRole("menuitem", { name: "Vista rápida" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(menuButton).toHaveFocus();
  });

  it("opens Quick Look with Space on a focused file and walks files with the arrows", async () => {
    const api = createApi({
      listItems: vi.fn(async (): Promise<DriveItemsResponse> => ({
        breadcrumbs: [],
        items: [
          { folder, type: "folder" },
          { asset: imageAsset, type: "asset" },
          { asset: { ...imageAsset, filename: "playa.jpg", id: "asset_beach" }, type: "asset" },
        ],
        next_cursor: null,
      })),
    });
    renderDrive({ api });
    await screen.findByText("foto.jpg");

    const folderButton = screen.getByRole("button", { name: "Abrir Documentos" });
    fireEvent.keyDown(folderButton, { key: " " });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole("button", { name: "Abrir foto.jpg" }), { key: " " });
    const viewer = await screen.findByRole("dialog", { name: "foto.jpg" });
    expect(within(viewer).getByText(/1 de 2/)).toBeInTheDocument();

    fireEvent.keyDown(viewer, { key: "ArrowRight" });
    expect(await screen.findByRole("dialog", { name: "playa.jpg" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "playa.jpg" })).toHaveAttribute("src", "/api/assets/asset_beach/preview");

    fireEvent.keyDown(screen.getByRole("dialog"), { key: " " });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("opens the share dialog from the file menu", async () => {
    const listChats = vi.fn(async () => ({ items: [{ id: 1, kind: "saved" as const, title: "Saved Messages" }] }));
    renderDrive({ api: createApi(), shareApi: { listChats } });
    await screen.findByText("factura.pdf");

    openMenu("Acciones factura.pdf");
    fireEvent.click(screen.getByRole("menuitem", { name: "Enviar por Telegram…" }));

    const dialog = await screen.findByRole("dialog", { name: "Enviar por Telegram" });
    expect(within(dialog).getByText("factura.pdf")).toBeInTheDocument();
    expect(await within(dialog).findByRole("radio", { name: /Mensajes guardados/ })).toBeInTheDocument();
  });

  it("offers folder upload and Telegram import in the add menu", async () => {
    const listChats = vi.fn(async () => ({ items: [] }));
    renderDrive({ api: createApi(), importApi: { listChats } });
    await screen.findByText("factura.pdf");

    fireEvent.click(screen.getByRole("button", { name: "Más formas de añadir" }));
    expect(screen.getByRole("menuitem", { name: "Subir carpeta" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "Importar de Telegram…" }));

    expect(await screen.findByRole("dialog", { name: "Importar de Telegram" })).toBeInTheDocument();
    await waitFor(() => expect(listChats).toHaveBeenCalled());
  });

  it("calls Drive scoped search with the current folder id", async () => {
    const api = createApi({
      search: vi.fn(async (): Promise<DriveSearchResponse> => ({
        facets: [],
        items: [
          {
            asset_id: "asset_invoice",
            id: "hit_invoice",
            processing_state: "indexed",
            reason: "nombre de archivo",
            score: 1,
            subtitle: null,
            thumbnail_url: null,
            title: "factura.pdf",
            type: "asset",
          },
        ],
        next_cursor: null,
      })),
    });

    render(<DriveBrowser api={api} initialFolderId="folder_docs" />);
    await screen.findByText("factura.pdf");

    fireEvent.change(screen.getByLabelText("Buscar en esta carpeta"), { target: { value: "factura" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));

    await waitFor(() => expect(api.search).toHaveBeenCalledWith({ folderId: "folder_docs", query: "factura" }));
    expect(await screen.findByRole("button", { name: "Abrir factura.pdf" })).toBeInTheDocument();
  });
});

function openMenu(name: string) {
  const button = screen.getByRole("button", { name });
  fireEvent.click(button);
}

function submitDialog(name: string) {
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name }));
}
