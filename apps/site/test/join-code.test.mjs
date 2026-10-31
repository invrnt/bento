import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { appLinkFor, CANONICAL_CODE, normalizeCode, parseJoinFragment } from "../src/assets/join-code.js";

describe("normalizeCode", () => {
  it("keeps canonical codes", () => {
    assert.equal(normalizeCode("K7Q2-MXR9-T4WA"), "K7Q2-MXR9-T4WA");
  });

  it("upper-cases and ignores spaces and dashes", () => {
    assert.equal(normalizeCode("k7q2 mxr9 t4wa"), "K7Q2-MXR9-T4WA");
    assert.equal(normalizeCode("k7q2mxr9t4wa"), "K7Q2-MXR9-T4WA");
    assert.equal(normalizeCode("  K7Q2--MXR9 - T4WA "), "K7Q2-MXR9-T4WA");
  });

  it("maps the Crockford aliases O→0 and I/L→1 like the app", () => {
    assert.equal(normalizeCode("KOQ2-MXRI-T4WL"), "K0Q2-MXR1-T4W1");
    assert.equal(normalizeCode("koq2-mxri-t4wl"), "K0Q2-MXR1-T4W1");
  });

  it("rejects characters outside the alphabet", () => {
    assert.equal(normalizeCode("K7Q2-MXR9-T4WU"), null); // U is not Crockford
    assert.equal(normalizeCode("K7Q2-MXR9-T4W!"), null);
    assert.equal(normalizeCode("K7Q2-MXR9-T4WÁ"), null);
    assert.equal(normalizeCode("K7Q2_MXR9_T4WA"), null);
    assert.equal(normalizeCode("<script>alert(1)</script>"), null);
  });

  it("rejects wrong lengths and non-strings", () => {
    assert.equal(normalizeCode("K7Q2-MXR9"), null);
    assert.equal(normalizeCode("K7Q2-MXR9-T4WA-0000"), null);
    assert.equal(normalizeCode(""), null);
    assert.equal(normalizeCode("A".repeat(41)), null);
    assert.equal(normalizeCode(undefined), null);
    assert.equal(normalizeCode(123456789012), null);
  });
});

describe("parseJoinFragment", () => {
  it("parses the web link fragment the app produces", () => {
    assert.deepEqual(parseJoinFragment("#v=1&c=K7Q2-MXR9-T4WA"), {
      status: "ok",
      code: "K7Q2-MXR9-T4WA",
      appLink: "bento://join?v=1&c=K7Q2-MXR9-T4WA",
    });
  });

  it("normalizes the code before building the deep link", () => {
    const parsed = parseJoinFragment("#v=1&c=k7q2+mxr9+t4wa");
    assert.equal(parsed.status, "ok");
    assert.equal(parsed.code, "K7Q2-MXR9-T4WA");
    assert.match(parsed.appLink, /^bento:\/\/join\?v=1&c=[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/u);
  });

  it("accepts percent-encoding, a missing version, extra parameters and a bare code", () => {
    assert.equal(parseJoinFragment("#v=1&c=K7Q2%2DMXR9%2DT4WA").code, "K7Q2-MXR9-T4WA");
    assert.equal(parseJoinFragment("#c=K7Q2-MXR9-T4WA").code, "K7Q2-MXR9-T4WA");
    assert.equal(parseJoinFragment("#v=1&c=K7Q2-MXR9-T4WA&utm=x").code, "K7Q2-MXR9-T4WA");
    assert.equal(parseJoinFragment("#K7Q2-MXR9-T4WA").code, "K7Q2-MXR9-T4WA");
    assert.equal(parseJoinFragment("v=1&c=K7Q2-MXR9-T4WA").code, "K7Q2-MXR9-T4WA");
  });

  it("reports a missing code", () => {
    assert.deepEqual(parseJoinFragment(""), { status: "missing" });
    assert.deepEqual(parseJoinFragment("#"), { status: "missing" });
    assert.deepEqual(parseJoinFragment("#v=1"), { status: "missing" });
    assert.deepEqual(parseJoinFragment("#v=1&c="), { status: "missing" });
    assert.deepEqual(parseJoinFragment(undefined), { status: "missing" });
  });

  it("reports links from newer versions", () => {
    assert.deepEqual(parseJoinFragment("#v=2&c=K7Q2-MXR9-T4WA"), { status: "unsupported" });
  });

  it("rejects invalid, ambiguous and hostile fragments", () => {
    for (const hash of [
      "#v=1&c=K7Q2-MXR9",
      "#v=1&c=K7Q2-MXR9-T4WU",
      "#v=abc&c=K7Q2-MXR9-T4WA",
      "#v=1&c=K7Q2-MXR9-T4WA&c=0000-0000-0000",
      "#v=1&v=2&c=K7Q2-MXR9-T4WA",
      "#v=1&c=%3Cscript%3E",
      "#v=1&c=javascript:alert(1)",
      "#%E0%A4%A",
      `#v=1&c=K7Q2-MXR9-T4WA&pad=${"x".repeat(300)}`,
    ]) {
      assert.deepEqual(parseJoinFragment(hash), { status: "invalid" }, hash);
    }
  });
});

describe("appLinkFor", () => {
  it("only accepts canonical codes", () => {
    assert.equal(appLinkFor("K7Q2-MXR9-T4WA"), "bento://join?v=1&c=K7Q2-MXR9-T4WA");
    assert.throws(() => appLinkFor("k7q2-mxr9-t4wa"), TypeError);
    assert.throws(() => appLinkFor("K7Q2-MXR9-T4WA&x=1"), TypeError);
  });

  it("matches the desktop deep-link pattern", () => {
    assert.equal(CANONICAL_CODE.source, "^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$");
  });
});
