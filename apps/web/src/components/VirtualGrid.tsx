import { useMemo, useRef, useState } from "react";
import type { ReactNode, UIEvent } from "react";

import { cx } from "../lib/cx";
import { useElementSize } from "./useElementSize";

export type VirtualGridProps<T> = {
  ariaLabel?: string;
  className?: string;
  /** Fill a positioned parent (absolute inset-0) instead of using a fixed `height`. */
  fill?: boolean;
  gap?: number;
  getKey: (item: T, index: number) => string;
  height?: number;
  items: T[];
  minColumnWidth?: number;
  overscan?: number;
  renderItem: (item: T, index: number) => ReactNode;
  rowHeight: number;
};

export function VirtualGrid<T>({
  ariaLabel,
  className,
  fill = false,
  gap = 12,
  getKey,
  height = 420,
  items,
  minColumnWidth = 160,
  overscan = 2,
  renderItem,
  rowHeight,
}: VirtualGridProps<T>) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const size = useElementSize(containerRef, { height, width: minColumnWidth * 2 + gap });
  const viewportHeight = fill ? size.height || height : height;
  const width = size.width;
  const columns = Math.max(1, Math.floor((width + gap) / (minColumnWidth + gap)));
  const rowCount = Math.ceil(items.length / columns);
  const rowStride = rowHeight + gap;
  const totalSize = Math.max(0, rowCount * rowStride - gap);
  const startRow = Math.max(0, Math.floor(scrollTop / rowStride) - overscan);
  const visibleRows = Math.ceil(viewportHeight / rowStride) + overscan * 2;
  const startIndex = startRow * columns;
  const visibleCount = visibleRows * columns;
  const visibleItems = useMemo(
    () => items.slice(startIndex, startIndex + visibleCount),
    [items, startIndex, visibleCount],
  );

  function onScroll(event: UIEvent<HTMLDivElement>) {
    setScrollTop(event.currentTarget.scrollTop);
  }

  const columnWidth = (width - gap * (columns - 1)) / columns;

  return (
    <div
      aria-label={ariaLabel}
      className={cx("relative overflow-y-auto overscroll-contain", fill && "absolute inset-0", className)}
      onScroll={onScroll}
      ref={containerRef}
      role="grid"
      style={fill ? undefined : { height }}
    >
      <div className="relative min-w-full" style={{ height: totalSize }}>
        {visibleItems.map((item, visibleIndex) => {
          const index = startIndex + visibleIndex;
          const row = Math.floor(index / columns);
          const column = index % columns;

          return (
            <div
              className="absolute"
              key={getKey(item, index)}
              role="gridcell"
              style={{
                height: rowHeight,
                transform: `translate(${column * (columnWidth + gap)}px, ${row * rowStride}px)`,
                width: columnWidth,
              }}
            >
              {renderItem(item, index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
