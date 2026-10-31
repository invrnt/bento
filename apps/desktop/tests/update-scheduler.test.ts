import { readdir } from "node:fs/promises";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UPDATE_CHECK_INTERVAL_MS, UpdateScheduler } from "../src/main/update-scheduler";
import { cleanupUpdateFixtures, FixtureOptions, setup } from "./support/update-fixture";

afterEach(cleanupUpdateFixtures);

async function scheduled(options: FixtureOptions = {}, autoDownload = true) {
  const fixture = await setup(options);
  const timers: Array<{ callback: () => void; delay: number }> = [];
  let auto = autoDownload;
  const statuses: string[] = [];
  fixture.controller.on("state", (state: { status: string }) => statuses.push(state.status));
  const scheduler = new UpdateScheduler({
    updates: fixture.controller,
    autoDownload: () => auto,
    schedule: (callback, delay) => { timers.push({ callback, delay }); return () => undefined; },
  });
  return { ...fixture, scheduler, statuses, timers, setAuto: (value: boolean) => { auto = value; } };
}

describe("background update scheduling", () => {
  it("checks at startup, then downloads and verifies automatically into a ready state", async () => {
    const { controller, fetch, scheduler, statuses, timers, autoUpdater, openPath } = await scheduled();
    await scheduler.start();
    expect(statuses).toEqual(expect.arrayContaining(["checking", "available", "downloading", "downloaded"]));
    expect(statuses.indexOf("available")).toBeLessThan(statuses.indexOf("downloaded"));
    expect(controller.state).toMatchObject({ status: "downloaded", availableVersion: "0.2.0", progress: { percent: 100 } });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(timers).toEqual([{ callback: expect.any(Function), delay: UPDATE_CHECK_INTERVAL_MS }]);
    expect(UPDATE_CHECK_INTERVAL_MS).toBe(6 * 60 * 60 * 1000);
    // Installation stays an explicit user action.
    expect(autoUpdater.quitAndInstall).not.toHaveBeenCalled();
    expect(openPath).not.toHaveBeenCalled();
  });

  it("only checks metadata when automatic downloads are off, and downloads once re-enabled", async () => {
    const { controller, fetch, scheduler, setAuto } = await scheduled({}, false);
    await scheduler.start();
    expect(controller.state.status).toBe("available");
    expect(fetch).toHaveBeenCalledTimes(2);
    setAuto(true);
    await scheduler.autoDownloadChanged();
    expect(controller.state.status).toBe("downloaded");
  });

  it.each([
    ["package checksum mismatch", { corruptArtifactDigest: true }],
    ["manifest checksum mismatch", { corruptManifestDigest: true }],
    ["missing digest", { omitArtifactDigest: true }],
  ])("fails closed on %s without staging anything, then retries on the next cycle", async (_label, options) => {
    const { controller, root, scheduler, timers } = await scheduled(options);
    await scheduler.start();
    expect(controller.state.status).toBe("error");
    expect(controller.state.error?.code).toMatch(/^updates_[a-z_]+$/u);
    const staged = await readdir(root, { recursive: true }).catch(() => []);
    expect(staged.filter((name) => String(name).endsWith(".deb"))).toEqual([]);
    expect(timers).toHaveLength(1);
    timers[0]!.callback();
    await vi.waitFor(() => expect(timers).toHaveLength(2));
    expect(controller.state.status).toBe("error");
  });

  it("keeps a verified download across a later check of the same release", async () => {
    const { controller, fetch, scheduler, timers } = await scheduled();
    await scheduler.start();
    fetch.mockClear();
    timers[0]!.callback();
    await vi.waitFor(() => expect(timers).toHaveLength(2));
    expect(controller.state.status).toBe("downloaded");
    // Metadata only: the staged package is not downloaded again.
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("never throws when the controller rejects or is busy", async () => {
    const updates = {
      state: { status: "idle" as const, installMode: "manual" as const, currentVersion: "0.1.0" },
      initialize: vi.fn(async () => updates.state),
      check: vi.fn(async () => { throw new Error("updates_operation_in_progress"); }),
      download: vi.fn(),
    };
    const scheduler = new UpdateScheduler({ updates, autoDownload: () => true, schedule: () => () => undefined });
    await expect(scheduler.start()).resolves.toBeUndefined();
    expect(updates.download).not.toHaveBeenCalled();
    scheduler.stop();
  });

  it("does not overlap a download that is already running", async () => {
    const updates = {
      state: { status: "downloading" as const, installMode: "automatic" as const, currentVersion: "0.1.0" },
      initialize: vi.fn(async () => updates.state),
      check: vi.fn(),
      download: vi.fn(),
    };
    const scheduler = new UpdateScheduler({ updates, autoDownload: () => true, schedule: () => () => undefined });
    await scheduler.runCycle();
    expect(updates.check).not.toHaveBeenCalled();
  });
});
