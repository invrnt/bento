import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SettingsPage } from "../../features/settings/SettingsPage";

describe("SettingsPage", () => {
  it("renders storage, Telegram, provider, model, and worker status", () => {
    render(
      <SettingsPage
        settings={{
          data_paths: {
            cache: "D:\\secret\\cache",
            uploads: "D:\\secret\\uploads",
          },
          embeddings_state: "pending",
          model_available: false,
          ocr_state: "ready",
          storage_backend: "telegram",
          telegram_configured: true,
          worker_concurrency: 1,
          worker_status: "running",
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "Ajustes" })).toBeInTheDocument();
    expect(screen.getAllByText("Telegram").length).toBeGreaterThan(0);
    expect(screen.getByText("Configurado")).toBeInTheDocument();
    expect(screen.getByText("Listo")).toBeInTheDocument();
    expect(screen.getAllByText("Pendiente").length).toBeGreaterThan(0);
    expect(screen.getByText("En ejecución")).toBeInTheDocument();
    expect(screen.getByText("cache, uploads")).toBeInTheDocument();
    expect(screen.queryByText("D:\\secret\\cache")).not.toBeInTheDocument();
  });

  it("only offers cache reclamation after Telegram and remote storage are verified", () => {
    const onReclaim = vi.fn();
    render(
      <SettingsPage
        onReclaim={onReclaim}
        settings={{
          storage_backend: "telegram",
          storage_maintenance: {
            can_reclaim: true,
            connection_state: "connected",
            fully_remote: true,
            local_blob_count: 0,
            reclaimable_bytes: 1536,
            reclaimable_files: 3,
            telegram_blob_count: 10,
          },
        }}
      />,
    );

    expect(screen.getByText(/Telegram está conectado/)).toBeInTheDocument();
    expect(screen.getByText(/1,5 KB/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Liberar espacio" }));
    expect(screen.getByRole("dialog", { name: "¿Liberar el espacio local de Bento?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Liberar ahora" }));
    expect(onReclaim).toHaveBeenCalledOnce();
  });

  it("blocks reclamation when Telegram is unavailable", () => {
    render(
      <SettingsPage
        settings={{
          storage_backend: "telegram",
          storage_maintenance: {
            can_reclaim: false,
            connection_state: "unavailable",
            fully_remote: true,
            local_blob_count: 0,
            reclaimable_bytes: 100,
            reclaimable_files: 1,
            telegram_blob_count: 1,
          },
        }}
      />,
    );

    expect(screen.getByRole("button", { name: "Liberar espacio" })).toBeDisabled();
    expect(screen.getByText(/No se pudo verificar la conexión/)).toBeInTheDocument();
  });

  it("renders foundation settings shape without optional fields", () => {
    render(
      <SettingsPage
        settings={{
          storage_backend: "local",
          telegram_enabled: false,
          worker_concurrency: 1,
        }}
      />,
    );

    expect(screen.getByText("Local")).toBeInTheDocument();
    expect(screen.getByText("No configurado")).toBeInTheDocument();
    expect(screen.getAllByText("Deshabilitado").length).toBeGreaterThan(0);
    expect(screen.getByText("Concurrencia: 1")).toBeInTheDocument();
  });
});
