import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

const desktopRoot = path.resolve(import.meta.dirname, "..");

describe("native packaging scaffold", () => {
  it("packages an asar app with a platform-native sidecar resource and no development sources", async () => {
    const forgeSource = await readFile(path.join(desktopRoot, "forge.config.cjs"), "utf8");
    expect(forgeSource).toContain("asar: true");
    expect(forgeSource).toContain("resources\", \"sidecars\", `${process.platform}-${process.arch}`");
    for (const excluded of ["src", "tests", "scripts", "resources"]) {
      expect(forgeSource).toMatch(new RegExp(`\\^\\\\/${excluded}\\(\\$\\|`, "u"));
    }
    expect(forgeSource).not.toMatch(/\.env(?:\.example)?["']/u);
  });

  it("locks production Electron fuses against Node/inspect escape hatches", async () => {
    const forgeSource = await readFile(path.join(desktopRoot, "forge.config.cjs"), "utf8");
    expect(forgeSource).toMatch(/RunAsNode\]: false/u);
    expect(forgeSource).toMatch(/EnableNodeOptionsEnvironmentVariable\]: false/u);
    expect(forgeSource).toMatch(/EnableNodeCliInspectArguments\]: false/u);
    expect(forgeSource).toMatch(/EnableEmbeddedAsarIntegrityValidation\]: true/u);
    expect(forgeSource).toMatch(/OnlyLoadAppFromAsar\]: true/u);
    expect(forgeSource).toMatch(/EnableCookieEncryption\]: true/u);
  });

  it("declares native makers without pretending to cross-compile sidecars", async () => {
    const forgeSource = await readFile(path.join(desktopRoot, "forge.config.cjs"), "utf8");
    expect(forgeSource).toContain("@electron-forge/maker-squirrel");
    expect(forgeSource).toContain("@electron-forge/maker-dmg");
    expect(forgeSource).toContain("@electron-forge/maker-deb");
    expect(forgeSource).toContain("@electron-forge/maker-zip");
    expect(forgeSource).toContain('platforms: ["win32"]');
    expect(forgeSource).toContain('platforms: ["darwin"]');
    expect(forgeSource).toContain('platforms: ["linux"]');
    expect(forgeSource).toContain('bin: "bento"');
    expect(forgeSource).toContain("process.platform");
    expect(forgeSource).toContain("process.arch");
  });

  it("uses Bento artwork and accurate package metadata instead of Electron defaults", async () => {
    const forgeSource = await readFile(path.join(desktopRoot, "forge.config.cjs"), "utf8");
    const packageJson = JSON.parse(await readFile(path.join(desktopRoot, "package.json"), "utf8")) as {
      homepage: string;
      repository: { url: string };
    };
    expect(forgeSource).toContain('"resources", "icons", "bento"');
    expect(forgeSource).toContain("setupIcon");
    expect(forgeSource).toContain("github.com/invrnt/bento");
    expect(packageJson.homepage).toBe("https://github.com/invrnt/bento");
    expect(packageJson.repository.url).toContain("invrnt/bento.git");
  });

  it("only enables platform signing when the release workflow explicitly opts in", async () => {
    const forgeSource = await readFile(path.join(desktopRoot, "forge.config.cjs"), "utf8");
    expect(forgeSource).toContain('BENTO_MAC_SIGNING === "1"');
    expect(forgeSource).toContain('BENTO_WINDOWS_SIGNING === "1"');
    expect(forgeSource).toContain("APPLE_APP_SPECIFIC_PASSWORD");
    expect(forgeSource).toContain("WINDOWS_CERTIFICATE_PASSWORD");
  });

  it("provides a bounded packaged smoke using an isolated user profile", async () => {
    const packageJson = JSON.parse(await readFile(path.join(desktopRoot, "package.json"), "utf8")) as {
      scripts: Record<string, string>;
    };
    expect(packageJson.scripts["smoke:packaged"]).toBe("node scripts/smoke-packaged.mjs");
    const smoke = await readFile(path.join(desktopRoot, "scripts", "smoke-packaged.mjs"), "utf8");
    expect(smoke).toContain("BENTO_DESKTOP_SMOKE");
    expect(smoke).toContain("XDG_CONFIG_HOME");
    expect(smoke).toContain("45_000");
    expect(smoke).toContain('child.kill("SIGKILL")');
    expect(smoke).toMatch(/electron\\\/default_app\|localhost:5173\|ERR_FILE_NOT_FOUND/u);
    expect(smoke).toContain("await rm(profile, { recursive: true, force: true })");
    expect(smoke).toContain("retention");
    expect(smoke).toContain("--user-data-dir=");
  });

  it("pins native CI actions and keeps PR builds secret-free", async () => {
    const repositoryRoot = path.resolve(desktopRoot, "../..");
    const native = await readFile(path.join(repositoryRoot, ".github", "workflows", "desktop-native.yml"), "utf8");
    const release = await readFile(path.join(repositoryRoot, ".github", "workflows", "desktop-release.yml"), "utf8");
    const bump = await readFile(path.join(repositoryRoot, ".github", "workflows", "desktop-version-bump.yml"), "utf8");
    for (const workflow of [native, release]) {
      expect(workflow).toContain("ubuntu-22.04");
      expect(workflow).toContain("windows-2025");
      expect(workflow).toContain("macos-15-intel");
      expect(workflow).toContain("macos-15");
      expect(workflow).toContain('node-version: "24"');
      expect(workflow).toContain('python-version: "3.12"');
      for (const match of workflow.matchAll(/uses:\s+[^@\s]+@([^\s]+)/gu)) {
        expect(match[1]).toMatch(/^[a-f0-9]{40}$/u);
      }
    }
    for (const match of bump.matchAll(/uses:\s+[^@\s]+@([^\s]+)/gu)) {
      expect(match[1]).toMatch(/^[a-f0-9]{40}$/u);
    }
    expect(native).not.toContain("secrets.");
    expect(native).toContain("unsigned");
    expect(release).toContain("Production release blocked");
    expect(release).toContain("validate-release-tag.mjs");
    expect(release).toContain("stage-artifacts.mjs");
    expect(release).toContain("codesign --verify --deep --strict");
    expect(release).toContain("Get-AuthenticodeSignature");
    expect(release).toContain("attest-build-provenance");
    expect(release).toContain("generate-update-manifest.mjs");
    expect(release).toContain("collect-release-assets.mjs");
    expect(release).toContain('gh release upload "$GITHUB_REF_NAME" "${artifacts[@]}" --clobber');
    expect(release).toContain("Published release asset inventory does not match");
    expect(release).toContain("Release digest mismatch");
    expect(release).toContain('git rev-list -n 1 "$GITHUB_REF"');
    expect(release).toContain("desktop-production-release");
    expect(bump).toContain("bump-version.mjs");
    expect(bump).toContain("actions: write");
    expect(bump).toContain('gh workflow run desktop-native.yml --ref "$VERSION_BRANCH"');
    expect(bump).toContain('git ls-remote --exit-code --heads origin "$branch"');
    expect(bump).toContain("apps/api/src/bento/domain/settings_registry.py");
    expect(bump).toContain("Reusing open pull request");
    expect(bump).toContain("desktop-version-bump");
  });
});
