import { useMemo, useRef, useState } from "react";
import type { ReactNode, UIEvent } from "react";

import { cx } from "../lib/cx";
import { useElementSize } from "./useElementSize";

export type VirtualListProps<T> = {
  ariaLabel?: string;
  className?: string;
  estimateSize: number;
  /** Fill a positioned parent (absolute inset-0) instead of using a fixed `height`. */
  fill?: boolean;
  getKey: (item: T, index: number) => string;
  height?: number;
  items: T[];
  overscan?: number;
  renderItem: (item: T, index: number) => ReactNode;
};

export function VirtualList<T>({
  ariaLabel,
  className,
  estimateSize,
  fill = false,
  getKey,
  height = 360,
  items,
  overscan = 3,
  renderItem,
}: VirtualListProps<T>) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const size = useElementSize(containerRef, { height, width: 0 });
  const viewportHeight = fill ? size.height || height : height;
  const totalSize = items.length * estimateSize;
  const startIndex = Math.max(0, Math.floor(scrollTop / estimateSize) - overscan);
  const visibleCount = Math.ceil(viewportHeight / estimateSize) + overscan * 2;
  const visibleItems = useMemo(
    () => items.slice(startIndex, startIndex + visibleCount),
    [items, startIndex, visibleCount],
  );

  function onScroll(event: UIEvent<HTMLDivElement>) {
    setScrollTop(event.currentTarget.scrollTop);
  }

  return (
    <div
      aria-label={ariaLabel}
      className={cx("relative overflow-y-auto overscroll-contain", fill && "absolute inset-0", className)}
      onScroll={onScroll}
      ref={containerRef}
      role="list"
      style={fill ? undefined : { height }}
    >
      <div className="relative" style={{ height: totalSize }}>
        {visibleItems.map((item, visibleIndex) => {
          const index = startIndex + visibleIndex;

          return (
            <div
              className="absolute left-0 top-0 w-full"
              key={getKey(item, index)}
              role="listitem"
              style={{ height: estimateSize, transform: `translateY(${index * estimateSize}px)` }}
            >
              {renderItem(item, index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
