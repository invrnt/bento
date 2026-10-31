// /join page behaviour. The pairing code lives in the URL fragment (after "#"), which
// browsers never send to a server. This script reads it locally, shows it, and builds the
// bento:// link. It makes no network requests and stores nothing.
import { parseJoinFragment } from "./join-code.js";

export function mountJoinPage(doc, hash, clipboard) {
  const parsed = parseJoinFragment(hash);

  for (const section of doc.querySelectorAll("[data-join-state]")) {
    section.hidden = section.getAttribute("data-join-state") !== parsed.status;
  }

  const code = parsed.status === "ok" ? parsed.code : "";
  for (const element of doc.querySelectorAll("[data-join-code]")) element.textContent = code;
  for (const element of doc.querySelectorAll("[data-join-open]")) {
    element.setAttribute("href", parsed.status === "ok" ? parsed.appLink : "bento://join");
  }

  // The language switch keeps the code local by carrying the fragment to the other page.
  for (const link of doc.querySelectorAll("[data-keep-fragment]")) {
    const base = (link.getAttribute("href") ?? "").split("#")[0];
    link.setAttribute("href", parsed.status === "ok" ? `${base}#v=1&c=${parsed.code}` : base);
  }

  const status = doc.querySelector("[data-join-copy-status]");
  for (const button of doc.querySelectorAll("[data-join-copy]")) {
    const canCopy = parsed.status === "ok" && typeof clipboard?.writeText === "function";
    button.hidden = !canCopy;
    if (!canCopy || button.getAttribute("data-bound") === "true") continue;
    button.setAttribute("data-bound", "true");
    button.addEventListener("click", async () => {
      const current = doc.querySelector("[data-join-code]")?.textContent ?? "";
      if (!current) return;
      try {
        await clipboard.writeText(current);
        if (status) status.textContent = status.getAttribute("data-copied") ?? "";
      } catch {
        if (status) status.textContent = status.getAttribute("data-copy-failed") ?? "";
      }
    });
  }

  return parsed;
}

if (typeof document !== "undefined" && typeof location !== "undefined") {
  const run = () => mountJoinPage(document, location.hash, globalThis.navigator?.clipboard);
  run();
  globalThis.addEventListener("hashchange", run);
}
