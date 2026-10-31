import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Activity, AttentionItem } from "../../api/activity";
import type { AccountStatus } from "../../api/account";
import type { VaultStatus } from "../../api/vault";
import {
  ActivityStatusPill,
  ConnectedSidebarStatus,
  desktopNavigationHref,
  SidebarStatus,
  subscribeDesktopNavigation,
} from "../../app/status";
import { activityPollInterval, attentionHref, attentionTitle, describeActivity, normalizeActivity } from "../../features/activity/activityModel";
import { createActivityStore } from "../../features/activity/activityStore";

const idleStats = { active: 0, bytes_done: 0, bytes_total: 0, eta_seconds: null, queued: 0 };

function activity(overrides: Partial<Activity> = {}): Activity {
  return { attention: [], downloads: idleStats, summary: "up_to_date", uploads: idleStats, ...overrides };
}

function attention(overrides: Partial<AttentionItem> = {}): AttentionItem {
  return { action: "retry", id: "att_1", kind: "upload_failed", params: {}, title_key: "", ...overrides };
}

describe("describeActivity", () => {
  it.each([
    [activity(), "Todo al día", "success"],
    [activity({ summary: "uploading", uploads: { ...idleStats, active: 1, eta_seconds: 180, queued: 11 } }), "Subiendo 12 archivos · 3 min", "active"],
    [activity({ summary: "uploading", uploads: { ...idleStats, active: 1, eta_seconds: null, queued: 0 } }), "Subiendo 1 archivo", "active"],
    [activity({ summary: "uploading" }), "Subiendo…", "active"],
    [activity({ downloads: { ...idleStats, active: 2, eta_seconds: 3900, queued: 3 }, summary: "downloading" }), "Descargando 5 archivos · 1 h 5 min", "active"],
    [activity({ summary: "syncing" }), "Sincronizando…", "active"],
    [activity({ summary: "paused" }), "Pausado", "idle"],
    [activity({ summary: "offline" }), "Sin conexión — se reanudará solo", "warning"],
    [
      activity({ attention: [attention({ action: "none", kind: "flood_wait", params: { retry_after_seconds: 240 } })], summary: "attention" }),
      "Telegram pidió esperar 4 min",
      "warning",
    ],
    [activity({ attention: [attention({ action: "none", kind: "flood_wait" })], summary: "uploading" }), "Telegram pidió esperar un momento", "warning"],
    [activity({ attention: [attention()], summary: "attention" }), "Necesita tu atención", "warning"],
    [
      activity({ attention: [attention(), attention({ action: "save_recovery_kit", id: "kit", kind: "recovery_kit" })], summary: "attention" }),
      "2 avisos necesitan tu atención",
      "warning",
    ],
  ])("maps %# to a calm sentence", (input, label, tone) => {
    expect(describeActivity(input)).toMatchObject({ label, tone });
  });

  it("says calmly that this device was removed, ahead of transfers", () => {
    const removed = attention({ action: "open_settings", id: "device_removed", kind: "device_removed", title_key: "activity.attention.device_removed" });
    expect(describeActivity(activity({ attention: [removed], summary: "attention" }))).toMatchObject({
      detail: "Tu biblioteca local sigue aquí. Vuelve a unirlo para sincronizar.",
      kind: "removed",
      label: "Este equipo se quitó de tu nube",
      tone: "warning",
    });
    expect(describeActivity(activity({ attention: [removed], summary: "uploading", uploads: { ...idleStats, active: 1 } })).kind).toBe("removed");
  });

  it("names a new device and a stale kit in the status detail", () => {
    const newDevice = attention({
      action: "open_devices", id: "new_device:dev_9", kind: "new_device", params: { device_id: "dev_9", name: "Portátil de Ana" }, title_key: "activity.attention.new_device",
    });
    expect(describeActivity(activity({ attention: [newDevice], summary: "attention" }))).toMatchObject({
      detail: "Se añadió «Portátil de Ana» a tu nube",
      label: "Necesita tu atención",
    });
    expect(attentionTitle({ ...newDevice, params: {} })).toBe("Se añadió un dispositivo a tu nube");
    expect(attentionTitle({ ...newDevice, title_key: "" })).toBe("Se añadió «Portátil de Ana» a tu nube");

    const stale = attention({ action: "save_recovery_kit", id: "recovery_kit", kind: "recovery_kit", params: { reason: "stale" }, title_key: "activity.attention.recovery_kit" });
    expect(describeActivity(activity({ attention: [stale], summary: "attention" })).detail).toBe("Tu kit de recuperación ya no sirve: genera uno nuevo");

    const skew = attention({
      action: "none", id: "clock_skew", kind: "clock_skew", params: { direction: "ahead", skew_minutes: 9, skew_seconds: 540 }, title_key: "activity.attention.clock_skew",
    });
    expect(normalizeActivity(activity({ attention: [skew], summary: "attention" })).attention[0]?.kind).toBe("clock_skew");
    expect(attentionTitle(skew)).toBe("La fecha y hora de este equipo no son correctas");
    expect(attentionHref(skew)).toBeNull();
  });

  it("keeps the new actions and maps each one to a route", () => {
    const normalized = normalizeActivity({
      attention: [
        { action: "open_devices", id: "new_device:dev_9", kind: "new_device", params: { name: "Torre" }, title_key: "activity.attention.new_device" },
        { action: "open_settings", id: "device_removed", kind: "device_removed", params: {}, title_key: "activity.attention.device_removed" },
        { action: "open_settings", id: "inbox", kind: "inbox_failed", params: {}, title_key: "" },
        { action: "retry", id: "upload", kind: "upload_failed", params: {}, title_key: "" },
      ],
      summary: "attention",
    });
    expect(normalized.attention.map((item) => item.action)).toEqual(["open_devices", "open_settings", "open_settings", "retry"]);
    expect(normalized.attention.map(attentionHref)).toEqual(["/settings/devices", "/settings/account", "/settings", null]);
  });

  it("describes loading and unreachable states", () => {
    expect(describeActivity(null)).toMatchObject({ kind: "loading", label: "Comprobando…" });
    expect(describeActivity(null, new Error("offline"))).toMatchObject({ kind: "unavailable", label: "Estado no disponible" });
  });

  it("explains a single attention item with its own title", () => {
    expect(describeActivity(activity({ attention: [attention({ kind: "recovery_kit" })], summary: "attention" })).detail).toBe(
      "Guarda tu kit de recuperación",
    );
  });

  it("normalizes partial payloads and picks the poll interval", () => {
    const normalized = normalizeActivity({ summary: "uploading", uploads: { active: 1 } });
    expect(normalized.uploads).toEqual({ ...idleStats, active: 1 });
    expect(normalizeActivity({}).summary).toBe("up_to_date");
    expect(activityPollInterval(normalized)).toBe(3000);
    expect(activityPollInterval(activity())).toBe(15000);
  });
});

describe("activity store", () => {
  afterEach(() => {
    vi.useRealTimers();
    setVisibility("visible");
  });

  it("polls every 3 s while transfers are active, 15 s when idle, and pauses while hidden", async () => {
    vi.useFakeTimers();
    const fetcher = vi
      .fn<() => Promise<Activity>>()
      .mockResolvedValueOnce(activity({ summary: "uploading", uploads: { ...idleStats, active: 1 } }))
      .mockResolvedValue(activity());
    const store = createActivityStore(fetcher);
    const unsubscribe = store.subscribe(() => undefined);

    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2999);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetcher).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(14_999);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetcher).toHaveBeenCalledTimes(3);

    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetcher).toHaveBeenCalledTimes(3);

    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(4);

    unsubscribe();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("shares one request between every subscriber", async () => {
    const fetcher = vi.fn(async () => activity());
    const store = createActivityStore(fetcher);
    const first = store.subscribe(() => undefined);
    const second = store.subscribe(() => undefined);

    await waitFor(() => expect(store.getSnapshot().activity).not.toBeNull());
    expect(fetcher).toHaveBeenCalledTimes(1);
    first();
    second();
  });

  it("loads immediately after an unsubscribe/resubscribe while a request is in flight (StrictMode remount)", async () => {
    let release: (value: Activity) => void = () => undefined;
    const fetcher = vi
      .fn<() => Promise<Activity>>()
      .mockImplementationOnce(() => new Promise((resolve) => (release = resolve)))
      .mockResolvedValue(activity());
    const store = createActivityStore(fetcher);

    store.subscribe(() => undefined)();
    const unsubscribe = store.subscribe(() => undefined);
    release(activity());

    await waitFor(() => expect(store.getSnapshot().isLoading).toBe(false));
    expect(store.getSnapshot().activity).not.toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(2);
    unsubscribe();
  });
});

describe("status surfaces", () => {
  it("links the top-bar pill to Activity", () => {
    const onNavigate = vi.fn();
    render(<ActivityStatusPill onNavigate={onNavigate} status={describeActivity(activity({ summary: "offline" }))} />);

    expect(screen.getByRole("status")).toHaveTextContent("Sin conexión — se reanudará solo");
    fireEvent.click(screen.getByRole("link", { name: /Sin conexión/ }));
    expect(onNavigate).toHaveBeenCalledWith("/activity");
  });

  it("renders the sidebar footer with initials, cloud usage and status", () => {
    const onNavigate = vi.fn();
    render(
      <SidebarStatus
        account={{ display_name: "Ana Pérez", phone_masked: null, premium: false, user_id: 1, username: "ana" }}
        onNavigate={onNavigate}
        status={describeActivity(activity())}
        usage={{ bytes: 1.2 * 1024 ** 4, scope: "cloud" }}
      />,
    );

    const link = screen.getByRole("link", { name: /Ana Pérez/ });
    expect(link).toHaveTextContent("AP");
    expect(link).toHaveTextContent("1,2 TB en tu nube");
    expect(link).toHaveTextContent("Todo al día");
    fireEvent.click(link);
    expect(onNavigate).toHaveBeenCalledWith("/activity");
  });

  it("loads account, vault and activity for the connected footer", async () => {
    const account: AccountStatus = {
      account: { display_name: "Ana", phone_masked: null, premium: false, user_id: 1, username: null },
      error: null,
      password_hint: null,
      qr: null,
      qr_expires_at: null,
      qr_url: null,
      step: "authorized",
    };
    const vault: VaultStatus = {
      created_at: null,
      devices_count: 2,
      other_vaults: 0,
      reason: null,
      recovery_kit_saved: true,
      recovery_kit_stale: false,
      state: "ready",
      usage: { bytes: 52428800000, files: 1200 },
      vault_id: "vlt_1",
    };
    const store = createActivityStore(async () =>
      activity({ summary: "uploading", uploads: { ...idleStats, active: 1, eta_seconds: 60, queued: 1 } }),
    );

    render(<ConnectedSidebarStatus api={{ getAccount: async () => account, getVault: async () => vault }} store={store} />);

    const link = await screen.findByRole("link", { name: /Ana/ });
    await waitFor(() => expect(link).toHaveTextContent("48,8 GB en tu nube"));
    await waitFor(() => expect(link).toHaveTextContent("Subiendo 2 archivos · 1 min"));
    expect(link.querySelector("img")).toHaveAttribute("src", "/api/account/avatar");
  });

  it("tells a removed device apart and hides the empty usage of a locked vault", async () => {
    const account: AccountStatus = {
      account: { display_name: "Ana", phone_masked: null, premium: false, user_id: 1, username: null },
      error: null, password_hint: null, qr: null, qr_expires_at: null, qr_url: null, step: "authorized",
    };
    const vault: VaultStatus = {
      created_at: null, devices_count: 0, other_vaults: 0, reason: "device_removed", recovery_kit_saved: false, recovery_kit_stale: false,
      state: "locked", usage: { bytes: 0, files: 0 }, vault_id: "vlt_1",
    };
    const store = createActivityStore(async () =>
      activity({ attention: [attention({ action: "open_settings", id: "device_removed", kind: "device_removed" })], summary: "attention" }),
    );

    render(<ConnectedSidebarStatus api={{ getAccount: async () => account, getVault: async () => vault }} store={store} />);

    const link = await screen.findByRole("link", { name: /Ana/ });
    await waitFor(() => expect(link).toHaveTextContent("Este equipo se quitó de tu nube"));
    expect(link).not.toHaveTextContent("0 B");
  });

  it("speaks of this device when there is no Telegram account", () => {
    render(<SidebarStatus account={null} status={describeActivity(activity())} usage={{ bytes: 1536, scope: "device" }} />);

    expect(screen.getByRole("link", { name: /Este equipo/ })).toHaveTextContent("1,5 KB en este equipo");
  });
});

describe("desktop navigation adapter", () => {
  it("maps notification targets to routes, falling back to Activity", () => {
    expect(desktopNavigationHref({ target: "activity" })).toBe("/activity");
    expect(desktopNavigationHref({ attentionId: "att 1/2", target: "activity" })).toBe("/activity?attention=att%201%2F2");
    expect(desktopNavigationHref({ attentionId: "a", target: "recovery-kit" })).toBe("/settings?section=recovery");
    expect(desktopNavigationHref({ target: "settings" })).toBe("/settings");
    expect(desktopNavigationHref({ target: "drive" })).toBe("/drive");
    expect(desktopNavigationHref({ attentionId: "x", target: "something-new" })).toBe("/activity?attention=x");
    // Security notifications: a new device opens its Activity item, a removal opens Cuenta y nube.
    expect(desktopNavigationHref({ attentionId: "new_device:dev_9", target: "activity" })).toBe("/activity?attention=new_device%3Adev_9");
    expect(desktopNavigationHref({ attentionId: "device_removed", target: "settings" })).toBe("/settings/account");
    expect(desktopNavigationHref({ attentionId: "inbox_failed:1", target: "settings" })).toBe("/settings");
    expect(desktopNavigationHref({ target: "devices" })).toBe("/settings/devices");
    expect(desktopNavigationHref("https://example.com")).toBeNull();
    expect(desktopNavigationHref(null)).toBeNull();
  });

  it("is a no-op without the bridge and subscribes when onNavigate exists", () => {
    const listener = vi.fn();
    expect(subscribeDesktopNavigation(listener, undefined)).toBeTypeOf("function");
    expect(subscribeDesktopNavigation(listener, { platform: vi.fn() })).toBeTypeOf("function");

    let emit: (request: unknown) => void = () => undefined;
    const unsubscribe = vi.fn();
    const bridge = {
      onNavigate: vi.fn((callback: (request: unknown) => void) => {
        emit = callback;
        return unsubscribe;
      }),
    };

    const stop = subscribeDesktopNavigation(listener, bridge);
    act(() => emit({ target: "drive" }));
    act(() => emit("not a request"));
    stop();

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith("/drive");
    expect(unsubscribe).toHaveBeenCalled();
  });
});

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: state });
  document.dispatchEvent(new Event("visibilitychange"));
}
