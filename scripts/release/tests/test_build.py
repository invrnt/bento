from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import HAVE_SSH_KEYGEN, REPO, TempDirTest

from bento_release import build, cli, inventory, signing

V = "0.1.0"


def write(directory: Path, names: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(f"content of {name}".encode())


class InventoryTest(unittest.TestCase):
    def test_classifies_the_names_the_site_and_updaters_use(self) -> None:
        cases = {
            "bento_0.1.0_amd64.deb": "desktop-linux-x64",
            "bento-desktop_0.1.0_amd64.deb": "desktop-linux-x64",
            "Bento-linux-x64-0.1.0.zip": "desktop-linux-x64",
            "bento-update-linux-x64.json.sig": "desktop-linux-x64",
            "Bento-0.1.0-Setup.exe": "desktop-windows-x64",
            "RELEASES": "desktop-windows-x64",
            "Bento-0.1.0-arm64.dmg": "desktop-macos-arm64",
            "SHA256SUMS-macos-x64": "desktop-macos-x64",
            "bento-cli-0.1.0-linux-arm64.tar.gz": "cli-linux-arm64",
            "bento-cli_0.1.0_amd64.deb": "cli-linux-x64",
            "bento-cli-0.1.0-windows-x64.zip": "cli-windows-x64",
            "install.ps1": "cli-installers",
            "bento_api-0.1.0-py3-none-any.whl": "backend",
            "bento-0.1.0-npm-web.cdx.json": "sbom",
            "bento-android-0.1.0-universal.apk": "android",
            "bento-update-android-arm64.json.sig": "android",
            "SHA256SUMS-android-0.1.0.txt": "android",
            "bento-0.1.0-android-gradle.cdx.json": "android-sbom",
        }
        for name, target in cases.items():
            with self.subTest(name=name):
                self.assertEqual(inventory.classify(name, V).id, target)
        for name in ("Bento-0.2.0-Setup.exe", "notes.txt", "bento-cli-0.1.0-linux-x64.tar.gz.sha256", "Bento-0.1.0 Setup.exe"):
            with self.subTest(name=name):
                self.assertIsNone(inventory.classify(name, V))

    def test_site_checksum_targets_are_produced(self) -> None:
        # apps/site/scripts/lib/release.mjs links SHA256SUMS-<target> for these targets.
        site = (REPO / "apps/site/scripts/lib/release.mjs").read_text(encoding="utf-8")
        for target in ("linux-x64", "windows-x64", "macos-x64", "macos-arm64"):
            self.assertIn(f'"{target}": "{target}"', site)
            self.assertIsNotNone(inventory.classify(f"SHA256SUMS-{target}", V))

    def test_missing_and_unsigned(self) -> None:
        names = {"bento_api-0.1.0-py3-none-any.whl", "bento-update-linux-x64.json"}
        missing = inventory.missing(names, inventory.PRODUCT, V)
        self.assertEqual(missing["backend"], [r"^bento_api-0\.1\.0\.tar\.gz$"])
        self.assertIn("desktop-windows-x64", missing)
        self.assertEqual(inventory.unsigned_manifests(names), ["bento-update-linux-x64.json"])
        self.assertEqual(inventory.tag_for(inventory.ANDROID, V), "android-v0.1.0")


class RemoveTargetsTest(TempDirTest):
    def test_rebuilding_a_target_keeps_imported_files(self) -> None:
        directory = self.tmp / "v0.1.0"
        write(directory, ["Bento-linux-x64-0.1.0.zip", "Bento-0.1.0-x64.dmg", "SHA256SUMS"])
        build.remove_targets(directory, V, {"desktop-linux-x64"})
        self.assertEqual(sorted(p.name for p in directory.iterdir()), ["Bento-0.1.0-x64.dmg", "SHA256SUMS"])


class FinalizeTest(TempDirTest):
    def report(self, mode: str = "dry-run") -> build.Report:
        return build.Report(version=V, mode=mode, commit="0" * 40, dirty=False, host="linux-x64", created="2026-11-24T00:00:00+00:00")

    def test_unsigned_dry_run_report(self) -> None:
        out = self.tmp / "out"
        write(out / "v0.1.0", ["bento_api-0.1.0-py3-none-any.whl", "bento_api-0.1.0.tar.gz", "stray.bin"])
        channels = build.finalize(REPO, out, V, self.report(), None, release=False)
        info = channels["v0.1.0"]
        self.assertFalse(info["signed"])
        self.assertNotIn("backend", info["missing"])
        self.assertEqual(info["unknown"], ["stray.bin"])
        self.assertEqual(signing.check_sums(out / "v0.1.0"), [])
        report = (out / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("Dry run: these files must never be published", report)
        self.assertIn("`desktop-windows-x64` (build on Windows x64)", report)
        notes = (out / "notes" / "v0.1.0.md").read_text(encoding="utf-8")
        self.assertIn("### Added", notes)
        self.assertIn("ssh-keygen -Y verify -f allowed_signers -I bento-release -n bento-release", notes)
        self.assertEqual(json.loads((out / "report.json").read_text())["channels"]["v0.1.0"]["tag"], "v0.1.0")

    @unittest.skipUnless(HAVE_SSH_KEYGEN, "ssh-keygen not installed")
    def test_dry_run_signs_and_checks_against_the_key_itself(self) -> None:
        out = self.tmp / "out"
        write(out / "v0.1.0", ["bento_api-0.1.0.tar.gz"])
        write(out / "android-v0.1.0", ["bento-0.1.0-android-gradle.cdx.json"])
        channels = build.finalize(REPO, out, V, self.report(), self.ssh_key(), release=False)
        for tag in ("v0.1.0", "android-v0.1.0"):
            self.assertTrue(channels[tag]["signed"])
            self.assertTrue((out / tag / "SHA256SUMS.sig").is_file())
        self.assertIn("own public key", channels["v0.1.0"]["signature_checked_against"])


class PreflightTest(TempDirTest):
    def test_release_mode_is_strict(self) -> None:
        root = self.git_fixture()
        (root / "untracked.txt").write_text("x")
        options = build.Options(root=root, version=V, out=self.tmp / "out", release=True, components=("backend",))
        with self.assertRaises(build.ReleaseError) as raised:
            build.Build(options).preflight()
        message = str(raised.exception)
        for expected in ("no ## [0.1.0] section", "not clean", "tag v0.1.0 does not exist", "evidence/local-ci.md", "signing key", "allowed_signers"):
            self.assertIn(expected, message)

    def test_dry_run_tolerates_what_a_release_refuses(self) -> None:
        root = self.git_fixture()
        (root / "untracked.txt").write_text("x")
        b = build.Build(build.Options(root=root, version=V, out=self.tmp / "out", components=("backend",)))
        b.preflight()
        self.assertIn("built from a working tree with uncommitted changes", b.report.notes)

    def test_version_mismatch_fails_even_in_a_dry_run(self) -> None:
        root = self.git_fixture()
        with self.assertRaises(build.ReleaseError):
            build.Build(build.Options(root=root, version="0.2.0", out=self.tmp / "out", components=("backend",))).preflight()

    def test_ci_evidence_accepts_an_ancestor_that_only_differs_in_the_log(self) -> None:
        root = self.git_fixture()
        tested = self.git(root, "rev-parse", "HEAD")
        evidence = root / build.EVIDENCE
        evidence.parent.mkdir(parents=True)
        evidence.write_text(f"# Local CI Evidence\n\n### Local CI PASS — `{tested[:10]}` (HEAD)\n\n- Commit `{tested}` · tree `x`\n")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "evidence")
        self.assertEqual(build.ci_evidence_problems(root, self.git(root, "rev-parse", "HEAD")), [])
        (root / "VERSION").write_text("0.1.0\n\n")
        self.git(root, "commit", "-qam", "untested change")
        self.assertTrue(build.ci_evidence_problems(root, self.git(root, "rev-parse", "HEAD")))


class RunnerTest(TempDirTest):
    def test_logs_redact_secret_values_and_failures_raise(self) -> None:
        import os
        import sys

        from bento_release.runner import Runner, StepError

        env = {**os.environ, "BENTO_TELEGRAM_API_HASH": "0123456789abcdef-not-a-real-hash"}
        runner = Runner(self.tmp, self.tmp / "logs", env)
        log = runner.run("echo", [sys.executable, "-c", "import os; print('hash=' + os.environ['BENTO_TELEGRAM_API_HASH'])"])
        text = log.read_text()
        self.assertIn("hash=[redacted]", text)
        self.assertNotIn("not-a-real-hash", text)
        with self.assertRaises(StepError):
            runner.run("fail", [sys.executable, "-c", "raise SystemExit(3)"])


class CliTest(unittest.TestCase):
    def test_components_and_aliases(self) -> None:
        args = cli.parser().parse_args(["build", "--only", "backend,cli", "--skip", "cli"])
        self.assertEqual(cli._components(args), ("backend",))
        with self.assertRaises(build.ReleaseError):
            cli._components(cli.parser().parse_args(["build", "--only", "ios"]))
        self.assertEqual(cli.main(["version", "check"]), 0)


if __name__ == "__main__":
    unittest.main()
