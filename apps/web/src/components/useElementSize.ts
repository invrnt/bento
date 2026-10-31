import { useEffect, useState } from "react";
import type { RefObject } from "react";

export type ElementSize = {
  height: number;
  width: number;
};

/** Tracks an element's content box. Falls back to `initial` where ResizeObserver is unavailable. */
export function useElementSize(ref: RefObject<HTMLElement | null>, initial: ElementSize): ElementSize {
  const [size, setSize] = useState(initial);

  useEffect(() => {
    const element = ref.current;

    if (!element || typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(([entry]) => {
      setSize({ height: entry.contentRect.height, width: entry.contentRect.width });
    });

    observer.observe(element);

    return () => observer.disconnect();
  }, [ref]);

  return size;
}
