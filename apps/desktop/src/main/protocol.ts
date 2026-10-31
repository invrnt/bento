import { net, Protocol } from "electron";
import { extname, isAbsolute, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { BENTO_ORIGIN } from "../shared/contracts";

const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'",
  "media-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

/** API responses are data, never documents: nothing in them may run, frame, or be sniffed. */
const API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; sandbox";
const NULL_BODY_STATUSES = new Set([204, 205, 304]);

interface ApiProxy {
  apiFetch(pathname: string, init?: RequestInit): Promise<Response>;
}

export function registerBentoProtocol(protocol: Protocol, rendererRoot: string, api: ApiProxy): void {
  protocol.handle("bento", async (request) => {
    const url = new URL(request.url);
    if (url.host !== "app") return new Response("Not found", { status: 404 });
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      const headers = new Headers(request.headers);
      headers.delete("authorization");
      headers.delete("cookie");
      headers.delete("origin");
      let response: Response;
      try {
        response = await api.apiFetch(`${url.pathname}${url.search}`, {
          method: request.method,
          headers,
          body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
          // Chromium's ReadableStream request body requires this Node fetch extension.
          duplex: request.body ? "half" : undefined,
        } as RequestInit);
      } catch {
        // Includes redirects, which the loopback client refuses to follow.
        return apiProxyError(503, "desktop_api_unavailable");
      }
      return hardenApiResponse(response);
    }

    const decoded = safeDecode(url.pathname);
    const requested = decoded === "/" ? "index.html" : decoded.replace(/^\/+/, "");
    let filePath = resolve(rendererRoot, requested);
    if (!safeDescendant(rendererRoot, filePath)) return new Response("Bad request", { status: 400 });
    if (!extname(requested)) filePath = resolve(rendererRoot, "index.html");
    if (!safeDescendant(rendererRoot, filePath)) return new Response("Bad request", { status: 400 });
    const response = await net.fetch(pathToFileURL(filePath).toString());
    const headers = new Headers(response.headers);
    headers.set("Content-Security-Policy", CSP);
    headers.set("Cross-Origin-Opener-Policy", "same-origin");
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("Referrer-Policy", "no-referrer");
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  });
}

/** Never hand the renderer a redirect (it would follow it) and pin safe response headers. */
export function hardenApiResponse(response: Response): Response {
  if (response.status >= 300 && response.status < 400 && response.status !== 304) {
    void response.body?.cancel().catch(() => undefined);
    return apiProxyError(502, "desktop_api_redirect_blocked");
  }
  const headers = new Headers(response.headers);
  headers.delete("location");
  headers.delete("refresh");
  headers.delete("set-cookie");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Content-Security-Policy", API_CSP);
  headers.set("Referrer-Policy", "no-referrer");
  const body = NULL_BODY_STATUSES.has(response.status) ? null : response.body;
  return new Response(body, { status: response.status, statusText: response.statusText, headers });
}

function apiProxyError(status: number, code: string): Response {
  return new Response(JSON.stringify({ detail: { code, message: "Request rejected" } }), {
    status,
    headers: {
      "Content-Type": "application/json",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": API_CSP,
      "Cache-Control": "no-store",
    },
  });
}

export function isAllowedNavigation(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "bento:" && url.host === "app" && url.username === "" && url.password === "";
  } catch {
    return false;
  }
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return "/invalid";
  }
}

function safeDescendant(root: string, candidate: string): boolean {
  const child = relative(resolve(root), candidate);
  return child !== "" && !child.startsWith("..") && !isAbsolute(child);
}

export { API_CSP, BENTO_ORIGIN, CSP };
