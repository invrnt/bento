import path from "node:path";
import { pathToFileURL } from "node:url";
import { describe, expect, it, vi } from "vitest";

const electron = vi.hoisted(() => ({ netFetch: vi.fn() }));
vi.mock("electron", () => ({ net: { fetch: electron.netFetch } }));

import { API_CSP, CSP, isAllowedNavigation, registerBentoProtocol } from "../src/main/protocol";

function setup() {
  let handler: ((request: Request) => Promise<Response>) | undefined;
  const protocol = { handle: vi.fn((_scheme: string, value: typeof handler) => { handler = value; }) };
  const api = { apiFetch: vi.fn(async () => new Response("api", { status: 200 })) };
  registerBentoProtocol(protocol as never, "/opt/bento/renderer", api);
  return { api, handler: handler!, protocol };
}

const rendererRootUrl = pathToFileURL(path.resolve("/opt/bento/renderer")).toString();

describe("bento protocol", () => {
  it.each([
    ["bento://app/", true],
    ["bento://app/settings", true],
    ["https://app/settings", false],
    ["bento://evil/settings", false],
    ["bento://user:password@app/settings", false],
    ["file:///opt/bento/renderer/index.html", false],
    ["javascript:alert(1)", false],
    ["not a URL", false],
  ])("navigation allowlist: %s => %s", (url, expected) => {
    expect(isAllowedNavigation(url)).toBe(expected);
  });

  it("rejects other hosts without touching disk or API", async () => {
    const { api, handler } = setup();
    await expect(handler(new Request("bento://evil/index.html"))).resolves.toMatchObject({ status: 404 });
    expect(api.apiFetch).not.toHaveBeenCalled();
    expect(electron.netFetch).not.toHaveBeenCalled();
  });

  it("proxies only /api and strips renderer-controlled credentials", async () => {
    const { api, handler } = setup();
    await handler(new Request("bento://app/api/settings/values?view=public", {
      headers: {
        authorization: "Bearer attacker-value",
        cookie: "session=attacker",
        origin: "https://attacker.example",
        "x-safe-header": "kept",
      },
    }));

    expect(api.apiFetch).toHaveBeenCalledOnce();
    const [pathname, init] = api.apiFetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(pathname).toBe("/api/settings/values?view=public");
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("cookie")).toBeNull();
    expect(headers.get("origin")).toBeNull();
    expect(headers.get("x-safe-header")).toBe("kept");
  });

  it("pins nosniff and a restrictive CSP on proxied API responses", async () => {
    const { api, handler } = setup();
    api.apiFetch.mockResolvedValueOnce(new Response("<script>alert(1)</script>", {
      status: 200,
      headers: { "content-type": "text/html", "content-security-policy": "default-src *", "set-cookie": "a=b", refresh: "0;url=https://x" },
    }));
    const response = await handler(new Request("bento://app/api/assets/1/content"));
    expect(response.status).toBe(200);
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("content-security-policy")).toBe(API_CSP);
    expect(API_CSP).toContain("default-src 'none'");
    expect(API_CSP).toContain("sandbox");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("refresh")).toBeNull();
    expect(response.headers.get("content-type")).toBe("text/html");
    expect(await response.text()).toBe("<script>alert(1)</script>");

    api.apiFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(handler(new Request("bento://app/api/x", { method: "DELETE" }))).resolves.toMatchObject({ status: 204 });
  });

  it("never hands a redirect to the renderer", async () => {
    const { api, handler } = setup();
    for (const status of [301, 302, 303, 307, 308]) {
      api.apiFetch.mockResolvedValueOnce(new Response(null, { status, headers: { location: "https://attacker.example/" } }));
      const response = await handler(new Request("bento://app/api/redirect"));
      expect(response.status).toBe(502);
      expect(response.headers.get("location")).toBeNull();
      expect(response.headers.get("x-content-type-options")).toBe("nosniff");
      expect(await response.json()).toEqual({ detail: { code: "desktop_api_redirect_blocked", message: "Request rejected" } });
    }
    // The loopback client refuses to follow redirects (`redirect: "error"`); that failure is a 503.
    api.apiFetch.mockRejectedValueOnce(new TypeError("fetch failed: unexpected redirect"));
    const failed = await handler(new Request("bento://app/api/redirect"));
    expect(failed.status).toBe(503);
    expect(failed.headers.get("content-security-policy")).toBe(API_CSP);
  });

  it("serves renderer files with strict response security headers", async () => {
    const { handler } = setup();
    electron.netFetch.mockResolvedValueOnce(new Response("asset", { status: 200, headers: { "content-type": "text/javascript" } }));
    const response = await handler(new Request("bento://app/assets/app.js"));
    expect(electron.netFetch).toHaveBeenCalledWith(new URL("assets/app.js", `${rendererRootUrl}/`).toString());
    expect(response.headers.get("content-security-policy")).toBe(CSP);
    expect(response.headers.get("cross-origin-opener-policy")).toBe("same-origin");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
  });

  it("uses index.html for client routes and does not resolve traversal outside renderer root", async () => {
    const { handler } = setup();
    electron.netFetch.mockResolvedValue(new Response("index", { status: 200 }));
    await handler(new Request("bento://app/settings/general"));
    expect(electron.netFetch).toHaveBeenLastCalledWith(new URL("index.html", `${rendererRootUrl}/`).toString());

    for (const pathname of ["/%2e%2e/%2e%2e/etc/passwd", "/..%2f..%2fetc/passwd", "/%00/asset.js"]) {
      electron.netFetch.mockClear();
      await handler(new Request(`bento://app${pathname}`));
      for (const [fileUrl] of electron.netFetch.mock.calls) {
        expect(fileUrl).toMatch(new RegExp(`^${escapeRegExp(`${rendererRootUrl}/`)}`, "u"));
        expect(fileUrl).not.toBe(`file://${path.join("etc", "passwd")}`);
      }
    }
  });
});

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
}
