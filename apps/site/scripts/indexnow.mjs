// Tells IndexNow search engines (Bing, Yandex, Seznam, Naver…) that the indexable pages changed.
// Runs after `npm run deploy`; best effort: a failed ping is reported but never fails the deploy.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { INDEXNOW_ENDPOINT, indexNowPayload, validateIndexNowKey } from "./lib/seo.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const STATUS = {
  200: "accepted",
  202: "accepted, key validation pending",
  400: "bad request",
  403: "key not valid (is /<key>.txt deployed?)",
  422: "URLs do not belong to the host or the key does not match",
  429: "too many requests",
};

export async function submitIndexNow({ origin, key, fetchImpl = fetch }) {
  const payload = indexNowPayload(origin, key);
  const response = await fetchImpl(INDEXNOW_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify(payload),
  });
  const ok = response.status === 200 || response.status === 202;
  return { ok, status: response.status, detail: STATUS[response.status] ?? "unexpected response", urls: payload.urlList.length };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const config = JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8"));
  const key = validateIndexNowKey(config.indexNowKey);
  if (!config.origin || !key) {
    console.log("IndexNow: skipped (origin or indexNowKey not set in site.config.json).");
  } else {
    try {
      const result = await submitIndexNow({ origin: config.origin, key });
      const line = `IndexNow: ${result.urls} URLs → HTTP ${result.status} (${result.detail}).`;
      if (result.ok) console.log(line);
      else console.warn(`${line} The deploy itself succeeded.`);
    } catch (error) {
      console.warn(`IndexNow: ping failed (${error.message}). The deploy itself succeeded.`);
    }
  }
}
