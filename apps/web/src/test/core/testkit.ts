import { vi } from "vitest";

import { createApiClient } from "../../api/client";
import type { QrMatrix } from "../../api/qr";
import type { BentoDesktopBridge } from "../../api/settingsDesktop";

export type FakeRequest = { body: unknown; method: string; path: string; query: URLSearchParams };
export type Route = unknown | ((request: FakeRequest) => unknown);

/** Throw from a route to answer with the API error model. */
export class FakeHttpError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(code);
  }
}

/** In-memory API: `"GET /vault"` or `"POST /pairing/:id/approve"` keys mapped to values or handlers. */
export function fakeApi(initial: Record<string, Route> = {}) {
  const routes = new Map<string, Route>(Object.entries(initial));
  const calls: Array<{ body: unknown; method: string; path: string }> = [];

  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://bento.test");
    const path = url.pathname.replace(/^\/api/, "");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ body, method, path });
    const route = findRoute(routes, method, path);
    if (route === undefined) return json(404, { error: { code: "not_found", message: `${method} ${path}` } });
    try {
      const value = typeof route === "function" ? await (route as (request: FakeRequest) => unknown)({ body, method, path, query: url.searchParams }) : route;
      return json(200, value);
    } catch (caught) {
      if (caught instanceof FakeHttpError) {
        return json(caught.status, { error: { code: caught.code, details: caught.details, message: caught.code } });
      }
      throw caught;
    }
  }) as typeof fetch;

  return {
    calls,
    callsTo: (key: string) => calls.filter((call) => `${call.method} ${call.path}` === key),
    client: createApiClient({ baseUrl: "/api", fetcher }),
    fetcher,
    on: (key: string, route: Route) => routes.set(key, route),
  };
}

/** A route that answers each value once, then keeps answering the last one. */
export function sequence(...values: unknown[]): () => unknown {
  let index = 0;
  return () => {
    const value = values[Math.min(index, values.length - 1)];
    index += 1;
    if (value instanceof FakeHttpError) throw value;
    return value;
  };
}

function findRoute(routes: Map<string, Route>, method: string, path: string): Route | undefined {
  const exact = routes.get(`${method} ${path}`);
  if (exact !== undefined) return exact;
  for (const [key, route] of routes) {
    const [routeMethod, routePath] = key.split(" ");
    if (routeMethod !== method) continue;
    const pattern = new RegExp(`^${routePath.replace(/:[a-z_]+/gi, "[^/]+")}$`);
    if (pattern.test(path)) return route;
  }
  return undefined;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" }, status });
}

/** Node's own webstorage shadows jsdom's `localStorage` (undefined without a file): give tests a real one. */
export function installMemoryStorage(): Storage {
  const data = new Map<string, string>();
  const storage: Storage = {
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    get length() {
      return data.size;
    },
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
  return storage;
}

export const qrMatrix: QrMatrix = {
  rows: ["11100", "10101", "11100", "00011", "10111"],
  size: 5,
};

type BridgeExtras = Record<string, unknown>;

/** A desktop bridge with the Stage 16 members; pass overrides for what the test checks. */
export function installBridge(extras: BridgeExtras = {}) {
  const bridge = {
    lifecycle: { onStatus: vi.fn(() => vi.fn()), status: vi.fn() },
    onDeepLink: vi.fn(() => vi.fn()),
    onNavigate: vi.fn(() => vi.fn()),
    pickDirectory: vi.fn(async () => ({ canceled: true })),
    pickFile: vi.fn(),
    platform: vi.fn(async () => ({ arch: "x64", desktop: true, locale: "es-CO", platform: "linux", recoveryMode: false, secureStorage: "os", version: "2.0.0" })),
    preferences: {
      get: vi.fn(async () => ({ autoDownloadUpdates: true, keepRunningInBackground: true, launchAtLogin: false })),
      set: vi.fn(async (patch: Record<string, boolean>) => ({ autoDownloadUpdates: true, keepRunningInBackground: true, launchAtLogin: false, ...patch })),
    },
    savePageAsPdf: vi.fn(async () => ({ fileName: "Kit de recuperación de Bento.pdf", saved: true })),
    settings: { apply: vi.fn(async () => ({ ok: true, revision: 2 })), onProgress: vi.fn(() => vi.fn()), probe: vi.fn() },
    ...extras,
  };
  window.bento = bridge as unknown as BentoDesktopBridge;
  return bridge;
}

export function removeBridge() {
  delete window.bento;
}

export const recoveryCode = "K7QM-3XRA-9TPW-HHM2-ZX4D-8C1V-QQ7N-WMB3-R2KD";
