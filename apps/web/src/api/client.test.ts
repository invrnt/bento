import { describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient, resolveApiBaseUrl } from "./client";

describe("api client", () => {
  it("normalizes the configured base URL", () => {
    expect(resolveApiBaseUrl("http://localhost:8000/api/")).toBe("http://localhost:8000/api");
    expect(resolveApiBaseUrl("")).toBe("/api");
  });

  it("requests JSON through the configured fetcher", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: { "content-type": "application/json" },
        status: 200,
      }),
    );
    const client = createApiClient({ baseUrl: "/api", fetcher });

    await expect(client.request<{ ok: boolean }>("/health")).resolves.toEqual({ ok: true });
    expect(fetcher).toHaveBeenCalledWith("/api/health", expect.objectContaining({ headers: expect.any(Headers) }));
  });

  it("marks every request as coming from the web client (the headless API's CSRF check)", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response("{}", { status: 200 }));
    const client = createApiClient({ baseUrl: "/api", fetcher });

    await client.request("/health");
    await client.request("/pairing/host", { method: "POST" });
    await client.request("/upload", { body: new FormData(), headers: { "x-bento-client": "other" }, method: "POST" });
    await client.request("/settings", { body: { a: 1 }, headers: new Headers({ accept: "application/json" }), method: "PATCH" });

    for (const [, init] of fetcher.mock.calls) {
      const headers = init?.headers as Headers;
      expect(headers.get("x-bento-client")).toBe("web");
    }
    expect((fetcher.mock.calls[3][1]?.headers as Headers).get("accept")).toBe("application/json");
  });

  it("serializes query parameters and omits empty values", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response("{}", { status: 200 }));
    const client = createApiClient({ baseUrl: "/api", fetcher });

    await client.request("/jobs", { query: { cursor: null, limit: 25, status: "failed" } });

    expect(fetcher).toHaveBeenCalledWith(
      "/api/jobs?limit=25&status=failed",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it("raises typed errors for failed responses", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ code: "bad_request" }), {
        headers: { "content-type": "application/json" },
        status: 400,
        statusText: "Bad Request",
      }),
    );
    const client = createApiClient({ baseUrl: "/api", fetcher });

    await expect(client.request("/broken")).rejects.toBeInstanceOf(ApiError);
  });
});
