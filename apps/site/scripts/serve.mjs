// Local preview of dist/ with the same _headers (CSP included) and Pages-style routing.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { headersFor, parseHeaders } from "./lib/headers.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const port = Number(process.env.PORT ?? 8788);
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};
const rules = parseHeaders(await readFile(path.join(dist, "_headers"), "utf8"));

async function isFile(file) {
  try {
    return (await stat(file)).isFile();
  } catch {
    return false;
  }
}

createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  let pathname = decodeURIComponent(url.pathname);
  if (pathname.includes("\0") || pathname.split("/").includes("..")) {
    response.writeHead(400).end();
    return;
  }
  if (!pathname.endsWith("/") && !path.extname(pathname) && (await isFile(path.join(dist, pathname, "index.html")))) {
    response.writeHead(308, { Location: `${pathname}/${url.search}` }).end();
    return;
  }
  let file = path.join(dist, pathname.endsWith("/") ? `${pathname}index.html` : pathname);
  let status = 200;
  if (pathname === "/_headers" || !(await isFile(file))) {
    file = path.join(dist, "404.html");
    status = 404;
    pathname = "/404.html";
  }
  const headers = { "Content-Type": types[path.extname(file)] ?? "application/octet-stream", ...headersFor(rules, pathname) };
  response.writeHead(status, headers).end(await readFile(file));
}).listen(port, "127.0.0.1", () => {
  console.log(`Bento site preview on http://127.0.0.1:${port}/ (Ctrl+C to stop)`);
});
