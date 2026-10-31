import { useMemo } from "react";

import type { QrMatrix } from "../api/qr";
import { cx } from "../lib/cx";

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
 * Always dark-on-white so phone cameras read it in both themes.
 */
export function QrCode({ className, label, matrix, quietZone = 4 }: QrCodeProps) {
  const runs = useMemo(() => darkRuns(matrix), [matrix]);
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
    </svg>
  );
}

/** Merges horizontal runs of dark modules into one rect each. */
export function darkRuns(matrix: QrMatrix): Run[] {
  const runs: Run[] = [];
  matrix.rows.slice(0, matrix.size).forEach((row, y) => {
    let start = -1;
    for (let x = 0; x <= matrix.size; x += 1) {
      const dark = x < matrix.size && row[x] === "1";
      if (dark && start < 0) start = x;
      if (!dark && start >= 0) {
        runs.push({ length: x - start, x: start, y });
        start = -1;
      }
    }
  });
  return runs;
}
