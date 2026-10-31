import { afterEach, describe, expect, it, vi } from "vitest";

import { decideGate } from "../../features/onboarding/useAppGate";
import { navigationPath, onDeepLink, onNavigate, savePageAsPdf, secureStorageMode, setDesktopPreferences, isLaunchAtLoginError } from "../../features/onboarding/desktopHost";
import { formatPairingInput, isCompletePairingCode, pairingCodeFromLocation } from "../../features/pairing/pairingCode";
import { pairingProblem } from "../../features/pairing/pairingErrors";
import { formatRecoveryInput, isCompleteRecoveryCode, matchesLastGroup, recoveryErrorKey, recoveryGroups, recoveryQrFrom } from "../../features/recovery/recoveryCode";
import { backupErrorKey } from "../../features/onboarding/backupSources";
import { ApiError } from "../../api/client";
import type { VaultStatus } from "../../api/vault";
import { installBridge, recoveryCode, removeBridge } from "./testkit";

afterEach(removeBridge);

const vault = (state: VaultStatus["state"]): VaultStatus => ({
  created_at: null, devices_count: 1, other_vaults: 0, recovery_kit_saved: false, state, usage: { bytes: 0, files: 0 }, vault_id: null,
});

describe("pairing codes", () => {
  it("formats typed codes and pasted links as XXXX-XXXX-XXXX", () => {
    expect(formatPairingInput("k7q2mxr9t4wa")).toBe("K7Q2-MXR9-T4WA");
    expect(formatPairingInput("k7q2")).toBe("K7Q2");
    expect(formatPairingInput("k7q2m")).toBe("K7Q2-M");
    expect(formatPairingInput("bento://join?v=1&c=K7Q2-MXR9-T4WA")).toBe("K7Q2-MXR9-T4WA");
    expect(formatPairingInput("https://bento.app/join#v=1&c=K7Q2-MXR9-T4WA")).toBe("K7Q2-MXR9-T4WA");
    expect(formatPairingInput("K7Q2 MXR9 T4WA extra")).toBe("K7Q2-MXR9-T4WA");
    // Crockford aliases: O → 0, I/L → 1; U is not part of the alphabet.
    expect(formatPairingInput("oilu")).toBe("011");
  });

  it("knows when a code is complete and reads prefilled codes from the location", () => {
    expect(isCompletePairingCode("K7Q2-MXR9-T4W")).toBe(false);
    expect(isCompletePairingCode("k7q2-mxr9-t4wa")).toBe(true);
    expect(pairingCodeFromLocation("?c=k7q2mxr9t4wa")).toBe("K7Q2-MXR9-T4WA");
    expect(pairingCodeFromLocation("", "#v=1&c=K7Q2-MXR9-T4WA")).toBe("K7Q2-MXR9-T4WA");
    expect(pairingCodeFromLocation("")).toBe("");
  });

  it("groups error codes into actionable problems", () => {
    expect(pairingProblem("pairing_code_invalid")).toBe("wrongCode");
    expect(pairingProblem("pairing_confirm_failed")).toBe("wrongCode");
    expect(pairingProblem("relay_unavailable")).toBe("relayUnavailable");
    expect(pairingProblem("room_not_found")).toBe("notFound");
    expect(pairingProblem("rate_limited")).toBe("rateLimited");
    expect(pairingProblem("telegram_login_failed")).toBe("telegramLogin");
    expect(pairingProblem("network_error")).toBe("network");
    expect(pairingProblem("server_error")).toBe("generic");
    expect(pairingProblem(null)).toBe("generic");
  });
});

describe("recovery codes", () => {
  it("shows 9 groups of 4 and checks the last group", () => {
    expect(recoveryGroups(recoveryCode)).toHaveLength(9);
    expect(matchesLastGroup(recoveryCode, "r2kd")).toBe(true);
    expect(matchesLastGroup(recoveryCode, "R2KX")).toBe(false);
  });

  it("formats while typing, ignores the bento-recovery prefix casing and caps the length", () => {
    expect(formatRecoveryInput("k7qm3xra")).toBe("K7QM-3XRA");
    expect(isCompleteRecoveryCode(recoveryCode.toLowerCase().replaceAll("-", ""))).toBe(true);
    expect(formatRecoveryInput(`${recoveryCode}ABCD`)).toBe(recoveryCode);
  });

  it("maps unlock errors and reads an optional kit QR", () => {
    expect(recoveryErrorKey("recovery_code_invalid", "join.recovery.failed")).toBe("join.recovery.invalid");
    expect(recoveryErrorKey("recovery_code_checksum", "join.recovery.failed")).toBe("recovery.error.checksum");
    expect(recoveryErrorKey("server_error", "join.recovery.failed")).toBe("join.recovery.failed");
    expect(recoveryQrFrom({ recovery_code: recoveryCode })).toBeNull();
    expect(recoveryQrFrom({ recovery_qr: { rows: ["1"], size: 1 } })).toEqual({ rows: ["1"], size: 1 });
  });
});

describe("backup folder errors", () => {
  it("explains why a folder was refused", () => {
    const refused = (reason: string) => new ApiError("Bad", 400, { error: { code: "backup_source_invalid", details: { reason }, message: "" } });
    expect(backupErrorKey(refused("filesystem_root"))).toBe("backup.error.root");
    expect(backupErrorKey(refused("inside_data_dir"))).toBe("backup.error.dataDir");
    expect(backupErrorKey(refused("overlap"))).toBe("backup.error.overlap");
    expect(backupErrorKey(refused("not_directory"))).toBe("backup.error.missing");
    expect(backupErrorKey(refused("unreadable"))).toBe("backup.error.unreadable");
    expect(backupErrorKey(new Error("boom"))).toBe("backup.error.generic");
  });
});

describe("first-run gate", () => {
  it("shows first run for signed-out or vault-less devices unless local mode was chosen", () => {
    expect(decideGate(vault("signed_out"), false)).toEqual({ kind: "first-run" });
    expect(decideGate(vault("no_vault"), false)).toEqual({ kind: "first-run" });
    expect(decideGate(vault("signed_out"), true).kind).toBe("app");
    expect(decideGate(vault("locked"), false)).toEqual({ kind: "locked" });
    expect(decideGate(vault("ready"), false).kind).toBe("app");
    expect(decideGate(vault("bootstrapping"), false).kind).toBe("app");
    expect(decideGate(vault("local_only"), false).kind).toBe("app");
    expect(decideGate(null, false)).toEqual({ kind: "app", vault: null });
  });
});

describe("desktop bridge adapter", () => {
  it("is inert in the browser", async () => {
    expect(onDeepLink(vi.fn())()).toBeUndefined();
    expect(onNavigate(vi.fn())()).toBeUndefined();
    await expect(savePageAsPdf("Kit")).resolves.toBeNull();
    await expect(setDesktopPreferences({ launchAtLogin: true })).resolves.toBeNull();
  });

  it("passes only well-formed join links", () => {
    let emit: (link: unknown) => void = () => undefined;
    installBridge({ onDeepLink: vi.fn((listener) => { emit = listener; return vi.fn(); }) });
    const listener = vi.fn();
    onDeepLink(listener);
    emit({ code: "k7q2-mxr9-t4wa", kind: "join" });
    emit({ code: "K7Q2-MXR9", kind: "join" });
    emit({ code: "K7Q2-MXR9-T4WA", kind: "other" });
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith({ code: "K7Q2-MXR9-T4WA", kind: "join" });
  });

  it("maps notification targets to routes", () => {
    expect(navigationPath({ target: "recovery-kit" })).toBe("/settings/recovery");
    expect(navigationPath({ target: "settings" })).toBe("/settings");
    expect(navigationPath({ target: "drive" })).toBe("/drive");
    expect(navigationPath({ attentionId: "att 1", target: "activity" })).toBe("/activity?attention=att%201");
    expect(navigationPath({ target: "something-new" })).toBe("/activity");
  });

  it("normalizes PDF results, secure storage modes and login item errors", async () => {
    installBridge({ savePageAsPdf: vi.fn(async () => ({ saved: false })) });
    await expect(savePageAsPdf("Kit")).resolves.toEqual({ fileName: undefined, saved: false });
    expect(secureStorageMode({ secureStorage: "file" } as never)).toBe("file");
    expect(secureStorageMode({ secureStorage: "available" } as never)).toBe("os");
    expect(secureStorageMode(null)).toBeNull();
    expect(isLaunchAtLoginError(new Error("Error invoking remote method 'bento:preferences-set': Error: preferences_launch_at_login_failed"))).toBe(true);
    expect(isLaunchAtLoginError(new Error("TypeError"))).toBe(false);
  });
});
