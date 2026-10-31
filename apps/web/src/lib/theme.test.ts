import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { initTheme, resolveTheme, setThemePreference, useThemePreference } from "./theme";

describe("theme preference", () => {
  let stored: Record<string, string>;

  beforeEach(() => {
    stored = {};
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => stored[key] ?? null,
        setItem: (key: string, value: string) => {
          stored[key] = value;
        },
      },
    });
  });

  afterEach(() => {
    setThemePreference("system");
  });

  it("falls back to light when the system preference is unavailable", () => {
    initTheme();

    expect(resolveTheme("system")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("applies, persists and broadcasts explicit choices", () => {
    const { result } = renderHook(() => useThemePreference());

    act(() => setThemePreference("dark"));

    expect(result.current).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(stored["bento:theme"]).toBe("dark");
  });
});
