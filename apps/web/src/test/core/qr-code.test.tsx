import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QrCode, darkRuns } from "../../components/QrCode";
import { qrMatrix } from "./testkit";

describe("QrCode", () => {
  it("is a labelled image with a quiet zone around the symbol", () => {
    render(<QrCode label="Código QR para vincular Telegram" matrix={qrMatrix} />);
    const image = screen.getByRole("img", { name: "Código QR para vincular Telegram" });
    expect(image).toHaveAttribute("viewBox", "0 0 13 13");
    expect(image.querySelector("g")).toHaveAttribute("transform", "translate(4 4)");
  });

  it("draws one rect per horizontal run of dark modules", () => {
    expect(darkRuns(qrMatrix)).toEqual([
      { length: 3, x: 0, y: 0 },
      { length: 1, x: 0, y: 1 },
      { length: 1, x: 2, y: 1 },
      { length: 1, x: 4, y: 1 },
      { length: 3, x: 0, y: 2 },
      { length: 2, x: 3, y: 3 },
      { length: 1, x: 0, y: 4 },
      { length: 3, x: 2, y: 4 },
    ]);
    const { container } = render(<QrCode label="QR" matrix={qrMatrix} quietZone={2} />);
    // Background + 8 runs.
    expect(container.querySelectorAll("rect")).toHaveLength(9);
    expect(container.querySelector("svg")).toHaveAttribute("viewBox", "0 0 9 9");
  });
});
