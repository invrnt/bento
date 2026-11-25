import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QrCode, darkRuns, logoSquare } from "../../components/QrCode";
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

  it("leaves the centre square light and draws the Bento mark there", () => {
    // 9×9 all-dark matrix with a 3-module logo square in the middle (modules 3..5).
    const matrix = { logo_modules: 3, rows: Array.from({ length: 9 }, () => "111111111"), size: 9 };
    expect(logoSquare(matrix)).toEqual({ inset: 1, mark: 1, side: 3, start: 3 });
    const runs = darkRuns(matrix, logoSquare(matrix));
    expect(runs.filter((run) => run.y === 4)).toEqual([
      { length: 3, x: 0, y: 4 },
      { length: 3, x: 6, y: 4 },
    ]);
    expect(runs.filter((run) => run.y === 0)).toEqual([{ length: 9, x: 0, y: 0 }]);

    render(<QrCode label="QR" matrix={matrix} quietZone={4} />);
    const mark = screen.getByTestId("qr-logo");
    expect(mark).toHaveAttribute("transform", "translate(8 8) scale(0.03125)");
    expect(mark.querySelector("circle")).not.toBeNull();
  });

  it("draws no mark for plain codes such as the printed recovery kit", () => {
    render(<QrCode label="QR" matrix={{ ...qrMatrix, logo_modules: 0 }} />);
    expect(screen.queryByTestId("qr-logo")).toBeNull();
    expect(logoSquare(qrMatrix)).toBeNull();
  });
});
