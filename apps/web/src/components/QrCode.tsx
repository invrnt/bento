import { useMemo } from "react";

import type { QrMatrix } from "../api/qr";
import { cx } from "../lib/cx";
import { BrandMarkShapes } from "./BrandMark";

export type QrCodeProps = {
  className?: string;
  /** Accessible name, e.g. "Código QR para vincular Telegram". */
  label: string;
  matrix: QrMatrix;
  /** Light modules around the symbol; scanners need at least 4. */
  quietZone?: number;
};

type Run = { length: number; x: number; y: number };

/**
 * Draws a QR matrix returned by the API (rows of "0"/"1") as crisp SVG rects.
 * Always dark-on-white so phone cameras read it in both themes. When the API
 * reserves a centre square (`logo_modules`, generated with error correction H),
 * those modules are left light and the Bento mark is drawn there.
 */
export function QrCode({ className, label, matrix, quietZone = 4 }: QrCodeProps) {
  const logo = useMemo(() => logoSquare(matrix), [matrix]);
  const runs = useMemo(() => darkRuns(matrix, logo), [matrix, logo]);
  const extent = matrix.size + quietZone * 2;

  return (
    <svg
      aria-label={label}
      className={cx("block aspect-square w-full rounded-lg", className)}
      data-testid="qr-code"
      role="img"
      shapeRendering="crispEdges"
      viewBox={`0 0 ${extent} ${extent}`}
    >
      <rect className="fill-white" height={extent} width={extent} />
      <g className="fill-black" transform={`translate(${quietZone} ${quietZone})`}>
        {runs.map((run) => (
          <rect height={1} key={`${run.x}-${run.y}`} width={run.length} x={run.x} y={run.y} />
        ))}
      </g>
      {logo ? (
        // Light scheme on purpose: the code is always dark-on-white, whatever the app theme.
        <g
          className="[color-scheme:light]"
          data-testid="qr-logo"
          shapeRendering="geometricPrecision"
          transform={`translate(${quietZone + logo.start + logo.inset} ${quietZone + logo.start + logo.inset}) scale(${logo.mark / 32})`}
        >
          <BrandMarkShapes />
        </g>
      ) : null}
    </svg>
  );
}

type LogoSquare = { inset: number; mark: number; side: number; start: number };

/** The centre square reserved for the mark, in module coordinates, or null for a plain code. */
export function logoSquare(matrix: QrMatrix): LogoSquare | null {
  const side = matrix.logo_modules ?? 0;
  if (side <= 0 || side >= matrix.size) return null;
  // A full module of white around the mark: its dark box must not merge with nearby modules.
  const inset = 1;
  return { inset, mark: side - inset * 2, side, start: (matrix.size - side) / 2 };
}

/** Merges horizontal runs of dark modules into one rect each, skipping the logo square. */
export function darkRuns(matrix: QrMatrix, logo: LogoSquare | null = null): Run[] {
  const runs: Run[] = [];
  const hidden = (x: number, y: number) =>
    logo !== null && x >= logo.start && x < logo.start + logo.side && y >= logo.start && y < logo.start + logo.side;
  matrix.rows.slice(0, matrix.size).forEach((row, y) => {
    let start = -1;
    for (let x = 0; x <= matrix.size; x += 1) {
      const dark = x < matrix.size && row[x] === "1" && !hidden(x, y);
      if (dark && start < 0) start = x;
      if (!dark && start >= 0) {
        runs.push({ length: x - start, x: start, y });
        start = -1;
      }
    }
  });
  return runs;
}
