import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { mountJoinPage } from "../src/assets/join.js";
import { detectPlatform } from "../src/assets/platform.js";
import { tags } from "./lib/html.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// Minimal DOM double built from the real page markup: only what join.js touches.
class FakeElement {
  constructor(name, attrs) {
    this.name = name;
    this.attrs = { ...attrs };
    this.hidden = "hidden" in attrs;
    this.textContent = "";
    this.listeners = {};
  }
  getAttribute(name) {
    return name in this.attrs ? this.attrs[name] : null;
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }
  addEventListener(type, listener) {
    (this.listeners[type] ??= []).push(listener);
  }
  async click() {
    for (const listener of this.listeners.click ?? []) await listener();
  }
}

async function loadPage(relative) {
  const html = await readFile(path.join(root, "src", relative), "utf8");
  const elements = tags(html).map((tag) => new FakeElement(tag.name, tag.attrs));
  const select = (selector) => {
    const attribute = /^\[([a-z-]+)\]$/u.exec(selector)?.[1];
    if (!attribute) throw new Error(`Unsupported selector ${selector}`);
    return elements.filter((element) => attribute in element.attrs);
  };
  return {
    elements,
    querySelectorAll: select,
    querySelector: (selector) => select(selector)[0] ?? null,
  };
}

for (const [label, page, otherLanguage] of [
  ["Spanish", "join/index.html", "/en/join/"],
  ["English", "en/join/index.html", "/join/"],
]) {
  describe(`${label} join page`, () => {
    it("shows the normalized code, the deep link and keeps the fragment on the language switch", async () => {
      const doc = await loadPage(page);
      const result = mountJoinPage(doc, "#v=1&c=k7q2-mxr9-t4wa", { writeText: async () => {} });
      assert.equal(result.status, "ok");
      const visible = doc.querySelectorAll("[data-join-state]").filter((element) => !element.hidden);
      assert.deepEqual(visible.map((element) => element.getAttribute("data-join-state")), ["ok"]);
      assert.equal(doc.querySelector("[data-join-code]").textContent, "K7Q2-MXR9-T4WA");
      assert.equal(doc.querySelector("[data-join-open]").getAttribute("href"), "bento://join?v=1&c=K7Q2-MXR9-T4WA");
      assert.equal(doc.querySelector("[data-keep-fragment]").getAttribute("href"), `${otherLanguage}#v=1&c=K7Q2-MXR9-T4WA`);
      assert.equal(doc.querySelector("[data-join-copy]").hidden, false);
    });

    it("copies the code locally and announces it", async () => {
      const doc = await loadPage(page);
      const copied = [];
      mountJoinPage(doc, "#v=1&c=K7Q2-MXR9-T4WA", { writeText: async (text) => copied.push(text) });
      await doc.querySelector("[data-join-copy]").click();
      assert.deepEqual(copied, ["K7Q2-MXR9-T4WA"]);
      const status = doc.querySelector("[data-join-copy-status]");
      assert.equal(status.textContent, status.getAttribute("data-copied"));
      assert.ok(status.textContent.length > 0);
    });

    it("hides the copy button without a clipboard and reports copy failures", async () => {
      const withoutClipboard = await loadPage(page);
      mountJoinPage(withoutClipboard, "#v=1&c=K7Q2-MXR9-T4WA", undefined);
      assert.equal(withoutClipboard.querySelector("[data-join-copy]").hidden, true);

      const failing = await loadPage(page);
      mountJoinPage(failing, "#v=1&c=K7Q2-MXR9-T4WA", { writeText: async () => { throw new Error("denied"); } });
      await failing.querySelector("[data-join-copy]").click();
      const status = failing.querySelector("[data-join-copy-status]");
      assert.equal(status.textContent, status.getAttribute("data-copy-failed"));
    });

    for (const [hash, state] of [["", "missing"], ["#v=1&c=NOPE", "invalid"], ["#v=9&c=K7Q2-MXR9-T4WA", "unsupported"]]) {
      it(`shows the ${state} state and never builds a deep link with a code`, async () => {
        const doc = await loadPage(page);
        mountJoinPage(doc, hash, { writeText: async () => {} });
        const visible = doc.querySelectorAll("[data-join-state]").filter((element) => !element.hidden);
        assert.deepEqual(visible.map((element) => element.getAttribute("data-join-state")), [state]);
        assert.equal(doc.querySelector("[data-join-open]").getAttribute("href"), "bento://join");
        assert.equal(doc.querySelector("[data-join-code]").textContent, "");
        assert.equal(doc.querySelector("[data-keep-fragment]").getAttribute("href"), otherLanguage);
        assert.equal(doc.querySelector("[data-join-copy]").hidden, true);
      });
    }

    it("shows desktop help and hides the Android install block in the static markup", async () => {
      const doc = await loadPage(page);
      const sections = doc.querySelectorAll("[data-platform]");
      assert.ok(sections.some((element) => element.getAttribute("data-platform") === "android"));
      for (const element of sections) {
        assert.equal(element.hidden, element.getAttribute("data-platform") === "android", element.getAttribute("data-platform"));
      }
    });

    it("on Android swaps the desktop help for \"Instala Bento\" and keeps the code and the app link", async () => {
      const doc = await loadPage(page);
      mountJoinPage(doc, "#v=1&c=K7Q2-MXR9-T4WA", { writeText: async () => {} }, "android");
      const visible = doc.querySelectorAll("[data-platform]").filter((element) => !element.hidden);
      assert.ok(visible.length >= 2);
      assert.ok(visible.every((element) => element.getAttribute("data-platform") === "android"));
      assert.equal(doc.querySelector("[data-join-code]").textContent, "K7Q2-MXR9-T4WA");
      assert.equal(doc.querySelector("[data-join-open]").getAttribute("href"), "bento://join?v=1&c=K7Q2-MXR9-T4WA");
      const install = doc.querySelectorAll("[data-android-asset]");
      assert.deepEqual(install.map((element) => element.getAttribute("data-android-asset")), ["android-arm64"]);
      assert.ok(install[0].getAttribute("href").startsWith("https://github.com/invrnt/bento/releases/"));
    });

    it("offers the Android install block even without a valid code", async () => {
      const doc = await loadPage(page);
      mountJoinPage(doc, "", undefined, "android");
      const install = doc.elements.find((element) => element.getAttribute("data-platform") === "android" && element.name === "section");
      assert.equal(install.hidden, false);
      assert.equal(doc.querySelector("[data-join-open]").getAttribute("href"), "bento://join");
    });

    it("on desktop keeps the desktop help unchanged", async () => {
      const doc = await loadPage(page);
      mountJoinPage(doc, "#v=1&c=K7Q2-MXR9-T4WA", undefined, "desktop");
      for (const element of doc.querySelectorAll("[data-platform]")) {
        assert.equal(element.hidden, element.getAttribute("data-platform") !== "desktop");
      }
    });

    it("never puts the code in a link other than the app link and the language switch", async () => {
      for (const platform of ["android", "desktop"]) {
        const doc = await loadPage(page);
        mountJoinPage(doc, "#v=1&c=K7Q2-MXR9-T4WA", undefined, platform);
        const carriers = doc.elements.filter((element) => (element.getAttribute("href") ?? "").includes("K7Q2"));
        assert.deepEqual(
          carriers.map((element) => ("data-join-open" in element.attrs ? "open" : "data-keep-fragment" in element.attrs ? "lang" : element.name)).sort(),
          ["lang", "open"],
        );
      }
    });

    it("has a section for every parser state", async () => {
      const doc = await loadPage(page);
      const states = doc.querySelectorAll("[data-join-state]").map((element) => element.getAttribute("data-join-state"));
      assert.deepEqual(states.sort(), ["invalid", "missing", "ok", "unsupported"]);
    });
  });
}

describe("platform detection (progressive enhancement)", () => {
  const cases = [
    ["Pixel Chrome", { userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 7a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36" }, "android"],
    ["Samsung Internet", { userAgent: "Mozilla/5.0 (Linux; Android 13; SM-A356B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/26.0 Chrome/122.0.0.0 Mobile Safari/537.36" }, "android"],
    ["Firefox for Android", { userAgent: "Mozilla/5.0 (Android 14; Mobile; rv:132.0) Gecko/132.0 Firefox/132.0" }, "android"],
    ["Chrome reduced UA with client hints", { userAgent: "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36", userAgentData: { platform: "Android", mobile: true } }, "android"],
    ["UA says Android, hints do not (overridden UA)", { userAgent: "Mozilla/5.0 (Linux; Android 10; K)", userAgentData: { platform: "Linux" } }, "android"],
    ["hints say Android, UA does not (desktop mode)", { userAgent: "Mozilla/5.0 (X11; Linux x86_64)", userAgentData: { platform: "Android" } }, "android"],
    ["empty client-hint platform falls back to the UA", { userAgent: "Mozilla/5.0 (Linux; Android 10; K)", userAgentData: { platform: "" } }, "android"],
    ["desktop Chrome on Linux", { userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", userAgentData: { platform: "Linux" } }, "desktop"],
    ["Windows Edge", { userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0" }, "desktop"],
    ["iPhone Safari", { userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1" }, "desktop"],
    ["no navigator", undefined, "desktop"],
    ["no user agent", {}, "desktop"],
  ];
  for (const [label, nav, expected] of cases) {
    it(`${label} → ${expected}`, () => assert.equal(detectPlatform(nav), expected));
  }
});
