import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useState } from "react";

import { AlbumDetailPage } from "../../features/albums/AlbumDetailPage";
import { AlbumsPage } from "../../features/albums/AlbumsPage";
import { PhotoLightbox } from "../../features/photos/PhotoLightbox";
import { PhotoTimeline } from "../../features/photos/PhotoTimeline";
import { PhotosPage } from "../../features/photos/PhotosPage";
import type { AlbumsApi, Album } from "../../api/albums";
import type { PhotoAsset, PhotosApi } from "../../api/photos";

describe("Photos UI", () => {
  it("renders timeline groups by month and day", () => {
    render(
      <PhotoTimeline
        groups={[
          { assets: [asset({ id: "asset_1", filename: "playa.jpg" })], date: "2026-06-20" },
          { assets: [asset({ id: "asset_2", filename: "cena.jpg" })], date: "2026-05-01" },
        ]}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { level: 2, name: "junio de 2026" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /20 de junio de 2026/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "mayo de 2026" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "playa.jpg" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "cena.jpg" })).toBeInTheDocument();
    expect(screen.queryByText("Miniatura lista")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Marcar favorito" })).not.toBeInTheDocument();
  });

  it("closes the lightbox with Escape and restores focus", async () => {
    render(<LightboxHarness />);

    const opener = screen.getByRole("button", { name: "Abrir" });
    opener.focus();
    fireEvent.click(opener);

    expect(screen.getByRole("dialog", { name: "playa.jpg" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });

  it("calls the favorite API when toggling a photo", async () => {
    const api = photosApiMock({
      getTimeline: vi.fn().mockResolvedValue({
        groups: [{ assets: [asset({ favorite: false })], date: "2026-06-20" }],
        next_cursor: null,
      }),
      toggleFavorite: vi.fn().mockResolvedValue(asset({ favorite: true })),
    });

    render(<PhotosPage api={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "playa.jpg" }));
    fireEvent.click(await screen.findByRole("button", { name: "Marcar favorito" }));

    await waitFor(() => expect(api.toggleFavorite).toHaveBeenCalledWith("asset_1", true));
  });

  it("creates an album and adds an item with mocked APIs", async () => {
    const createdAlbum = album({ asset_ids: [] });
    const api = albumsApiMock({
      addAlbumItem: vi.fn().mockResolvedValue(album({ asset_ids: ["asset_1"] })),
      createAlbum: vi.fn().mockResolvedValue(createdAlbum),
      getAlbum: vi.fn().mockResolvedValue(createdAlbum),
      listAlbums: vi.fn().mockResolvedValue({ albums: [], next_cursor: null }),
    });

    const { unmount } = render(<AlbumsPage api={api} />);

    await screen.findByRole("heading", { name: "No hay álbumes" });
    fireEvent.change(screen.getByLabelText("Nuevo álbum"), { target: { value: "Viaje" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear álbum" }));

    await waitFor(() => expect(api.createAlbum).toHaveBeenCalledWith("Viaje"));
    unmount();

    render(<AlbumDetailPage albumId="album_1" api={api} />);

    await screen.findByRole("heading", { name: "Viaje" });
    fireEvent.change(screen.getByLabelText("Agregar foto o video por ID"), { target: { value: "asset_1" } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar" }));

    await waitFor(() => expect(api.addAlbumItem).toHaveBeenCalledWith("album_1", "asset_1"));
    expect(await screen.findByText("asset_1")).toBeInTheDocument();
  });

  it("renders a basic video viewer in the lightbox", () => {
    render(
      <PhotoLightbox
        asset={asset({ filename: "clip.mp4", kind: "video", mime_type: "video/mp4" })}
        onClose={vi.fn()}
        onToggleFavorite={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "clip.mp4" });
    expect(dialog).toBeInTheDocument();
    expect(dialog.querySelector("video")).toHaveAttribute("controls");
  });

  it("runs searches scoped to photos", async () => {
    const api = photosApiMock({
      getTimeline: vi.fn().mockResolvedValue({ groups: [], next_cursor: null }),
      searchPhotos: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    });

    render(<PhotosPage api={api} />);

    fireEvent.change(screen.getByLabelText("Buscar en fotos"), { target: { value: "playa" } });

    await waitFor(() => expect(api.searchPhotos).toHaveBeenCalledWith("playa"));
  });
});

function LightboxHarness() {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button onClick={() => setOpen(true)} type="button">
        Abrir
      </button>
      {open ? (
        <PhotoLightbox
          asset={asset()}
          onClose={() => setOpen(false)}
          onToggleFavorite={vi.fn()}
        />
      ) : null}
    </div>
  );
}

function photosApiMock(overrides: Partial<PhotosApi>): PhotosApi {
  return {
    getPhoto: vi.fn().mockResolvedValue(asset()),
    getTimeline: vi.fn().mockResolvedValue({ groups: [], next_cursor: null }),
    searchPhotos: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    toggleFavorite: vi.fn().mockResolvedValue(asset()),
    uploadPhoto: vi.fn().mockResolvedValue(asset()),
    ...overrides,
  };
}

function albumsApiMock(overrides: Partial<AlbumsApi>): AlbumsApi {
  return {
    addAlbumItem: vi.fn().mockResolvedValue(album()),
    createAlbum: vi.fn().mockResolvedValue(album()),
    getAlbum: vi.fn().mockResolvedValue(album()),
    listAlbums: vi.fn().mockResolvedValue({ albums: [], next_cursor: null }),
    removeAlbumItem: vi.fn().mockResolvedValue(album()),
    ...overrides,
  };
}

function asset(overrides: Partial<PhotoAsset> = {}): PhotoAsset {
  return {
    created_at: "2026-06-20T10:00:00.000Z",
    favorite: false,
    filename: "playa.jpg",
    id: "asset_1",
    kind: "image",
    mime_type: "image/jpeg",
    processing_state: "indexed",
    preview_url: "/preview.jpg",
    size_bytes: 120,
    taken_at: "2026-06-20T10:00:00.000Z",
    thumbnail_url: "/thumb.jpg",
    updated_at: "2026-06-20T10:00:00.000Z",
    ...overrides,
  };
}

function album(overrides: Partial<Album> = {}): Album {
  return {
    asset_ids: ["asset_1"],
    cover_asset: null,
    created_at: "2026-06-20T10:00:00.000Z",
    id: "album_1",
    title: "Viaje",
    updated_at: "2026-06-20T10:00:00.000Z",
    ...overrides,
  };
}
