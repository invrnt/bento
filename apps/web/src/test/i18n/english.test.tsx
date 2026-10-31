import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { en, es, messageKeys } from "../../i18n/dictionary";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

describe("English dictionary", () => {
  it("translates every Spanish key", () => {
    const missing = messageKeys().filter((key) => !en[key]?.trim());
    expect(missing).toEqual([]);
  });

  it("keeps the same placeholders as Spanish", () => {
    const mismatched = messageKeys().filter((key) => placeholders(es[key]).join() !== placeholders(en[key] ?? "").join());
    expect(mismatched).toEqual([]);
  });

  it("does not leave Spanish sentences untranslated", () => {
    const suspicious = messageKeys().filter((key) => {
      const value = en[key] ?? "";
      return value === es[key] && /[áéíóúñ¿¡]|\b(el|la|los|las|de|del|que|para|con|una?)\b/i.test(value);
    });
    expect(suspicious).toEqual([]);
  });
});

describe("App in English", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.resetModules();
    Object.defineProperty(window.navigator, "language", { configurable: true, value: "es-ES" });
    window.history.pushState({}, "", "/");
  });

  async function loadEnglish() {
    Object.defineProperty(window.navigator, "language", { configurable: true, value: "en-US" });
    vi.resetModules();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => jsonResponse(responseFor(String(input)))));
    return {
      App: (await import("../../app/App")).App,
      ActivityPage: (await import("../../features/activity/ActivityPage")).ActivityPage,
      createActivityStore: (await import("../../features/activity/activityStore")).createActivityStore,
      TrashPage: (await import("../../features/trash/TrashPage")).TrashPage,
    };
  }

  it("renders the shell, Drive and status in English when the locale is en", async () => {
    const { App } = await loadEnglish();
    window.history.pushState({}, "", "/drive");

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Drive" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    for (const label of ["Photos", "Albums", "Favorites", "Documents", "Jobs", "Trash", "Settings"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("searchbox", { name: "Global search" })).toHaveAttribute("placeholder", "Search photos, files and text…");
    expect(await screen.findAllByRole("button", { name: "Upload files" })).not.toHaveLength(0);
    expect(screen.getByRole("heading", { name: "Empty folder" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import from Telegram…" })).toBeInTheDocument();
    // The same status shows in the top-bar pill and the sidebar footer.
    expect(await screen.findAllByText("All up to date")).not.toHaveLength(0);
    expectNoSpanishCopy();
  });

  it("renders Activity and Trash in English", async () => {
    const { ActivityPage, createActivityStore, TrashPage } = await loadEnglish();
    const store = createActivityStore(async () => ({
      attention: [{ action: "save_recovery_kit", id: "kit", kind: "recovery_kit", params: {}, title_key: "" }],
      downloads: { active: 0, bytes_done: 0, bytes_total: 0, eta_seconds: null, queued: 0 },
      summary: "uploading",
      uploads: { active: 1, bytes_done: 1024, bytes_total: 4096, eta_seconds: 180, queued: 11 },
    }));

    const activity = render(
      <ActivityPage
        api={{
          getBackupPolicy: async () => ({ bandwidth_limit_kbps: 0, effective_paused: false, on_battery: false, pause_on_battery: true, paused: false }),
          retryJob: vi.fn(),
          syncNow: vi.fn(),
          updateBackupPolicy: vi.fn(),
        }}
        store={store}
      />,
    );
    expect(await screen.findByRole("heading", { name: "Uploading 12 files · 3 min" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Pause backup" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save kit" })).toBeInTheDocument();
    expectNoSpanishCopy();
    activity.unmount();

    render(
      <TrashPage
        api={{
          empty: vi.fn(),
          list: async () => ({
            items: [
              {
                deleted_at: "2026-10-20T10:00:00Z",
                id: "a",
                name: "invoice.pdf",
                purge_at: "2026-11-19T10:00:00Z",
                size_bytes: 1536,
                thumbnail_url: null,
                type: "asset",
              },
            ],
            next_cursor: null,
          }),
          purge: vi.fn(),
          restore: vi.fn(),
        }}
        now={new Date("2026-10-31T12:00:00Z")}
      />,
    );
    expect(await screen.findByRole("button", { name: "Empty trash" })).toBeInTheDocument();
    expect(screen.getAllByText("Deletes on November 19")).not.toHaveLength(0);
    expect(screen.getByText(/Deleted on October 20/)).toBeInTheDocument();
    expectNoSpanishCopy();
  });
});

/** Fails when any visible text or accessible label is a Spanish string that has its own English translation. */
function expectNoSpanishCopy() {
  const spanishOnly = new Set<string>(
    messageKeys()
      .filter((key) => en[key] && en[key] !== es[key] && !es[key].includes("{"))
      .map((key) => es[key]),
  );
  const leaks = new Set<string>();

  for (const element of Array.from(document.body.querySelectorAll<HTMLElement>("*"))) {
    for (const value of [element.getAttribute("aria-label"), element.getAttribute("placeholder"), element.getAttribute("title")]) {
      if (value && spanishOnly.has(value)) leaks.add(value);
    }
    for (const node of Array.from(element.childNodes)) {
      const text = node.nodeType === Node.TEXT_NODE ? node.textContent?.trim() : null;
      if (text && spanishOnly.has(text)) leaks.add(text);
    }
  }

  expect([...leaks]).toEqual([]);
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" }, status: 200 });
}

function responseFor(url: string): unknown {
  if (url.includes("/drive/items")) return { breadcrumbs: [], items: [], next_cursor: null };
  if (url.includes("/activity")) return { attention: [], downloads: {}, summary: "up_to_date", uploads: {} };
  if (url.includes("/account")) return { account: null, error: null, password_hint: null, qr: null, qr_expires_at: null, qr_url: null, step: "signed_out" };
  if (url.includes("/vault")) return { created_at: null, devices_count: 1, other_vaults: 0, reason: null, recovery_kit_saved: false, recovery_kit_stale: false, state: "local_only", usage: { bytes: 0, files: 0 }, vault_id: null };
  if (url.includes("/drive/folders")) return { items: [] };
  return {};
}
