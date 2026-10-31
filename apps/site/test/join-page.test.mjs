import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { mountJoinPage } from "../src/assets/join.js";
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

    it("has a section for every parser state", async () => {
      const doc = await loadPage(page);
      const states = doc.querySelectorAll("[data-join-state]").map((element) => element.getAttribute("data-join-state"));
      assert.deepEqual(states.sort(), ["invalid", "missing", "ok", "unsupported"]);
    });
  });
}
