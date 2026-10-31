import { generateKeyPairSync } from "node:crypto";
import { afterEach, describe, expect, it } from "vitest";
import {
  encodeUpdatePublicKey,
  encodeUpdateSignature,
  parseUpdatePublicKey,
  signUpdateManifest,
  updateKeyId,
  verifyUpdateManifestSignature,
} from "../src/main/update-signature";
import { cleanupUpdateFixtures, setup } from "./support/update-fixture";

afterEach(cleanupUpdateFixtures);

const manifest = Buffer.from('{"schemaVersion":1,"version":"0.2.0"}\n');

function keyPair() {
  const pair = generateKeyPairSync("ed25519");
  return { ...pair, encoded: encodeUpdatePublicKey(pair.publicKey) };
}

describe("update manifest signatures", () => {
  it("accepts only canonical base64 of a raw 32-byte Ed25519 public key", () => {
    const { encoded, publicKey } = keyPair();
    expect(encoded).toMatch(/^[A-Za-z0-9+/]{43}=$/u);
    expect(updateKeyId(parseUpdatePublicKey(encoded)!)).toBe(updateKeyId(publicKey));
    for (const invalid of ["", "abc", encoded.slice(0, -1), `${encoded}=`, Buffer.alloc(31).toString("base64"), Buffer.alloc(33).toString("base64"), encoded.replace(/=$/u, ""), Buffer.from(encoded, "base64").toString("base64url")]) {
      expect(parseUpdatePublicKey(invalid)).toBeNull();
    }
  });

  it("verifies the exact manifest bytes with the embedded key", () => {
    const signer = keyPair();
    const signature = Buffer.from(encodeUpdateSignature(signUpdateManifest(manifest, [signer.privateKey])));
    expect(verifyUpdateManifestSignature(manifest, signature, signer.publicKey)).toBe(true);
    expect(verifyUpdateManifestSignature(Buffer.concat([manifest, Buffer.from(" ")]), signature, signer.publicKey)).toBe(false);
    expect(verifyUpdateManifestSignature(manifest, signature, keyPair().publicKey)).toBe(false);
  });

  it("supports dual-signed rotation releases", () => {
    const previous = keyPair();
    const next = keyPair();
    const signature = Buffer.from(encodeUpdateSignature(signUpdateManifest(manifest, [previous.privateKey, next.privateKey])));
    expect(verifyUpdateManifestSignature(manifest, signature, previous.publicKey)).toBe(true);
    expect(verifyUpdateManifestSignature(manifest, signature, next.publicKey)).toBe(true);
  });

  it("rejects malformed or relabelled signature documents", () => {
    const signer = keyPair();
    const document = signUpdateManifest(manifest, [signer.privateKey]);
    const encode = (value: unknown) => Buffer.from(JSON.stringify(value));
    const [entry] = document.signatures;
    const otherSignature = signUpdateManifest(manifest, [keyPair().privateKey]).signatures[0]!.signature;
    for (const candidate of [
      Buffer.alloc(0),
      Buffer.from("not json"),
      Buffer.from([0xff, 0xfe]),
      encode({ ...document, schemaVersion: 2 }),
      encode({ ...document, algorithm: "rsa" }),
      encode({ ...document, extra: true }),
      encode({ ...document, signatures: [] }),
      encode({ ...document, signatures: Array.from({ length: 5 }, () => entry) }),
      encode({ ...document, signatures: [{ ...entry, keyId: "zz" }] }),
      encode({ ...document, signatures: [{ ...entry, signature: otherSignature }] }),
      encode({ ...document, signatures: [{ keyId: entry!.keyId, signature: entry!.signature, note: "x" }] }),
      Buffer.alloc(5000, 32),
    ]) expect(verifyUpdateManifestSignature(manifest, candidate, signer.publicKey)).toBe(false);
  });

  it("refuses non-Ed25519 or missing signing keys", () => {
    expect(() => signUpdateManifest(manifest, [])).toThrow();
    expect(() => signUpdateManifest(manifest, [keyPair().publicKey])).toThrow();
    const { privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
    expect(() => signUpdateManifest(manifest, [privateKey])).toThrow();
  });
});

describe("updater signature enforcement", () => {
  it("accepts a release whose manifest carries a valid signature by the embedded key", async () => {
    const signer = keyPair();
    const fixture = await setup({ signWith: [signer.privateKey], updatePublicKey: signer.encoded });
    expect(await fixture.controller.check()).toMatchObject({ status: "available", availableVersion: "0.2.0" });
    expect(fixture.fetch.mock.calls.map((call) => String(call[0]))).toContain(fixture.signatureUrl);
    expect((await fixture.controller.download()).status).toBe("downloaded");
    expect(fixture.warn).not.toHaveBeenCalled();
  });

  it("fails closed on a missing, foreign, tampered, or digest-mismatched signature", async () => {
    const signer = keyPair();
    const cases = [
      [{}, "updates_signature_missing"],
      [{ signWith: [keyPair().privateKey] }, "updates_signature_invalid"],
      [{ signatureBytes: Buffer.from('{"schemaVersion":1}') }, "updates_signature_invalid"],
      [{ signWith: [signer.privateKey], corruptSignatureDigest: true }, "updates_signature_invalid"],
    ] as const;
    for (const [options, code] of cases) {
      const fixture = await setup({ ...options, updatePublicKey: signer.encoded });
      const state = await fixture.controller.check();
      expect(state).toMatchObject({ status: "error", error: { code } });
      expect(fixture.fetch.mock.calls.map((call) => String(call[0])).some((url) => url.endsWith(".deb"))).toBe(false);
    }
  });

  it("fails closed when the embedded key is unusable", async () => {
    for (const updatePublicKey of [null, "not-a-key"]) {
      const fixture = await setup({ signWith: [keyPair().privateKey], updatePublicKey });
      expect(await fixture.controller.check()).toMatchObject({ status: "error", error: { code: "updates_signature_key_invalid" } });
    }
  });

  it("keeps hash-only verification without an embedded key and warns once", async () => {
    const fixture = await setup();
    expect((await fixture.controller.check()).status).toBe("available");
    expect((await fixture.controller.check()).status).toBe("available");
    expect(fixture.warn).toHaveBeenCalledOnce();
    expect(fixture.warn.mock.calls[0]?.[0]).toMatch(/not verified/u);
  });
});
