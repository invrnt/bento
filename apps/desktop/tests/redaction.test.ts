import { describe, expect, it, vi } from "vitest";
import { RedactingLog, redact } from "../src/main/redaction";

describe("desktop diagnostic redaction", () => {
  it("redacts sensitive keys, bearer credentials, query parameters, and known values recursively", () => {
    const known = "known-value-123";
    const circular: Record<string, unknown> = { safe: "visible" };
    circular.self = circular;
    const result = redact(
      {
        authorization: "Bearer abc.def.ghi",
        nested: {
          telegram_api_hash: "hash-value",
          BENTO_DEVICE_WRAPPING_KEY: "wrapping-value",
          output: `failed for ${known} at https://local.test/path?token=url-token&keep=yes`,
        },
        list: ["Bearer other-token", circular],
      },
      [known],
    );

    expect(result).toEqual({
      authorization: "[REDACTED]",
      nested: {
        telegram_api_hash: "[REDACTED]",
        BENTO_DEVICE_WRAPPING_KEY: "[REDACTED]",
        output: "failed for [REDACTED] at https://local.test/path?token=[REDACTED]&keep=yes",
      },
      list: ["Bearer [REDACTED]", { safe: "visible", self: "[CIRCULAR]" }],
    });
    expect(JSON.stringify(result)).not.toContain(known);
    expect(JSON.stringify(result)).not.toContain("url-token");
  });

  it("writes valid structured JSON without leaking runtime secrets", () => {
    const writeLine = vi.fn();
    const log = new RedactingLog(writeLine, () => ["launch-token-value", "telegram-secret-value"]);
    log.write("error", "Bearer launch-token-value failed", {
      stderr: "telegram-secret-value",
      cookie: "session-cookie",
      harmless: "kept",
    });

    const line = writeLine.mock.calls[0]?.[0] as string;
    expect(() => JSON.parse(line)).not.toThrow();
    expect(line).not.toContain("launch-token-value");
    expect(line).not.toContain("telegram-secret-value");
    expect(line).not.toContain("session-cookie");
    expect(JSON.parse(line)).toMatchObject({ level: "error", context: { cookie: "[REDACTED]", harmless: "kept" } });
  });
});
