import { describe, expect, it, vi } from "vitest";
import { SettingsTransaction } from "../src/main/settings-transaction";
import type { ProgressEvent, SettingsApplyRequest } from "../src/shared/contracts";

const request: SettingsApplyRequest = {
  revision: 4,
  values: { worker_concurrency: 2 },
  secrets: { sample_token: { operation: "set", value: "new-secret" } },
};

function fixtures() {
  const previous = {
    revision: 4,
    values: {
      worker_concurrency: { value: 1, source: "saved", locked: false, apply_mode: "restart_worker" },
      sample_token: { configured: true, source: "saved", locked: false, apply_mode: "restart_services" },
    },
  };
  const validation = {
    valid: true,
    errors: [],
    restart_plan: { mode: "restart_services", services: ["api", "worker"], affected_keys: ["worker_concurrency", "sample_token"] },
  };
  const applied = { ...previous, revision: 5, restart_plan: validation.restart_plan };
  const prepared = {
    references: { sample_token: { reference: "desktop-secret:opaque", configured: true } },
    values: { sample_token: "new-secret" },
    commit: vi.fn(async () => undefined),
    rollback: vi.fn(async () => undefined),
  };
  const sidecars = {
    apiJson: vi.fn(async (pathname: string) => {
      if (pathname === "/api/settings/values") return previous;
      if (pathname === "/api/settings/validate") return validation;
      throw new Error(`unexpected path ${pathname}`);
    }),
    restart: vi.fn(async () => undefined),
    verify: vi.fn(async () => undefined),
  };
  const secrets = {
    references: vi.fn(async () => ({ sample_token: "desktop-secret:old" })),
    prepare: vi.fn(async () => prepared),
    values: vi.fn(async () => ({ sample_token: "old-secret" })),
  };
  const bootstrap = { save: vi.fn(async () => undefined) };
  let patchCount = 0;
  sidecars.apiJson.mockImplementation(async (pathname: string, init?: RequestInit) => {
    if (pathname === "/api/settings/values" && init?.method === "PATCH") {
      patchCount += 1;
      return applied;
    }
    if (pathname === "/api/settings/values") return previous;
    if (pathname === "/api/settings/validate") return validation;
    throw new Error(`unexpected path ${pathname}`);
  });
  const progress: ProgressEvent[] = [];
  const transaction = new SettingsTransaction(sidecars as never, secrets as never, bootstrap as never, {
    schemaVersion: 1,
    dataDir: "/tmp/bento-data",
    lastKnownGoodRevision: 4,
  });
  return { applied, bootstrap, prepared, previous, progress, secrets, sidecars, transaction, validation, patchCount: () => patchCount };
}

function bodyOf(call: [unknown, ...unknown[]]): Record<string, unknown> {
  const init = call[1] as RequestInit;
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

describe("transactional settings apply", () => {
  it("commits, performs the targeted restart, verifies health, and advances last-known-good", async () => {
    const state = fixtures();
    const result = await state.transaction.apply(request, (event) => state.progress.push(event));
    expect(result).toEqual({
      ok: true,
      revision: 5,
      restartPlan: {
        mode: "restart_services",
        services: ["api", "worker"],
        affectedKeys: ["worker_concurrency", "sample_token"],
      },
    });
    expect(state.prepared.commit).toHaveBeenCalledOnce();
    expect(state.sidecars.restart).toHaveBeenCalledWith(["api", "worker"], { sample_token: "new-secret" });
    expect(state.sidecars.verify).toHaveBeenCalledOnce();
    expect(state.bootstrap.save).toHaveBeenCalledWith(expect.objectContaining({ lastKnownGoodRevision: 5 }));
    expect(state.progress.at(-1)).toEqual({ phase: "complete", status: "ok" });

    const validateCall = state.sidecars.apiJson.mock.calls.find((call) => call[0] === "/api/settings/validate")!;
    expect(bodyOf(validateCall)).toMatchObject({
      values: request.values,
      secret_references: { sample_token: { reference: "desktop-secret:opaque", configured: true } },
    });
    expect(JSON.stringify(state.sidecars.apiJson.mock.calls)).not.toContain("new-secret");
  });

  it("returns field validation errors without persisting, restarting, or committing secrets", async () => {
    const state = fixtures();
    state.sidecars.apiJson.mockImplementation(async (pathname: string) => {
      if (pathname === "/api/settings/values") return state.previous;
      return {
        ...state.validation,
        valid: false,
        errors: [{ key: "worker_concurrency", code: "out_of_range", message: "Invalid value" }],
      };
    });
    const result = await state.transaction.apply(request, (event) => state.progress.push(event));
    expect(result).toMatchObject({ ok: false, revision: 4, errors: [{ code: "out_of_range" }] });
    expect(state.prepared.commit).not.toHaveBeenCalled();
    expect(state.sidecars.restart).not.toHaveBeenCalled();
    expect(state.bootstrap.save).not.toHaveBeenCalled();
  });

  it("rolls back committed settings and secrets when health verification fails", async () => {
    const state = fixtures();
    let valuesReads = 0;
    let patchWrites = 0;
    state.sidecars.apiJson.mockImplementation(async (pathname: string, init?: RequestInit) => {
      if (pathname === "/api/settings/validate") return state.validation;
      if (pathname === "/api/settings/values" && init?.method === "PATCH") {
        patchWrites += 1;
        return patchWrites === 1
          ? state.applied
          : { ...state.previous, revision: 6, restart_plan: state.validation.restart_plan };
      }
      if (pathname === "/api/settings/values") {
        valuesReads += 1;
        return valuesReads === 1 ? state.previous : { ...state.applied };
      }
      throw new Error("unexpected call");
    });
    state.sidecars.verify.mockRejectedValueOnce(new Error("Bearer launch-token leaked failure")).mockResolvedValueOnce(undefined);

    const result = await state.transaction.apply(request, (event) => state.progress.push(event));
    expect(result).toMatchObject({ ok: false, revision: 6, rolledBack: true, errors: [{ code: "desktop_apply_rolled_back" }] });
    expect(JSON.stringify(result)).not.toContain("launch-token");
    expect(state.prepared.rollback).toHaveBeenCalledOnce();
    expect(state.sidecars.restart).toHaveBeenLastCalledWith(["api", "worker"], { sample_token: "old-secret" });
    expect(state.sidecars.verify).toHaveBeenCalledTimes(2);
    expect(state.bootstrap.save).not.toHaveBeenCalled();

    const patchCalls = state.sidecars.apiJson.mock.calls.filter((call) => call[0] === "/api/settings/values" && (call[1] as RequestInit)?.method === "PATCH");
    expect(bodyOf(patchCalls[1]!)).toMatchObject({
      revision: 5,
      values: { worker_concurrency: 1 },
      secret_references: { sample_token: { reference: "desktop-secret:old", configured: true } },
    });
  });

  it("fails safely into recovery when last-known-good rollback cannot be restored", async () => {
    const state = fixtures();
    state.sidecars.verify.mockRejectedValue(new Error("unhealthy"));
    state.prepared.rollback.mockRejectedValue(new Error("key store unavailable"));
    const result = await state.transaction.apply(request, (event) => state.progress.push(event));
    expect(result).toEqual({
      ok: false,
      revision: 4,
      rolledBack: false,
      errors: [{
        key: "_",
        code: "desktop_recovery_required",
        message: "Bento could not restore the last known good configuration",
      }],
    });
    expect(state.progress.at(-1)).toMatchObject({ phase: "rolling-back", status: "failed" });
    expect(state.bootstrap.save).not.toHaveBeenCalled();
  });

  it("moves the supervisor to a validated new directory and supports use-empty without copying", async () => {
    const state = fixtures();
    const oldDataDir = "/tmp/bento-data";
    const newDataDir = "/tmp/bento-new-data";
    const dataDirectories = {
      validate: vi.fn(async () => newDataDir),
      execute: vi.fn(async () => undefined),
    };
    Object.assign(state.sidecars, {
      stop: vi.fn(async () => undefined),
      start: vi.fn(async () => undefined),
      setDataDir: vi.fn(),
      setSecretEnvironment: vi.fn(),
    });
    let valuesReads = 0;
    let patchWrites = 0;
    state.sidecars.apiJson.mockImplementation(async (pathname: string, init?: RequestInit) => {
      if (pathname === "/api/settings/validate") return state.validation;
      if (pathname === "/api/settings/values" && init?.method === "PATCH") {
        patchWrites += 1;
        return { ...state.previous, revision: 1, restart_plan: state.validation.restart_plan };
      }
      if (pathname === "/api/settings/values") {
        valuesReads += 1;
        return valuesReads === 1 ? state.previous : { revision: 0, values: {} };
      }
      throw new Error("unexpected call");
    });
    const transaction = new SettingsTransaction(
      state.sidecars as never,
      state.secrets as never,
      state.bootstrap as never,
      { schemaVersion: 1, dataDir: oldDataDir, lastKnownGoodRevision: 4 },
      dataDirectories as never,
    );
    const result = await transaction.apply(
      { revision: 4, values: { data_dir: newDataDir }, secrets: {}, dataMigration: "use-empty" },
      () => undefined,
    );

    expect(result).toMatchObject({ ok: true, revision: 1 });
    expect(patchWrites).toBe(1);
    expect(dataDirectories.validate).toHaveBeenCalledWith(oldDataDir, newDataDir, "use-empty");
    expect(dataDirectories.execute).toHaveBeenCalledWith(oldDataDir, newDataDir, "use-empty");
    expect(state.sidecars.stop).toHaveBeenCalledOnce();
    expect(state.sidecars.setDataDir).toHaveBeenCalledWith(newDataDir);
    expect(state.sidecars.start).toHaveBeenCalledOnce();
    expect(state.sidecars.restart).toHaveBeenCalledWith(["api", "worker"], { sample_token: "old-secret" });
    expect(state.bootstrap.save).toHaveBeenNthCalledWith(1, {
      schemaVersion: 1,
      dataDir: newDataDir,
      lastKnownGoodRevision: 4,
    });
    expect(state.bootstrap.save).toHaveBeenLastCalledWith({
      schemaVersion: 1,
      dataDir: newDataDir,
      lastKnownGoodRevision: 1,
    });
  });

  it("reapplies values and opaque secret references into a newly migrated empty database", async () => {
    const state = fixtures();
    const oldDataDir = "/tmp/bento-data";
    const newDataDir = "/tmp/bento-empty-data";
    const values = { data_dir: newDataDir, worker_concurrency: 2, ocr_provider: "rapidocr" };
    const previous = {
      revision: 4,
      values: {
        worker_concurrency: { value: 1, source: "saved", locked: false, apply_mode: "restart_worker" },
        sample_attempts: { value: 7, source: "saved", locked: false, apply_mode: "restart_services" },
        host: { value: "127.0.0.1", source: "policy", locked: true, apply_mode: "restart_app" },
        sample_token: { configured: true, source: "saved", locked: false, apply_mode: "restart_services" },
        sample_hash: { configured: true, source: "saved", locked: false, apply_mode: "restart_services" },
        sample_signing_key: { configured: true, source: "saved", locked: false, apply_mode: "restart_services" },
      },
    };
    const references = {
      sample_token: "desktop-secret:old-token",
      sample_hash: "desktop-secret:old-sample-hash",
      sample_signing_key: "desktop-secret:old-signing-key",
    };
    const prepared = {
      references: {
        sample_token: { reference: "desktop-secret:opaque", configured: true },
        sample_signing_key: { reference: null, configured: false },
      },
      values: { sample_token: "new-secret", sample_hash: "existing-api-hash" },
      commit: vi.fn(async () => undefined),
      rollback: vi.fn(async () => undefined),
    };
    state.secrets.references.mockResolvedValue(references);
    state.secrets.prepare.mockResolvedValue(prepared);
    const dataDirectories = {
      validate: vi.fn(async () => newDataDir),
      execute: vi.fn(async () => undefined),
    };
    Object.assign(state.sidecars, {
      stop: vi.fn(async () => undefined),
      start: vi.fn(async () => undefined),
      setDataDir: vi.fn(),
      setSecretEnvironment: vi.fn(),
    });
    let valuesReads = 0;
    state.sidecars.apiJson.mockImplementation(async (pathname: string, init?: RequestInit) => {
      if (pathname === "/api/settings/validate") return state.validation;
      if (pathname === "/api/settings/values" && init?.method === "PATCH") {
        return { revision: 1, values: {}, restart_plan: { mode: "restart_services", services: ["api", "worker"], affected_keys: Object.keys(values) } };
      }
      if (pathname === "/api/settings/values") {
        valuesReads += 1;
        return valuesReads === 1 ? previous : { revision: 0, values: {} };
      }
      throw new Error(`unexpected call ${pathname}`);
    });
    const transaction = new SettingsTransaction(
      state.sidecars as never,
      state.secrets as never,
      state.bootstrap as never,
      { schemaVersion: 1, dataDir: oldDataDir, lastKnownGoodRevision: 4 },
      dataDirectories as never,
    );
    const result = await transaction.apply({
      revision: 4,
      values,
      secrets: {
        sample_token: { operation: "set", value: "new-secret" },
        sample_signing_key: { operation: "clear" },
      },
      dataMigration: "use-empty",
    }, () => undefined);

    const patchCalls = state.sidecars.apiJson.mock.calls.filter(
      (call) => call[0] === "/api/settings/values" && (call[1] as RequestInit)?.method === "PATCH",
    );
    expect(patchCalls).toHaveLength(1);
    expect(bodyOf(patchCalls[0]!)).toEqual({
      revision: 0,
      values: {
        worker_concurrency: 2,
        sample_attempts: 7,
        data_dir: newDataDir,
        ocr_provider: "rapidocr",
      },
      secret_references: {
        sample_token: { reference: "desktop-secret:opaque", configured: true },
        sample_hash: { reference: "desktop-secret:old-sample-hash", configured: true },
        sample_signing_key: { reference: null, configured: false },
      },
      run_probes: false,
    });
    const validateCalls = state.sidecars.apiJson.mock.calls.filter((call) => call[0] === "/api/settings/validate");
    expect(validateCalls).toHaveLength(2);
    expect(bodyOf(validateCalls[1]!)).toEqual({
      values: {
        worker_concurrency: 2,
        sample_attempts: 7,
        data_dir: newDataDir,
        ocr_provider: "rapidocr",
      },
      secret_references: {
        sample_token: { reference: "desktop-secret:opaque", configured: true },
        sample_hash: { reference: "desktop-secret:old-sample-hash", configured: true },
        sample_signing_key: { reference: null, configured: false },
      },
      run_probes: false,
    });
    expect(result).toMatchObject({ ok: true, revision: 1 });
    expect(state.bootstrap.save).toHaveBeenLastCalledWith({
      schemaVersion: 1,
      dataDir: newDataDir,
      lastKnownGoodRevision: 1,
    });
  });

  it("returns the supervisor and bootstrap to the former directory when new-directory health fails", async () => {
    const state = fixtures();
    const oldDataDir = "/tmp/bento-data";
    const newDataDir = "/tmp/bento-new-data";
    const dataDirectories = {
      validate: vi.fn(async () => newDataDir),
      execute: vi.fn(async () => undefined),
    };
    Object.assign(state.sidecars, {
      stop: vi.fn(async () => undefined),
      start: vi.fn(async () => undefined),
      setDataDir: vi.fn(),
      setSecretEnvironment: vi.fn(),
    });
    let valuesReads = 0;
    let patchWrites = 0;
    state.sidecars.apiJson.mockImplementation(async (pathname: string, init?: RequestInit) => {
      if (pathname === "/api/settings/validate") return state.validation;
      if (pathname === "/api/settings/values" && init?.method === "PATCH") {
        patchWrites += 1;
        return patchWrites === 1
          ? { ...state.applied, restart_plan: { mode: "restart_app", services: ["desktop"], affected_keys: ["data_dir"] } }
          : { ...state.previous, revision: 6, restart_plan: state.validation.restart_plan };
      }
      if (pathname === "/api/settings/values") {
        valuesReads += 1;
        return valuesReads === 1 ? state.previous : { ...state.previous, revision: 5 };
      }
      throw new Error("unexpected call");
    });
    state.sidecars.verify.mockRejectedValueOnce(new Error("new data directory unhealthy")).mockResolvedValue(undefined);
    const transaction = new SettingsTransaction(
      state.sidecars as never,
      state.secrets as never,
      state.bootstrap as never,
      { schemaVersion: 1, dataDir: oldDataDir, lastKnownGoodRevision: 4 },
      dataDirectories as never,
    );
    const result = await transaction.apply(
      { revision: 4, values: { data_dir: newDataDir }, secrets: {}, dataMigration: "copy" },
      () => undefined,
    );

    expect(result).toMatchObject({ ok: false, rolledBack: true, revision: 6 });
    expect(dataDirectories.execute).toHaveBeenCalledWith(oldDataDir, newDataDir, "copy");
    expect(state.sidecars.setDataDir.mock.calls).toEqual([[newDataDir], [oldDataDir]]);
    expect(state.sidecars.stop).toHaveBeenCalledTimes(2);
    expect(state.sidecars.start).toHaveBeenCalledTimes(2);
    expect(state.bootstrap.save).toHaveBeenCalledWith({
      schemaVersion: 1,
      dataDir: oldDataDir,
      lastKnownGoodRevision: 4,
    });
    expect(state.sidecars.verify).toHaveBeenCalledTimes(2);
  });

  it.each(["copy", "use-empty"] as const)(
    "restores the previous secret environment before starting the former data directory after %s fails",
    async (dataMigration) => {
      const state = fixtures();
      const oldDataDir = "/tmp/bento-data";
      const newDataDir = `/tmp/bento-${dataMigration}-data`;
      const previousSecretValues = {
        sample_token: "old-token",
        sample_signing_key: "old-signing-key-secret",
      };
      const changedSecretValues = { sample_token: "new-token" };
      const events: string[] = [];
      const prepared = {
        references: {
          sample_token: { reference: "desktop-secret:new-token", configured: true },
          sample_signing_key: { reference: null, configured: false },
        },
        values: changedSecretValues,
        commit: vi.fn(async () => { events.push("secrets:commit"); }),
        rollback: vi.fn(async () => { events.push("secrets:rollback"); }),
      };
      state.secrets.references.mockResolvedValue({
        sample_token: "desktop-secret:old-token",
        sample_signing_key: "desktop-secret:old-signing-key",
      });
      state.secrets.prepare.mockResolvedValue(prepared);
      state.secrets.values.mockImplementation(async () => {
        events.push("secrets:previous-values");
        return previousSecretValues;
      });
      const dataDirectories = {
        validate: vi.fn(async () => newDataDir),
        execute: vi.fn(async () => undefined),
      };
      let currentDataDir = oldDataDir;
      Object.assign(state.sidecars, {
        stop: vi.fn(async () => { events.push(`stop:${currentDataDir}`); }),
        start: vi.fn(async () => { events.push(`start:${currentDataDir}`); }),
        setDataDir: vi.fn((value: string) => {
          currentDataDir = value;
          events.push(`data-dir:${value}`);
        }),
        setSecretEnvironment: vi.fn((values: Record<string, string>) => {
          events.push(values === previousSecretValues ? "environment:previous" : "environment:changed");
        }),
      });
      let initialRead = true;
      let patchWrites = 0;
      state.sidecars.apiJson.mockImplementation(async (pathname: string, init?: RequestInit) => {
        if (pathname === "/api/settings/validate") return state.validation;
        if (pathname === "/api/settings/values" && init?.method === "PATCH") {
          patchWrites += 1;
          if (dataMigration === "use-empty") {
            return { revision: 1, values: {}, restart_plan: state.validation.restart_plan };
          }
          return patchWrites === 1
            ? { ...state.applied, restart_plan: { mode: "restart_app", services: ["desktop"], affected_keys: ["data_dir"] } }
            : { ...state.previous, revision: 6, restart_plan: state.validation.restart_plan };
        }
        if (pathname === "/api/settings/values") {
          if (initialRead) {
            initialRead = false;
            return state.previous;
          }
          return currentDataDir === newDataDir ? { revision: 0, values: {} } : { ...state.previous, revision: 5 };
        }
        throw new Error(`unexpected call ${pathname}`);
      });
      state.sidecars.verify.mockRejectedValueOnce(new Error("new directory unhealthy")).mockResolvedValue(undefined);
      const transaction = new SettingsTransaction(
        state.sidecars as never,
        state.secrets as never,
        state.bootstrap as never,
        { schemaVersion: 1, dataDir: oldDataDir, lastKnownGoodRevision: 4 },
        dataDirectories as never,
      );

      const result = await transaction.apply({
        revision: 4,
        values: { data_dir: newDataDir },
        secrets: {
          sample_token: { operation: "set", value: "new-token" },
          sample_signing_key: { operation: "clear" },
        },
        dataMigration,
      }, () => undefined);

      expect(result).toMatchObject({ ok: false, rolledBack: true });
      expect(prepared.commit).toHaveBeenCalledOnce();
      expect(prepared.rollback).toHaveBeenCalledOnce();
      expect(state.sidecars.setSecretEnvironment.mock.calls).toEqual([
        [changedSecretValues],
        [previousSecretValues],
      ]);
      expect(changedSecretValues).not.toHaveProperty("sample_signing_key");
      expect(previousSecretValues.sample_token).toBe("old-token");
      expect(previousSecretValues.sample_signing_key).toBe("old-signing-key-secret");
      expect(events.indexOf("secrets:rollback")).toBeLessThan(events.indexOf("environment:previous"));
      expect(events.indexOf("secrets:previous-values")).toBeLessThan(events.indexOf("environment:previous"));
      expect(events.indexOf("environment:previous")).toBeLessThan(events.indexOf(`start:${oldDataDir}`));
    },
  );
});
