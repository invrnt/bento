import { access } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { ActivityMonitor, ActivityState, parseActivity, parsePolicy } from "../src/main/activity";
import { createStrings } from "../src/main/i18n";
import { TRAY_ICON_STATES, TrayController, trayIconPath, trayMenuTemplate, trayModel } from "../src/main/tray";

const es = createStrings(["es-CO"]);
const en = createStrings(["en-US"]);

function activityPayload(overrides: Record<string, unknown> = {}) {
  return {
    summary: "up_to_date",
    uploads: { active: 0, queued: 0, bytes_total: 0, bytes_done: 0, eta_seconds: null },
    downloads: { active: 0, queued: 0, bytes_total: 0, bytes_done: 0, eta_seconds: null },
    attention: [],
    ...overrides,
  };
}

function state(payload: unknown, policy: unknown = { paused: false, effective_paused: false, on_battery: false, pause_on_battery: true, bandwidth_limit_kbps: 0 }): ActivityState {
  const activity = parseActivity(payload);
  return { available: activity !== null, activity, policy: parsePolicy(policy) };
}

describe("tray state mapping", () => {
  it.each([
    [activityPayload(), "idle", "Todo al día"],
    [activityPayload({ summary: "uploading", uploads: { active: 1, queued: 11, eta_seconds: 180 } }), "syncing", "Subiendo 12 archivos · 3 min"],
    [activityPayload({ summary: "uploading", uploads: { active: 1, queued: 0, eta_seconds: 20 } }), "syncing", "Subiendo 1 archivo · menos de 1 min"],
    [activityPayload({ summary: "downloading", downloads: { active: 2, queued: 0, eta_seconds: null } }), "syncing", "Descargando 2 archivos"],
    [activityPayload({ summary: "syncing" }), "syncing", "Sincronizando…"],
    [activityPayload({ summary: "paused" }), "paused", "Respaldo en pausa"],
    [activityPayload({ summary: "offline" }), "paused", "Sin conexión — se reanudará solo"],
    [activityPayload({ summary: "attention", attention: [{ id: "a1", kind: "upload_failed", title_key: "x", params: {}, action: "retry" }] }), "attention", "Bento necesita tu atención"],
  ])("maps %j", (payload, icon, status) => {
    const model = trayModel({ lifecycle: "ready", activity: state(payload), update: null }, es);
    expect(model.icon).toBe(icon);
    expect(model.status).toBe(status);
    expect(model.tooltip).toBe(`Bento — ${status}`);
  });

  it("falls back to a neutral state when /api/activity is missing or malformed", () => {
    for (const payload of [null, {}, { summary: "exploding" }, "up_to_date", []]) {
      const model = trayModel({ lifecycle: "ready", activity: state(payload, null), update: null }, es);
      expect(model).toMatchObject({ icon: "idle", status: "Bento está abierto", backupAction: null });
    }
  });

  it("reflects the sidecar lifecycle before activity", () => {
    const ready = state(activityPayload({ summary: "uploading" }));
    expect(trayModel({ lifecycle: "starting", activity: ready, update: null }, es)).toMatchObject({ icon: "idle", status: "Iniciando…", backupAction: null });
    expect(trayModel({ lifecycle: "recovery", activity: ready, update: null }, es)).toMatchObject({ icon: "attention", status: "Bento necesita reiniciarse" });
    expect(trayModel({ lifecycle: "stopping", activity: ready, update: null }, en)).toMatchObject({ status: "Closing…" });
  });

  it("offers pause or resume from the backup policy and the explicit update action", () => {
    const paused = state(activityPayload({ summary: "paused" }), { paused: true, effective_paused: true, on_battery: false });
    expect(trayModel({ lifecycle: "ready", activity: paused, update: null }, es).backupAction).toBe("resume");
    const battery = state(activityPayload({ summary: "paused" }), { paused: false, effective_paused: true, on_battery: true });
    expect(trayModel({ lifecycle: "ready", activity: battery, update: null }, es).backupAction).toBe("pause");
    expect(trayModel({ lifecycle: "ready", activity: battery, update: { status: "downloaded", installMode: "automatic" } }, es).updateAction).toBe("restart");
    expect(trayModel({ lifecycle: "ready", activity: battery, update: { status: "downloaded", installMode: "manual" } }, es).updateAction).toBe("install");
    expect(trayModel({ lifecycle: "ready", activity: battery, update: { status: "available", installMode: "automatic" } }, es).updateAction).toBeNull();
  });

  it("uses English labels when the OS locale is English", () => {
    const model = trayModel({ lifecycle: "ready", activity: state(activityPayload({ summary: "uploading", uploads: { active: 3, queued: 0, eta_seconds: 7200 } })), update: null }, en);
    expect(model.status).toBe("Uploading 3 files · 2 h");
    const actions = { open: vi.fn(), setBackupPaused: vi.fn(), installUpdate: vi.fn(), quit: vi.fn() };
    expect(trayMenuTemplate(model, en, actions).map((item) => item.label ?? item.type)).toEqual([
      "Uploading 3 files · 2 h", "separator", "Open Bento", "Pause backup", "separator", "Quit",
    ]);
  });

  it("builds the Spanish menu and wires each action", () => {
    const model = trayModel({ lifecycle: "ready", activity: state(activityPayload(), { paused: true }), update: { status: "downloaded", installMode: "automatic" } }, es);
    const actions = { open: vi.fn(), setBackupPaused: vi.fn(), installUpdate: vi.fn(), quit: vi.fn() };
    const template = trayMenuTemplate(model, es, actions);
    expect(template.map((item) => item.label ?? item.type)).toEqual([
      "Todo al día", "separator", "Abrir Bento", "Reanudar respaldo", "Reiniciar para actualizar", "separator", "Salir",
    ]);
    expect(template[0]!.enabled).toBe(false);
    for (const item of template) item.click?.();
    expect(actions.open).toHaveBeenCalledOnce();
    expect(actions.setBackupPaused).toHaveBeenCalledWith(false);
    expect(actions.installUpdate).toHaveBeenCalledOnce();
    expect(actions.quit).toHaveBeenCalledOnce();
  });

  it("ships every icon variant for each platform", async () => {
    const root = path.resolve(import.meta.dirname, "../resources/tray");
    for (const platform of ["darwin", "win32", "linux"] as const) {
      for (const icon of TRAY_ICON_STATES) await access(trayIconPath(root, platform, icon));
    }
    for (const icon of TRAY_ICON_STATES) {
      await access(path.join(root, `tray-${icon}@2x.png`));
      await access(path.join(root, `tray-${icon}Template@2x.png`));
    }
    await access(path.join(root, "notification.png"));
    expect(trayIconPath(root, "darwin", "idle")).toMatch(/Template\.png$/u);
  });

  it("re-renders only on change and always resets the Linux context menu", () => {
    const tray = { setImage: vi.fn(), setToolTip: vi.fn(), setContextMenu: vi.fn(), on: vi.fn(), destroy: vi.fn() };
    const createTray = vi.fn(() => tray);
    const loadImage = vi.fn((filePath: string) => ({ filePath }));
    const controller = new TrayController({
      platform: "linux",
      iconRoot: "/res/tray",
      strings: es,
      createTray,
      loadImage,
      buildMenu: (template) => template,
      actions: { open: vi.fn(), setBackupPaused: vi.fn(), installUpdate: vi.fn(), quit: vi.fn() },
    });
    const idle = trayModel({ lifecycle: "ready", activity: state(activityPayload()), update: null }, es);
    controller.render(idle);
    controller.render(idle);
    expect(createTray).toHaveBeenCalledExactlyOnceWith({ filePath: path.join("/res/tray", "tray-idle-linux.png") });
    expect(tray.on).toHaveBeenCalledWith("click", expect.any(Function));
    expect(tray.setContextMenu).toHaveBeenCalledTimes(1);
    controller.render(trayModel({ lifecycle: "ready", activity: state(activityPayload({ summary: "syncing" })), update: null }, es));
    expect(tray.setImage).toHaveBeenCalledWith({ filePath: path.join("/res/tray", "tray-syncing-linux.png") });
    expect(tray.setContextMenu).toHaveBeenCalledTimes(2);
    expect(tray.setToolTip).toHaveBeenLastCalledWith("Bento — Sincronizando…");
  });
});

describe("activity polling", () => {
  function monitorFixture(responses: Record<string, () => Response | Promise<Response>>) {
    const timers: Array<() => void> = [];
    const client = {
      apiFetch: vi.fn(async (pathname: string, init?: RequestInit) => {
        const key = `${init?.method ?? "GET"} ${pathname}`;
        const respond = responses[key];
        if (!respond) return new Response("not found", { status: 404 });
        return respond();
      }),
    };
    let ready = true;
    const monitor = new ActivityMonitor({
      client,
      isReady: () => ready,
      schedule: (callback, delay) => { expect(delay).toBe(5_000); timers.push(callback); return () => undefined; },
    });
    return { client, monitor, timers, setReady: (value: boolean) => { ready = value; } };
  }

  it("polls every 5 s through the authenticated client and reports a neutral state on 404", async () => {
    const { client, monitor, timers } = monitorFixture({});
    const states: ActivityState[] = [];
    monitor.on("state", (value: ActivityState) => states.push(value));
    monitor.start();
    await vi.waitFor(() => expect(timers).toHaveLength(1));
    expect(client.apiFetch.mock.calls.map(([pathname]) => pathname).sort()).toEqual(["/api/activity", "/api/backup/policy"]);
    expect(monitor.state).toEqual({ available: false, activity: null, policy: null });
    expect(states).toEqual([]);
  });

  it("parses activity and policy, emits only on change, and pauses while the system sleeps", async () => {
    let summary = "uploading";
    const { client, monitor, timers } = monitorFixture({
      "GET /api/activity": () => Response.json(activityPayload({ summary })),
      "GET /api/backup/policy": () => Response.json({ paused: false, effective_paused: false, on_battery: false }),
    });
    const listener = vi.fn();
    monitor.on("state", listener);
    monitor.start();
    await vi.waitFor(() => expect(timers).toHaveLength(1));
    expect(monitor.state.activity?.summary).toBe("uploading");
    expect(listener).toHaveBeenCalledTimes(1);

    timers.shift()!();
    await vi.waitFor(() => expect(timers).toHaveLength(1));
    expect(listener).toHaveBeenCalledTimes(1);

    monitor.suspend();
    const callsWhileAsleep = client.apiFetch.mock.calls.length;
    timers.shift()!();
    await Promise.resolve();
    expect(client.apiFetch.mock.calls.length).toBe(callsWhileAsleep);
    expect(monitor.isPolling).toBe(false);

    summary = "up_to_date";
    monitor.resume();
    await vi.waitFor(() => expect(monitor.state.activity?.summary).toBe("up_to_date"));
    expect(listener).toHaveBeenCalledTimes(2);
    monitor.stop();
  });

  it("skips requests while sidecars are not ready", async () => {
    const { client, monitor, setReady } = monitorFixture({});
    setReady(false);
    await monitor.refresh();
    expect(client.apiFetch).not.toHaveBeenCalled();
    expect(monitor.state.available).toBe(false);
  });

  it("pauses and resumes backup through PATCH /api/backup/policy", async () => {
    const { client, monitor } = monitorFixture({
      "PATCH /api/backup/policy": () => Response.json({ paused: true, effective_paused: true, on_battery: false }),
    });
    await expect(monitor.setPaused(true)).resolves.toEqual({ paused: true, effectivePaused: true, onBattery: false });
    const patch = client.apiFetch.mock.calls.find(([, init]) => init?.method === "PATCH")!;
    expect(patch[0]).toBe("/api/backup/policy");
    expect(JSON.parse(String(patch[1]!.body))).toEqual({ paused: true });
    expect(new Headers(patch[1]!.headers).get("content-type")).toBe("application/json");
  });

  it("bounds and sanitizes attention items", () => {
    const parsed = parseActivity(activityPayload({
      summary: "attention",
      attention: [
        { id: "ok-1", kind: "flood_wait", action: "none", params: { retry_after_seconds: 240 } },
        { id: "../../etc", kind: "upload_failed" },
        { id: "future", kind: "brand_new_kind", action: "launch_rockets" },
        ...Array.from({ length: 80 }, (_value, index) => ({ id: `bulk-${index}`, kind: "sync_error", action: "retry" })),
      ],
    }));
    expect(parsed?.attention[0]).toEqual({ id: "ok-1", kind: "flood_wait", action: "none", retryAfterSeconds: 240 });
    expect(parsed?.attention[1]).toEqual({ id: "future", kind: "unknown", action: "none" });
    expect(parsed?.attention.some((item) => item.id === "../../etc")).toBe(false);
    expect(parsed!.attention.length).toBeLessThanOrEqual(50);
  });
});
