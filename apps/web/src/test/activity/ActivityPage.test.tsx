import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Activity, AttentionItem } from "../../api/activity";
import type { BackupPolicy } from "../../api/backup";
import { clearToasts, ToastViewport } from "../../components/Toast";
import { ActivityPage } from "../../features/activity/ActivityPage";
import type { ActivityPageApi } from "../../features/activity/ActivityPage";
import { createActivityStore } from "../../features/activity/activityStore";

const idleStats = { active: 0, bytes_done: 0, bytes_total: 0, eta_seconds: null, queued: 0 };
const policy: BackupPolicy = { bandwidth_limit_kbps: 0, effective_paused: false, on_battery: false, pause_on_battery: true, paused: false };

function activity(overrides: Partial<Activity> = {}): Activity {
  return { attention: [], downloads: idleStats, summary: "up_to_date", uploads: idleStats, ...overrides };
}

function attention(overrides: Partial<AttentionItem>): AttentionItem {
  return { action: "none", id: "att", kind: "upload_failed", params: {}, title_key: "", ...overrides };
}

function setup(data: Activity, apiOverrides: Partial<ActivityPageApi> = {}, focusAttentionId: string | null = null) {
  const fetcher = vi.fn(async () => data);
  const api: ActivityPageApi = {
    getBackupPolicy: vi.fn(async () => policy),
    retryJob: vi.fn(async () => ({})),
    syncNow: vi.fn(async () => ({ accepted: true })),
    updateBackupPolicy: vi.fn(async (patch) => ({ ...policy, ...patch, effective_paused: patch.paused })),
    ...apiOverrides,
  };
  const onNavigate = vi.fn();
  render(
    <>
      <ActivityPage api={api} focusAttentionId={focusAttentionId} onNavigate={onNavigate} store={createActivityStore(fetcher)} />
      <ToastViewport />
    </>,
  );
  return { api, fetcher, onNavigate };
}

describe("ActivityPage", () => {
  afterEach(() => act(() => clearToasts()));

  it("shows upload progress with ETA and queue counts", async () => {
    setup(
      activity({
        summary: "uploading",
        uploads: { active: 1, bytes_done: 400 * 1024 * 1024, bytes_total: 1000 * 1024 * 1024, eta_seconds: 180, queued: 11 },
      }),
    );

    expect(await screen.findByRole("heading", { name: "Subiendo 12 archivos · 3 min" })).toBeInTheDocument();
    const uploads = screen.getByRole("region", { name: "Subidas" });
    expect(within(uploads).getByText("1 en curso · 11 en cola")).toBeInTheDocument();
    expect(within(uploads).getByRole("progressbar", { name: "Progreso de las subidas" })).toHaveAttribute("aria-valuenow", "40");
    expect(within(uploads).getByText("400 MB de 1000 MB")).toBeInTheDocument();
    expect(within(uploads).getByText("Quedan 3 min")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Descargas" })).getByText("No hay descargas pendientes.")).toBeInTheDocument();
  });

  it("pauses and resumes the backup", async () => {
    const { api, fetcher } = setup(activity());

    fireEvent.click(await screen.findByRole("button", { name: "Pausar respaldo" }));
    await waitFor(() => expect(api.updateBackupPolicy).toHaveBeenCalledWith({ paused: true }));
    expect(await screen.findByRole("button", { name: "Reanudar respaldo" })).toBeInTheDocument();
    expect(fetcher.mock.calls.length).toBeGreaterThan(1);

    fireEvent.click(screen.getByRole("button", { name: "Reanudar respaldo" }));
    await waitFor(() => expect(api.updateBackupPolicy).toHaveBeenLastCalledWith({ paused: false }));
  });

  it("gives every attention item exactly one action", async () => {
    const { api, onNavigate } = setup(
      activity({
        attention: [
          attention({ action: "retry", id: "att_upload", kind: "upload_failed", params: { job_id: "job_42" } }),
          attention({ action: "retry", id: "att_sync", kind: "sync_error" }),
          attention({ action: "open_settings", id: "att_inbox", kind: "inbox_failed" }),
          attention({ action: "save_recovery_kit", id: "att_kit", kind: "recovery_kit" }),
          attention({ action: "none", id: "att_flood", kind: "flood_wait", params: { retry_after_seconds: 60 } }),
        ],
        summary: "attention",
      }),
    );

    const list = await screen.findByRole("list", { name: "Avisos" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    for (const row of rows) {
      expect(within(row).getAllByRole("button")).toHaveLength(1);
    }

    fireEvent.click(within(rows[0]).getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(api.retryJob).toHaveBeenCalledWith("job_42"));
    expect(await screen.findByText("Lo intentaremos de nuevo.")).toBeInTheDocument();

    fireEvent.click(within(rows[1]).getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(api.syncNow).toHaveBeenCalled());

    fireEvent.click(within(rows[2]).getByRole("button", { name: "Abrir ajustes" }));
    expect(onNavigate).toHaveBeenCalledWith("/settings");

    fireEvent.click(within(rows[3]).getByRole("button", { name: "Guardar kit" }));
    expect(onNavigate).toHaveBeenCalledWith("/settings?section=recovery");
  });

  it("highlights and focuses the attention item a notification points to", async () => {
    setup(
      activity({
        attention: [
          attention({ action: "retry", id: "att_upload", kind: "upload_failed" }),
          attention({ action: "save_recovery_kit", id: "att_kit", kind: "recovery_kit" }),
        ],
        summary: "attention",
      }),
      {},
      "att_kit",
    );

    const list = await screen.findByRole("list", { name: "Avisos" });
    const target = list.querySelector('[data-attention-id="att_kit"]');
    await waitFor(() => expect(target).toHaveFocus());
    expect(target).toHaveAttribute("aria-current", "true");
    expect(list.querySelector('[data-attention-id="att_upload"]')).not.toHaveAttribute("aria-current");
  });

  it("uses the backend title key when the dictionary knows it", async () => {
    setup(
      activity({
        attention: [attention({ action: "save_recovery_kit", kind: "recovery_kit", title_key: "activity.attention.recovery_kit" })],
        summary: "attention",
      }),
    );

    const list = await screen.findByRole("list", { name: "Avisos" });
    expect(within(list).getByText("Guarda tu kit de recuperación")).toBeInTheDocument();
    expect(within(list).getByText("Con él puedes recuperar todo aunque pierdas tus dispositivos.")).toBeInTheDocument();
  });

  it("reports a failed retry calmly", async () => {
    setup(activity({ attention: [attention({ action: "retry", id: "job_1" })], summary: "attention" }), {
      retryJob: vi.fn(async () => Promise.reject(new Error("nope"))),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo completar la acción. Inténtalo otra vez.");
  });

  it("links advanced users to the jobs page", async () => {
    const { onNavigate } = setup(activity());

    fireEvent.click(await screen.findByRole("link", { name: "Ver trabajos en segundo plano" }));
    expect(onNavigate).toHaveBeenCalledWith("/jobs");
  });

  it("explains a battery pause", async () => {
    setup(activity({ summary: "paused" }), {
      getBackupPolicy: vi.fn(async () => ({ ...policy, effective_paused: true, on_battery: true })),
    });

    expect(await screen.findByText("En pausa mientras el equipo usa la batería.")).toBeInTheDocument();
  });

  it("offers a retry when activity cannot load", async () => {
    render(<ActivityPage api={{ getBackupPolicy: vi.fn(async () => policy), retryJob: vi.fn(), syncNow: vi.fn(), updateBackupPolicy: vi.fn() }} store={createActivityStore(async () => Promise.reject(new Error("down")))} />);

    expect(await screen.findByText("No se pudo cargar la actividad.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
