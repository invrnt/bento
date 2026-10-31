import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePolledResource } from "./usePolledResource";

describe("usePolledResource", () => {
  afterEach(() => vi.useRealTimers());

  it("loads once and exposes data", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true });
    const { result } = renderHook(() => usePolledResource(fetcher, null));

    await waitFor(() => expect(result.current.data).toEqual({ ok: true }));
    expect(result.current.isLoading).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("polls on an interval and surfaces errors", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValueOnce(1).mockRejectedValueOnce(new Error("boom")).mockResolvedValue(3);
    const { result } = renderHook(() => usePolledResource(fetcher, 1000));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.error?.message).toBe("boom");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(3);
    expect(result.current.error).toBeNull();
  });
});
