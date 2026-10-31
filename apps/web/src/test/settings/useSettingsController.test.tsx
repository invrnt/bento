import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createApiClient } from "../../api/client";
import { useSettingsController } from "../../features/settings/useSettingsController";

afterEach(() => { delete window.bento; });

describe("settings controller desktop transaction", () => {
  it("applies through the desktop bridge without secrets and follows apply progress", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      const payload = path.endsWith("/settings/schema")
        ? { revision: 3, fields: [
          { apply_mode: "restart_worker", availability: "both", constraints: { choices: [], maximum: 8, minimum: 1 }, default: 1, editable: true, env_aliases: ["WORKER_CONCURRENCY"], group: "performance", help_key: "settings.worker_concurrency.help", key: "worker_concurrency", label_key: "settings.worker_concurrency.label", locked: false, probe: null, secret: false, source: "saved", type: "integer" },
          { apply_mode: "restart_services", availability: "both", constraints: { choices: [], maximum: null, minimum: null }, default: null, editable: true, env_aliases: ["TELEGRAM_BOT_TOKEN"], group: "telegram", help_key: "settings.telegram_bot_token.help", key: "telegram_bot_token", label_key: "settings.telegram_bot_token.label", locked: false, probe: null, secret: true, source: "saved", type: "secret" },
        ] }
        : path.endsWith("/settings/values")
          ? { revision: 3, values: { worker_concurrency: { apply_mode: "restart_worker", locked: false, source: "saved", value: 1 }, telegram_bot_token: { apply_mode: "restart_services", configured: false, locked: false, source: "saved" } } }
          : { storage_backend: "local", worker_concurrency: 1, worker_status: "running" };
      return new Response(JSON.stringify(payload), { headers: { "content-type": "application/json" }, status: 200 });
    });
    let progressListener: ((event: { phase: "validating"; status: "started" }) => void) | undefined;
    const apply = vi.fn().mockImplementation(async () => {
      progressListener?.({ phase: "validating", status: "started" });
      return { ok: true, restartPlan: { affectedKeys: ["worker_concurrency"], mode: "restart_services", services: ["api", "worker"] }, revision: 4 };
    });
    window.bento = {
      lifecycle: { onStatus: vi.fn(() => vi.fn()), status: vi.fn() }, pickDirectory: vi.fn(), pickFile: vi.fn(),
      platform: vi.fn().mockResolvedValue({ arch: "x64", desktop: true, platform: "linux", recoveryMode: false, secureStorage: "available", version: "1.0.0" }),
      settings: { apply, onProgress: vi.fn((listener) => { progressListener = listener as typeof progressListener; return vi.fn(); }), probe: vi.fn() },
    };
    const client = createApiClient({ baseUrl: "/api", fetcher });
    const { result } = renderHook(() => useSettingsController(client));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.setValue("worker_concurrency", 2);
    });
    await act(async () => { await result.current.save(); });

    expect(apply).toHaveBeenCalledWith(expect.objectContaining({
      revision: 3,
      secrets: {},
      values: { worker_concurrency: 2 },
    }));
    expect(result.current.applyProgress).toEqual([{ phase: "validating", status: "started" }]);
  });

  it("only runs probes the desktop bridge supports and never sends secrets", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      const payload = path.endsWith("/settings/schema")
        ? { revision: 1, fields: [] }
        : path.endsWith("/settings/values")
          ? { revision: 1, values: { data_dir: { apply_mode: "restart_app", locked: false, source: "saved", value: "/data" } } }
          : { storage_backend: "local" };
      return new Response(JSON.stringify(payload), { headers: { "content-type": "application/json" }, status: 200 });
    });
    const probe = vi.fn().mockResolvedValue({ status: "ok" });
    window.bento = {
      lifecycle: { onStatus: vi.fn(() => vi.fn()), status: vi.fn() }, pickDirectory: vi.fn(), pickFile: vi.fn(),
      platform: vi.fn().mockResolvedValue({ arch: "x64", desktop: true, platform: "linux", recoveryMode: false, secureStorage: "available", version: "1.0.0" }),
      settings: { apply: vi.fn(), onProgress: vi.fn(() => vi.fn()), probe },
    };
    const client = createApiClient({ baseUrl: "/api", fetcher });
    const { result } = renderHook(() => useSettingsController(client));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => { await result.current.probe("telegram_bot_api_url", "telegram"); });
    expect(probe).not.toHaveBeenCalled();
    await act(async () => { await result.current.probe("data_dir", "writable_directory"); });
    expect(probe).toHaveBeenCalledWith({ kind: "writable-directory", path: "/data" });
  });
});
