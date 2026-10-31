import path from "node:path";
import { pathToFileURL } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { argumentsFromAdditionalData, parseDeepLink, parseLaunchArguments, userArguments } from "../src/main/deep-links";
import { LaunchRouter } from "../src/main/launch-router";
import { RendererEventQueue } from "../src/main/renderer-events";
import { DeepLink } from "../src/shared/contracts";

const CODE = "K7Q2-MXR9-T4WA";

describe("bento:// deep link parsing", () => {
  it.each([
    [`bento://join?v=1&c=${CODE}`, CODE],
    [`bento://join/?v=1&c=${CODE}`, CODE],
    [`bento://join?c=${CODE}&v=1`, CODE],
    [`bento://join?v=1&c=${CODE.toLowerCase()}`, CODE],
    [`BENTO://join?v=1&c=${CODE}`, CODE],
    ["bento://join?v=1&c=K7Q2%2DMXR9%2DT4WA", CODE],
  ])("accepts %s", (link, code) => {
    expect(parseDeepLink(link)).toEqual({ kind: "join", code });
  });

  it.each([
    ["wrong scheme", `https://bento.example/join?v=1&c=${CODE}`],
    ["custom lookalike scheme", `bentox://join?v=1&c=${CODE}`],
    ["renderer origin", `bento://app/join?v=1&c=${CODE}`],
    ["unknown action", `bento://pair?v=1&c=${CODE}`],
    ["extra path", `bento://join/evil?v=1&c=${CODE}`],
    ["wrong version", `bento://join?v=2&c=${CODE}`],
    ["missing version", `bento://join?c=${CODE}`],
    ["duplicate code", `bento://join?v=1&c=${CODE}&c=AAAA-BBBB-CCCC`],
    ["extra parameter", `bento://join?v=1&c=${CODE}&next=https://evil.example`],
    ["fragment", `bento://join?v=1&c=${CODE}#x`],
    ["credentials", `bento://user:pass@join?v=1&c=${CODE}`],
    ["port", `bento://join:8080?v=1&c=${CODE}`],
    ["excluded Crockford letters", "bento://join?v=1&c=K7Q2-MXR9-T4WI"],
    ["U is not Crockford", "bento://join?v=1&c=UUUU-MXR9-T4WA"],
    ["short group", "bento://join?v=1&c=K7Q-MXR9-T4WA"],
    ["no dashes", "bento://join?v=1&c=K7Q2MXR9T4WA"],
    ["spaces", `bento://join?v=1&c=${CODE} `],
    ["control characters", `bento://join?v=1&c=${CODE}\n`],
    ["script", "bento://join?v=1&c=<script>alert(1)</script>"],
    ["oversized", `bento://join?v=1&c=${CODE}&pad=${"A".repeat(400)}`],
    ["empty", ""],
  ])("rejects %s", (_label, link) => {
    expect(parseDeepLink(link)).toBeNull();
  });

  it("rejects non-string input", () => {
    for (const value of [null, undefined, 42, { kind: "join", code: CODE }, [`bento://join?v=1&c=${CODE}`]]) {
      expect(parseDeepLink(value)).toBeNull();
    }
  });
});

describe("launch arguments", () => {
  const absolute = path.resolve("/tmp", "bento photo.jpg");

  it("drops the executable (and the dev app path) from argv", () => {
    expect(userArguments(["/opt/Bento/bento", "--hidden"], false)).toEqual(["--hidden"]);
    expect(userArguments(["/usr/bin/electron", ".", "--hidden"], true)).toEqual(["--hidden"]);
  });

  it("separates the hidden flag, deep links, and absolute files while ignoring switches", () => {
    const request = parseLaunchArguments([
      "--hidden",
      "--original-process-start-time=1",
      "--user-data-dir=/tmp/profile",
      "--",
      `bento://join?v=1&c=${CODE}`,
      absolute,
      pathToFileURL(absolute).toString(),
      "relative/file.txt",
      "file:///%00bad",
      42,
    ]);
    expect(request.hidden).toBe(true);
    expect(request.deepLinks).toEqual([`bento://join?v=1&c=${CODE}`]);
    expect(request.files).toEqual([absolute, absolute]);
  });

  it.skipIf(process.platform === "win32")("ignores remote file URLs on POSIX", () => {
    expect(parseLaunchArguments(["file://remote-host/share/file.txt"]).files).toEqual([]);
  });

  it("accepts only well-formed second-instance additional data", () => {
    expect(argumentsFromAdditionalData({ bento: 1, args: ["--hidden"] })).toEqual(["--hidden"]);
    for (const value of [null, [], { args: ["x"] }, { bento: 2, args: [] }, { bento: 1, args: [1] }, { bento: 1, args: "x" }]) {
      expect(argumentsFromAdditionalData(value)).toBeNull();
    }
    expect(argumentsFromAdditionalData({ bento: 1, args: new Array(10_001).fill("x") })).toBeNull();
  });
});

describe("cold start buffering", () => {
  it("buffers hand-offs that arrive before the desktop runtime is ready", () => {
    const router = new LaunchRouter();
    router.arguments([`bento://join?v=1&c=${CODE}`, "/tmp/a.jpg"]);
    router.deepLink("bento://join?v=9&c=nope");
    const handlers = { deepLink: vi.fn(), rejectedDeepLink: vi.fn(), files: vi.fn() };
    router.attach(handlers);
    expect(handlers.deepLink).toHaveBeenCalledWith({ kind: "join", code: CODE });
    expect(handlers.rejectedDeepLink).toHaveBeenCalledTimes(1);
    expect(handlers.files).toHaveBeenCalledWith(["/tmp/a.jpg"]);

    router.deepLink(`bento://join?v=1&c=${CODE}`);
    expect(handlers.deepLink).toHaveBeenCalledTimes(2);
  });

  it("bounds what it buffers before attach", () => {
    const router = new LaunchRouter();
    for (let index = 0; index < 50; index += 1) router.deepLink(`bento://join?v=1&c=${CODE}`);
    const handlers = { deepLink: vi.fn(), rejectedDeepLink: vi.fn(), files: vi.fn() };
    router.attach(handlers);
    expect(handlers.deepLink).toHaveBeenCalledTimes(16);
  });

  it("groups macOS open-file bursts into one batch", () => {
    const timers: Array<() => void> = [];
    const cancel = vi.fn();
    const router = new LaunchRouter({ schedule: (callback) => { timers.push(callback); return cancel; } });
    const handlers = { deepLink: vi.fn(), rejectedDeepLink: vi.fn(), files: vi.fn() };
    router.attach(handlers);
    router.openFile("/tmp/a.jpg");
    router.openFile("/tmp/b.jpg");
    expect(cancel).toHaveBeenCalledTimes(1);
    timers.at(-1)!();
    expect(handlers.files).toHaveBeenCalledExactlyOnceWith(["/tmp/a.jpg", "/tmp/b.jpg"]);
  });

  it("holds renderer events until the renderer subscribes, then delivers each once", () => {
    const queue = new RendererEventQueue<DeepLink>("bento:deep-link");
    queue.push({ kind: "join", code: CODE });
    queue.push({ kind: "join", code: CODE });
    queue.push({ kind: "join", code: "AAAA-BBBB-CCCC" });
    expect(queue.pending).toHaveLength(2);
    const target = { send: vi.fn(), isDestroyed: () => false };
    queue.subscribe(target);
    expect(target.send.mock.calls).toEqual([
      ["bento:deep-link", { kind: "join", code: CODE }],
      ["bento:deep-link", { kind: "join", code: "AAAA-BBBB-CCCC" }],
    ]);
    queue.push({ kind: "join", code: "DDDD-EEEE-FFFF" });
    expect(target.send).toHaveBeenCalledTimes(3);

    // A reload drops the subscription until the new document subscribes again.
    queue.reset();
    queue.push({ kind: "join", code: "GGGG-HHHH-JJJJ" });
    expect(target.send).toHaveBeenCalledTimes(3);
    const reloaded = { send: vi.fn(), isDestroyed: () => false };
    queue.subscribe(reloaded);
    expect(reloaded.send).toHaveBeenCalledExactlyOnceWith("bento:deep-link", { kind: "join", code: "GGGG-HHHH-JJJJ" });

    queue.unsubscribe(target);
    expect(queue.subscribed).toBe(true);
    queue.unsubscribe(reloaded);
    expect(queue.subscribed).toBe(false);
  });

  it("does not send to a destroyed renderer and caps the buffer", () => {
    const queue = new RendererEventQueue<{ id: number }>("bento:navigate", 3);
    let destroyed = false;
    const target = { send: vi.fn(), isDestroyed: () => destroyed };
    queue.subscribe(target);
    destroyed = true;
    for (let id = 0; id < 5; id += 1) queue.push({ id });
    expect(target.send).not.toHaveBeenCalled();
    expect(queue.pending).toEqual([{ id: 2 }, { id: 3 }, { id: 4 }]);
  });
});
