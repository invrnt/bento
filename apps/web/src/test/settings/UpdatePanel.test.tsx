import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BentoDesktopBridge, DesktopPlatform, UpdateState } from "../../api/settingsDesktop";
import { UpdatePanel } from "../../features/settings/UpdatePanel";

// The dictionary picks the locale at import time and jsdom reports en-US: pin Spanish first.
vi.hoisted(() => Object.defineProperty(navigator, "language", { configurable: true, value: "es-ES" }));

const platform: DesktopPlatform = {
  arch: "x64",
  desktop: true,
  platform: "win32",
  recoveryMode: false,
  secureStorage: "available",
  version: "0.4.0",
};

afterEach(() => {
  delete window.bento;
});

describe("desktop update experience", () => {
  it("checks explicitly, downloads with accessible progress and confirms installation", async () => {
    let listener: ((state: UpdateState) => void) | undefined;
    let finishDownload: ((state: UpdateState) => void) | undefined;
    const available: UpdateState = { availableVersion: "0.5.0", currentVersion: "0.4.0", installMode: "automatic", releaseName: "Bento 0.5", releaseNotes: "Mejoras de rendimiento", status: "available" };
    const downloaded: UpdateState = { ...available, status: "downloaded" };
    const install = vi.fn(async () => ({ action: "restarting" as const }));
    const download = vi.fn(() => new Promise<UpdateState>((resolve) => { finishDownload = resolve; }));
    installBridge({
      check: vi.fn(async () => available),
      download,
      getState: vi.fn(async (): Promise<UpdateState> => ({ currentVersion: "0.4.0", installMode: "automatic", status: "idle" })),
      install,
      onState: (next) => { listener = next; return vi.fn(); },
    });

    render(<UpdatePanel desktop={platform} />);
    expect(screen.getByText("0.4.0")).toBeInTheDocument();
    expect(screen.getByText(/cada pocas horas/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Buscar actualizaciones" }));
    expect(await screen.findByText(/Nueva versión disponible:/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Ver novedades de esta versión"));
    expect(screen.getByText("Mejoras de rendimiento")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Descargar actualización" }));
    act(() => listener?.({ ...available, progress: { percent: 42.5, totalBytes: 20_000_000, transferredBytes: 8_500_000 }, status: "downloading" }));
    const progress = screen.getByRole("progressbar", { name: "Progreso de descarga de la actualización" });
    expect(progress).toHaveAttribute("aria-valuenow", "43");
    expect(screen.getByText("42,5%")).toBeInTheDocument();
    await act(async () => finishDownload?.(downloaded));

    fireEvent.click(await screen.findByRole("button", { name: "Reiniciar para actualizar" }));
    expect(install).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "¿Actualizar y reiniciar Bento?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Actualizar y reiniciar" }));
    await waitFor(() => expect(install).toHaveBeenCalledOnce());
  });

  it("explains the controlled manual Linux installation", async () => {
    const install = vi.fn(async () => ({ action: "manual" as const, packageManager: "deb" }));
    installBridge({
      check: vi.fn(),
      download: vi.fn(),
      getState: vi.fn(async (): Promise<UpdateState> => ({ availableVersion: "0.5.0", currentVersion: "0.4.0", installMode: "manual", status: "downloaded" })),
      install,
      onState: () => vi.fn(),
    });
    render(<UpdatePanel desktop={{ ...platform, platform: "linux" }} />);

    fireEvent.click(await screen.findByRole("button", { name: "Instalar actualización…" }));
    expect(screen.getByRole("dialog", { name: "Instalar la actualización en Linux" })).toHaveTextContent("paquete descargado y verificado");
    expect(install).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar instalador" }));
    await waitFor(() => expect(install).toHaveBeenCalledOnce());
  });

  it("shows a safe error code and lets the user retry", async () => {
    const check = vi.fn(async (): Promise<UpdateState> => ({ currentVersion: "0.4.0", installMode: "automatic", status: "not-available" }));
    installBridge({
      check,
      download: vi.fn(),
      getState: vi.fn(async (): Promise<UpdateState> => ({ currentVersion: "0.4.0", error: { code: "NETWORK_UNAVAILABLE", message: "private filesystem detail" }, installMode: "automatic", status: "error" })),
      install: vi.fn(),
      onState: () => vi.fn(),
    });
    render(<UpdatePanel desktop={platform} />);

    expect(await screen.findByText(/NETWORK_UNAVAILABLE/)).toBeInTheDocument();
    expect(screen.queryByText(/private filesystem detail/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(check).toHaveBeenCalledOnce());
    expect(screen.getByText("Bento está actualizado.")).toBeInTheDocument();
  });
});

function installBridge(updates: NonNullable<BentoDesktopBridge["updates"]>) {
  window.bento = {
    lifecycle: { onStatus: () => vi.fn(), status: vi.fn() },
    pickDirectory: vi.fn(),
    pickFile: vi.fn(),
    platform: vi.fn(async () => platform),
    settings: { apply: vi.fn(), onProgress: () => vi.fn(), probe: vi.fn() },
    updates,
  } as BentoDesktopBridge;
}
