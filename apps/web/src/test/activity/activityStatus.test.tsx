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
import { activityPollInterval, describeActivity, normalizeActivity } from "../../features/activity/activityModel";
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
      recovery_kit_saved: true,
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
