import { describe, expect, it } from "vitest";
import { LineSplitter, OVERLONG_LINE } from "../src/main/line-splitter";

function split(chunks: string[], maxLength?: number): string[] {
  const lines: string[] = [];
  const splitter = new LineSplitter((line) => lines.push(line), maxLength);
  for (const chunk of chunks) splitter.push(chunk);
  splitter.end();
  return lines;
}

describe("sidecar output line splitting", () => {
  it("joins chunks into whole lines and strips CRLF", () => {
    expect(split(["first par", "t\r\nsecond\n\nthi", "rd"])).toEqual(["first part", "second", "third"]);
  });

  it("drops overlong lines whole instead of truncating them", () => {
    const secret = "S".repeat(40);
    expect(split([`${"x".repeat(10)}${secret.slice(0, 5)}`, `${secret.slice(5)}\nafter\n`], 32)).toEqual([OVERLONG_LINE, "after"]);
    expect(split([`${"x".repeat(40)}\nok\n`], 32)).toEqual([OVERLONG_LINE, "ok"]);
    expect(split(["x".repeat(40)], 32)).toEqual([OVERLONG_LINE]);
  });
});
