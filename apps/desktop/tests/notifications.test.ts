import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AttentionItem } from "../src/main/activity";
import { createStrings } from "../src/main/i18n";
import { attentionTarget, DesktopNotifier, NotificationOptions } from "../src/main/notifications";
import { DesktopStateStore } from "../src/main/preferences";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function fixture(options: { quiet?: boolean; supported?: boolean; locale?: string } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "bento-notify-"));
  roots.push(root);
  const memory = new DesktopStateStore(path.join(root, "preferences.json"));
  await memory.load();
  const shown: Array<NotificationOptions & { click(): void }> = [];
  const activate = vi.fn();
  const create = vi.fn((notificationOptions: NotificationOptions) => {
    const listeners = new Map<string, () => void>();
    const notification = {
      on: (event: string, listener: () => void) => { listeners.set(event, listener); return notification; },
      show: () => shown.push({ ...notificationOptions, click: () => listeners.get("click")?.() }),
    };
    return notification;
  });
  const notifier = new DesktopNotifier({
    platform: "linux",
    strings: createStrings([options.locale ?? "es-ES"]),
    supported: () => options.supported ?? true,
    create,
    memory,
    activate,
    quiet: () => options.quiet ?? false,
    icon: "/res/tray/notification.png",
  });
  return { activate, create, memory, notifier, root, shown };
}

const item = (id: string, kind: AttentionItem["kind"] = "upload_failed", action: AttentionItem["action"] = "retry"): AttentionItem => ({ id, kind, action });

describe("native notifications", () => {
  it("notifies once per new attention item id, across polls and restarts", async () => {
    const { notifier, shown, root } = await fixture();
    await notifier.attention([item("a1")]);
    await notifier.attention([item("a1")]);
    await notifier.attention([item("a1"), item("r1", "recovery_kit", "save_recovery_kit")]);
    expect(shown.map((entry) => entry.title)).toEqual(["No se pudo subir un archivo", "Guarda tu kit de recuperación"]);
    expect(shown[0]).toMatchObject({ body: "Abre Bento para revisarlo.", icon: "/res/tray/notification.png" });

    const restarted = new DesktopStateStore(path.join(root, "preferences.json"));
    await restarted.load();
    const again = new DesktopNotifier({
      platform: "linux", strings: createStrings(["es"]), supported: () => true, create: vi.fn(), memory: restarted, activate: vi.fn(),
    });
    await again.attention([item("a1"), item("r1", "recovery_kit")]);
    expect(shown).toHaveLength(2);
  });

  it("routes clicks to the matching renderer target", async () => {
    const { activate, notifier, shown } = await fixture();
    await notifier.attention([item("k1", "recovery_kit", "save_recovery_kit"), item("s1", "sync_error", "open_settings")]);
    shown[0]!.click();
    shown[1]!.click();
    expect(activate.mock.calls).toEqual([
      [{ target: "recovery-kit", attentionId: "k1" }],
      [{ target: "settings", attentionId: "s1" }],
    ]);
    expect(attentionTarget({ kind: "inbox_failed", action: "retry" })).toBe("activity");
  });

  it("summarizes bursts and shows flood waits in minutes", async () => {
    const { notifier, shown } = await fixture();
    await notifier.attention([{ id: "f1", kind: "flood_wait", action: "none", retryAfterSeconds: 230 }]);
    expect(shown.at(-1)?.title).toBe("Telegram pidió esperar 4 min");
    await notifier.attention([item("b1"), item("b2"), item("b3")]);
    expect(shown.at(-1)?.title).toBe("Bento tiene 3 avisos para ti");
    expect(shown).toHaveLength(2);
  });

  it("stays quiet while the window is focused but still marks items as seen", async () => {
    const { notifier, shown, memory } = await fixture({ quiet: true });
    await notifier.attention([item("q1")]);
    expect(shown).toHaveLength(0);
    expect(memory.notifiedAttentionIds.has("q1")).toBe(true);
  });

  it("reports Send-to results with plural-aware copy", async () => {
    const { activate, notifier, shown } = await fixture();
    notifier.sendToSummary({ added: 1, failed: 0, rejected: 0 });
    notifier.sendToSummary({ added: 12000, failed: 2, rejected: 1 });
    notifier.sendToSummary({ added: 0, failed: 0, rejected: 2 });
    notifier.sendToSummary({ added: 0, failed: 0, rejected: 0 });
    expect(shown.map((entry) => [entry.title, entry.body])).toEqual([
      ["1 archivo añadido a Bento", ""],
      ["12.000 archivos añadidos a Bento", "3 archivos no se pudieron añadir."],
      ["No se pudieron añadir los archivos", "2 archivos no se pudieron añadir."],
    ]);
    shown[0]!.click();
    expect(activate).toHaveBeenCalledWith({ target: "drive" });
  });

  it("shows the background notice only once", async () => {
    const { notifier, shown } = await fixture({ locale: "en-GB" });
    await notifier.backgroundNotice();
    await notifier.backgroundNotice();
    expect(shown).toHaveLength(1);
    expect(shown[0]).toMatchObject({ title: "Bento keeps running in the background", silent: true });
    shown[0]!.click();
  });

  it("does nothing when the OS does not support notifications", async () => {
    const { create, notifier } = await fixture({ supported: false });
    await notifier.attention([item("n1")]);
    notifier.sendToSummary({ added: 2, failed: 0, rejected: 0 });
    expect(create).not.toHaveBeenCalled();
  });
});
