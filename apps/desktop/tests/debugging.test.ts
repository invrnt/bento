import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { applicationMenuTemplate, debuggingSwitches } from "../src/main/debugging";

describe("packaged debugging lockdown", () => {
  it("finds remote debugging and inspector switches without reporting their values", () => {
    expect(debuggingSwitches(["/opt/Bento/bento", "--remote-debugging-port=9222", "--inspect", "--hidden"], undefined, "linux"))
      .toEqual(["remote-debugging-port", "inspect"]);
    expect(debuggingSwitches(["bento", "--remote-debugging-pipe", "--inspect-brk=0.0.0.0:9229", "-inspect-port=1"], undefined, "darwin"))
      .toEqual(["remote-debugging-pipe", "inspect-brk", "inspect-port"]);
    expect(debuggingSwitches(["bento.exe", "/remote-debugging-port=9222"], undefined, "win32")).toEqual(["remote-debugging-port"]);
    // Ordinary launches, deep links, files, and anything after `--` are not switches.
    expect(debuggingSwitches([
      "/opt/Bento/bento", "--hidden", "bento://join?v=1&c=K7Q2-MXR9-T4WA", "/remote-debugging-port=1", "/home/ana/inspect.pdf", "--inspector-notes", "--", "--inspect",
    ], undefined, "linux")).toEqual([]);
  });

  it("also trusts what Chromium already parsed", () => {
    expect(debuggingSwitches(["bento"], (name) => name === "remote-debugging-port", "linux")).toEqual(["remote-debugging-port"]);
  });

  it("builds an application menu without reload or developer tools", () => {
    for (const platform of ["darwin", "win32", "linux"] as const) {
      const template = applicationMenuTemplate(platform, { view: "Ver" });
      const serialized = JSON.stringify(template);
      for (const role of ["toggleDevTools", "reload", "forceReload", "viewMenu", "help"]) expect(serialized).not.toContain(`"${role}"`);
      expect(serialized).toContain('"editMenu"');
      expect(template.find((item) => item.label === "Ver")).toBeDefined();
      expect(serialized).toContain(platform === "darwin" ? '"appMenu"' : '"fileMenu"');
    }
  });

  it("wires the lockdown into the packaged main process", async () => {
    const source = await readFile(path.resolve(import.meta.dirname, "../src/main/index.ts"), "utf8");
    expect(source).toMatch(/const refusedSwitches = app\.isPackaged \? debuggingSwitches\(/u);
    expect(source).toContain("app.exit(1)");
    expect(source).toContain("Menu.setApplicationMenu(Menu.buildFromTemplate(applicationMenuTemplate(");
    expect(source).toContain("const devTools = !app.isPackaged;");
    expect(source.match(/createMainWindow\(\{[^}]*devTools/gu)).toHaveLength(2);
  });
});
