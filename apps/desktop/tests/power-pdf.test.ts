import { EventEmitter } from "node:events";
import { mkdtemp, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PdfSaver, pdfFileName, writeFileAtomic } from "../src/main/pdf";
import { PowerReporter } from "../src/main/power";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

class FakePowerMonitor extends EventEmitter {
  battery = false;
  isOnBatteryPower(): boolean { return this.battery; }
}

describe("power reporting", () => {
  function fixture(status = 200) {
    const monitor = new FakePowerMonitor();
    const bodies: unknown[] = [];
    const client = {
      apiFetch: vi.fn(async (pathname: string, init: RequestInit = {}) => {
        expect(pathname).toBe("/api/backup/power");
        expect(init.method).toBe("POST");
        bodies.push(JSON.parse(String(init.body)));
        return new Response("{}", { status });
      }),
    };
    const polls: Array<() => void> = [];
    let ready = true;
    const reporter = new PowerReporter({
      monitor,
      client,
      isReady: () => ready,
      schedule: (callback) => { polls.push(callback); return () => undefined; },
    });
    return { bodies, client, monitor, polls, reporter, setReady: (value: boolean) => { ready = value; } };
  }

  it("reports the initial state and every battery/AC transition once", async () => {
    const { bodies, monitor, reporter } = fixture();
    monitor.battery = true;
    reporter.start();
    await vi.waitFor(() => expect(bodies).toEqual([{ on_battery: true }]));
    monitor.emit("on-battery");
    monitor.emit("on-ac");
    await vi.waitFor(() => expect(bodies).toEqual([{ on_battery: true }, { on_battery: false }]));
    reporter.stop();
    monitor.emit("on-battery");
    await Promise.resolve();
    expect(bodies).toHaveLength(2);
  });

  it("polls for changes on platforms without power events", async () => {
    const { bodies, monitor, polls, reporter } = fixture();
    reporter.start();
    await vi.waitFor(() => expect(polls).toHaveLength(1));
    monitor.battery = true;
    polls.shift()!();
    await vi.waitFor(() => expect(bodies).toEqual([{ on_battery: false }, { on_battery: true }]));
  });

  it("retries when the endpoint is unavailable and re-reports after an API restart", async () => {
    const unavailable = fixture(404);
    await unavailable.reporter.report(false);
    await unavailable.reporter.report(false);
    expect(unavailable.client.apiFetch).toHaveBeenCalledTimes(2);
    expect(unavailable.reporter.reported).toBeNull();

    const { bodies, reporter, setReady } = fixture();
    setReady(false);
    await reporter.report(true);
    expect(bodies).toEqual([]);
    setReady(true);
    await reporter.report(false);
    await reporter.apiRestarted();
    expect(bodies).toEqual([{ on_battery: false }, { on_battery: false }]);
  });
});

describe("recovery kit PDF saving", () => {
  async function fixture(dialogResult: (defaultPath: string) => { canceled: boolean; filePath?: string }) {
    const root = await mkdtemp(path.join(os.tmpdir(), "bento-pdf-"));
    roots.push(root);
    const pdfBytes = Buffer.from("%PDF-1.7 recovery kit");
    const mainFrame = { processId: 7, routingId: 1, parent: null };
    const webContents = { mainFrame, printToPDF: vi.fn(async () => pdfBytes) };
    const window = { webContents, isDestroyed: () => false };
    const showSaveDialog = vi.fn(async (_window: unknown, options: { defaultPath: string }) => dialogResult(options.defaultPath));
    const saver = new PdfSaver({
      window: () => window,
      documentsDirectory: () => root,
      defaultFileName: "Kit de recuperación de Bento.pdf",
      dialogTitle: "Guardar kit de recuperación",
      filterName: "Documento PDF",
      showSaveDialog,
    });
    const trusted = { sender: webContents, senderFrame: { ...mainFrame } };
    return { pdfBytes, root, saver, showSaveDialog, trusted, webContents };
  }

  it("prints the main window to A4 with backgrounds and writes the chosen file atomically", async () => {
    const { pdfBytes, root, saver, showSaveDialog, trusted, webContents } = await fixture((defaultPath) => ({ canceled: false, filePath: defaultPath }));
    const expected = Buffer.from(pdfBytes);
    await expect(saver.save(trusted, {})).resolves.toEqual({ saved: true, fileName: "Kit de recuperación de Bento.pdf" });
    expect(webContents.printToPDF).toHaveBeenCalledWith({ printBackground: true, pageSize: "A4" });
    expect(showSaveDialog.mock.calls[0]?.[1]).toMatchObject({
      defaultPath: path.join(root, "Kit de recuperación de Bento.pdf"),
      filters: [{ name: "Documento PDF", extensions: ["pdf"] }],
    });
    const written = path.join(root, "Kit de recuperación de Bento.pdf");
    expect(await readFile(written)).toEqual(expected);
    if (process.platform !== "win32") expect((await stat(written)).mode & 0o777).toBe(0o600);
    expect((await readdir(root)).filter((name) => name.endsWith(".tmp"))).toEqual([]);
    // The in-memory copy of the recovery kit is wiped after saving.
    expect(pdfBytes.every((byte) => byte === 0)).toBe(true);
  });

  it("uses a sanitized suggestion and appends the .pdf extension", async () => {
    const { root, saver, showSaveDialog, trusted } = await fixture((defaultPath) => ({ canceled: false, filePath: defaultPath.replace(/\.pdf$/u, "") }));
    await expect(saver.save(trusted, { suggestedName: "Mi kit" })).resolves.toEqual({ saved: true, fileName: "Mi kit.pdf" });
    expect(showSaveDialog.mock.calls[0]?.[1].defaultPath).toBe(path.join(root, "Mi kit.pdf"));
    expect(pdfFileName(undefined, "Fallback.pdf")).toBe("Fallback.pdf");
    expect(pdfFileName("Kit.PDF", "x")).toBe("Kit.PDF");
  });

  it("never replaces an existing file the dialog did not confirm after appending .pdf", async () => {
    const { root, saver, trusted } = await fixture((defaultPath) => ({ canceled: false, filePath: defaultPath.replace(/\.pdf$/u, "") }));
    await writeFile(path.join(root, "Mi kit.pdf"), "existing kit");
    await writeFile(path.join(root, "Mi kit (2).pdf"), "second kit");
    await expect(saver.save(trusted, { suggestedName: "Mi kit" })).resolves.toEqual({ saved: true, fileName: "Mi kit (3).pdf" });
    expect(await readFile(path.join(root, "Mi kit.pdf"), "utf8")).toBe("existing kit");
    expect(await readFile(path.join(root, "Mi kit (2).pdf"), "utf8")).toBe("second kit");
    expect(await readFile(path.join(root, "Mi kit (3).pdf"), "utf8")).toBe("%PDF-1.7 recovery kit");
    if (process.platform !== "win32") expect((await stat(path.join(root, "Mi kit (3).pdf"))).mode & 0o777).toBe(0o600);
    expect((await readdir(root)).filter((name) => name.endsWith(".tmp"))).toEqual([]);
  });

  it("still replaces a .pdf path the dialog confirmed", async () => {
    const { root, saver, trusted } = await fixture((defaultPath) => ({ canceled: false, filePath: defaultPath }));
    await writeFile(path.join(root, "Kit de recuperación de Bento.pdf"), "old kit");
    await expect(saver.save(trusted, {})).resolves.toEqual({ saved: true, fileName: "Kit de recuperación de Bento.pdf" });
    expect(await readFile(path.join(root, "Kit de recuperación de Bento.pdf"), "utf8")).toBe("%PDF-1.7 recovery kit");
  });

  it("writes nothing when the dialog is canceled", async () => {
    const { root, saver, trusted } = await fixture(() => ({ canceled: true }));
    await expect(saver.save(trusted, {})).resolves.toEqual({ saved: false });
    expect(await readdir(root)).toEqual([]);
  });

  it.each([
    ["another webContents", (trusted: { sender: unknown; senderFrame: object }) => ({ ...trusted, sender: {} })],
    ["a subframe", (trusted: { sender: unknown; senderFrame: object }) => ({ ...trusted, senderFrame: { processId: 7, routingId: 2, parent: {} } })],
    ["a frame from another process", (trusted: { sender: unknown; senderFrame: object }) => ({ ...trusted, senderFrame: { processId: 8, routingId: 1, parent: null } })],
    ["a missing frame", (trusted: { sender: unknown; senderFrame: object }) => ({ ...trusted, senderFrame: null })],
  ])("refuses requests from %s before printing", async (_label, mutate) => {
    const { saver, showSaveDialog, trusted, webContents } = await fixture(() => ({ canceled: true }));
    await expect(saver.save(mutate(trusted) as never, {})).rejects.toThrow(/main window/u);
    expect(webContents.printToPDF).not.toHaveBeenCalled();
    expect(showSaveDialog).not.toHaveBeenCalled();
  });

  it("refuses concurrent saves and rejects unsafe dialog results", async () => {
    let finish!: (value: { canceled: boolean; filePath?: string }) => void;
    const { saver, trusted } = await fixture(() => ({ canceled: true }));
    const pending = new PdfSaver({
      window: () => ({ webContents: trusted.sender as never, isDestroyed: () => false }),
      documentsDirectory: () => os.tmpdir(),
      defaultFileName: "Kit.pdf",
      dialogTitle: "t",
      filterName: "PDF",
      showSaveDialog: () => new Promise((resolve) => { finish = resolve; }),
    });
    const first = pending.save(trusted, {});
    await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
    await expect(pending.save(trusted, {})).rejects.toThrow("pdf_save_in_progress");
    finish({ canceled: false, filePath: "relative/kit.pdf" });
    await expect(first).rejects.toThrow(TypeError);
    await expect(saver.save(trusted, {})).resolves.toEqual({ saved: false });
  });

  it("refuses to replace an existing file in exclusive mode", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "bento-pdf-exclusive-"));
    roots.push(root);
    const target = path.join(root, "kit.pdf");
    await writeFileAtomic(target, Buffer.from("old"), { exclusive: true });
    await expect(writeFileAtomic(target, Buffer.from("new"), { exclusive: true })).rejects.toMatchObject({ code: "EEXIST" });
    expect(await readFile(target, "utf8")).toBe("old");
    expect(await readdir(root)).toEqual(["kit.pdf"]);
  });

  it("replaces an existing file through a same-directory temporary file", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "bento-pdf-atomic-"));
    roots.push(root);
    const target = path.join(root, "kit.pdf");
    await writeFileAtomic(target, Buffer.from("old"));
    await writeFileAtomic(target, Buffer.from("new"));
    expect(await readFile(target, "utf8")).toBe("new");
    expect(await readdir(root)).toEqual(["kit.pdf"]);
  });
});
