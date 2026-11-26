// IndexNow: the key file in the build, the payload, and the best-effort ping.
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "../scripts/build.mjs";
import { submitIndexNow } from "../scripts/indexnow.mjs";
import { INDEXNOW_ENDPOINT, indexableUrls, indexNowPayload, validateIndexNowKey } from "../scripts/lib/seo.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const KEY = "0123456789abcdef0123456789abcdef";

describe("indexnow", () => {
  it("serves the configured key at /<key>.txt with the key as its only content", async () => {
    const { indexNowKey } = JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8"));
    assert.ok(indexNowKey, "indexNowKey must be configured");
    assert.equal(await readFile(path.join(root, "dist", `${indexNowKey}.txt`), "utf8"), indexNowKey);
  });

  it("validates the key and emits no key file without an origin", async () => {
    assert.equal(validateIndexNowKey(undefined), null);
    assert.equal(validateIndexNowKey(KEY), KEY);
    for (const bad of ["short", "has space here", "../../etc/passwd", "x".repeat(129), 42]) {
      assert.throws(() => validateIndexNowKey(bad), /indexNowKey/u);
    }
    const config = JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8"));
    const output = await mkdtemp(path.join(tmpdir(), "bento-site-indexnow-"));
    try {
      await build({ output, config: { ...config, origin: null, indexNowKey: KEY } });
      await assert.rejects(readFile(path.join(output, `${KEY}.txt`), "utf8"));
      await assert.rejects(build({ output, config: { ...config, indexNowKey: "bad key" } }), /indexNowKey/u);
    } finally {
      await rm(output, { recursive: true, force: true });
    }
  });

  it("submits exactly the sitemap pages for the origin's host", async () => {
    const payload = indexNowPayload("https://bento.example", KEY);
    assert.deepEqual(payload, {
      host: "bento.example",
      key: KEY,
      keyLocation: `https://bento.example/${KEY}.txt`,
      urlList: indexableUrls("https://bento.example"),
    });
    assert.ok(payload.urlList.includes("https://bento.example/en/android/"));
    assert.ok(!payload.urlList.some((url) => url.includes("/join")));
    const sitemap = await readFile(path.join(root, "dist", "sitemap.xml"), "utf8");
    const { origin } = JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8"));
    const locs = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/gu)].map((match) => match[1]);
    assert.deepEqual(locs, indexableUrls(origin));
  });

  it("posts JSON to the IndexNow endpoint and reports the response", async () => {
    const calls = [];
    const fetchImpl = async (url, init) => {
      calls.push({ url, init });
      return { status: calls.length === 1 ? 202 : 403 };
    };
    const accepted = await submitIndexNow({ origin: "https://bento.example", key: KEY, fetchImpl });
    assert.equal(calls[0].url, INDEXNOW_ENDPOINT);
    assert.equal(calls[0].init.method, "POST");
    assert.deepEqual(JSON.parse(calls[0].init.body), indexNowPayload("https://bento.example", KEY));
    assert.equal(accepted.ok, true);
    const rejected = await submitIndexNow({ origin: "https://bento.example", key: KEY, fetchImpl });
    assert.equal(rejected.ok, false);
    assert.equal(rejected.status, 403);
  });
});
