"""Publish and import against a fake `gh` and a local bare remote: nothing reaches GitHub."""

from __future__ import annotations

import datetime as dt
import json
import os
import stat
import sys
import unittest
from pathlib import Path

from helpers import HAVE_SSH_KEYGEN, TempDirTest

from bento_release import build, changelog, publish, signing

V = "0.1.0"

FAKE_GH = r'''#!PYTHON
import json, os, sys
state_path = os.environ["FAKE_GH_STATE"]
state = json.load(open(state_path)) if os.path.exists(state_path) else {"calls": [], "releases": {}}
args = sys.argv[1:]
state["calls"].append(args)
code = 0
if args[:2] == ["release", "view"]:
    tag = args[2]
    if tag not in state["releases"]:
        code = 1
    elif "--json" in args:
        print(json.dumps({"assets": state["releases"][tag]}))
elif args[:2] == ["release", "create"]:
    tag = args[2]
    files = [a for a in args[3:] if os.path.isfile(a) and not a.endswith(".md")]
    state["releases"][tag] = [{"name": os.path.basename(f).replace(" ", "."), "size": os.path.getsize(f)} for f in files]
    if os.environ.get("FAKE_GH_DROP_ONE"):
        state["releases"][tag].pop()
json.dump(state, open(state_path, "w"))
sys.exit(code)
'''


@unittest.skipUnless(HAVE_SSH_KEYGEN, "ssh-keygen not installed")
class PublishTest(TempDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.git_fixture()
        notes = self.root / "CHANGELOG.md"
        notes.write_text(changelog.cut(notes.read_text(), V, dt.date(2026, 12, 1)))
        self.key = self.ssh_key()
        line = signing.allowed_signers_line(signing.public_key_of(self.key))
        allowed = self.root / build.ALLOWED_SIGNERS
        allowed.parent.mkdir(parents=True, exist_ok=True)
        allowed.write_text(line + "\n")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "release key")
        self.git(self.root, "config", "gpg.format", "ssh")
        self.git(self.root, "config", "user.signingkey", str(self.key))
        self.remote = self.tmp / "remote.git"
        self.git(self.tmp, "init", "-q", "--bare", str(self.remote))
        self.git(self.root, "remote", "add", "origin", str(self.remote))
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH.replace("PYTHON", sys.executable))
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.state = self.tmp / "gh-state.json"
        self._saved_path = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{self._saved_path}"
        os.environ["FAKE_GH_STATE"] = str(self.state)
        self.out = self.tmp / "out"

    def tearDown(self) -> None:
        os.environ["PATH"] = self._saved_path
        os.environ.pop("FAKE_GH_STATE", None)
        os.environ.pop("FAKE_GH_DROP_ONE", None)
        super().tearDown()

    def release_build(self, mode: str = "release") -> None:
        commit = self.git(self.root, "rev-parse", "HEAD")
        directory = self.out / f"v{V}"
        directory.mkdir(parents=True)
        for name in (f"bento_api-{V}-py3-none-any.whl", f"bento_api-{V}.tar.gz", "install.sh", "install.ps1"):
            (directory / name).write_text(f"content of {name}")
        report = build.Report(version=V, mode=mode, commit=commit, dirty=False, host="linux-x64", created="2026-11-24T00:00:00+00:00")
        report.components["backend@linux-x64"] = {"status": "built"}
        build.finalize(self.root, self.out, V, report, self.key, release=mode == "release")

    def calls(self) -> list[list[str]]:
        return json.loads(self.state.read_text())["calls"] if self.state.exists() else []

    def allowed(self) -> set[str]:
        return {"desktop-linux-x64", "desktop-windows-x64", "desktop-macos-x64", "desktop-macos-arm64", "cli-linux-x64", "cli-linux-arm64", "cli-macos-x64", "cli-macos-arm64", "cli-windows-x64", "sbom"}

    def test_signed_tag_then_publish(self) -> None:
        self.assertEqual(publish.create_tags(self.root, V, ["product"]), ["v0.1.0"])
        self.assertIn("-----BEGIN SSH SIGNATURE-----", self.git(self.root, "cat-file", "tag", "v0.1.0"))
        self.release_build()
        publish.publish(self.root, self.out, V, ["product"], allow_missing=self.allowed(), assume_yes=True)
        self.assertEqual(self.git(self.remote, "rev-parse", "v0.1.0^{commit}"), self.git(self.root, "rev-parse", "HEAD"))
        verbs = [call[:2] + call[2:3] for call in self.calls()]
        self.assertEqual(verbs, [["release", "view", "v0.1.0"], ["release", "create", "v0.1.0"], ["release", "view", "v0.1.0"], ["release", "edit", "v0.1.0"]])
        create = self.calls()[1]
        for flag in ("--verify-tag", "--draft", "--notes-file"):
            self.assertIn(flag, create)
        self.assertIn(str(self.out / "v0.1.0" / "SHA256SUMS.sig"), create)
        self.assertEqual(self.calls()[3][-2:], ["--draft=false", "--latest"])

    def test_refuses_dry_runs_missing_targets_and_unsigned_tags(self) -> None:
        self.release_build(mode="dry-run")
        problems = "\n".join(publish.publish_problems(self.root, self.out, V, ["product"], set()))
        self.assertIn("dry-run build", problems)
        self.assertIn("desktop-windows-x64 is missing", problems)
        self.assertIn("tag v0.1.0 does not exist", problems)
        self.git(self.root, "tag", "-a", "v0.1.0", "-m", "unsigned")
        problems = "\n".join(publish.publish_problems(self.root, self.out, V, ["product"], set()))
        self.assertIn("is not signed", problems)
        self.assertEqual(self.calls(), [])

    def test_tampered_asset_blocks_publishing(self) -> None:
        publish.create_tags(self.root, V, ["product"])
        self.release_build()
        (self.out / "v0.1.0" / "install.sh").write_text("tampered")
        with self.assertRaises(build.ReleaseError) as raised:
            publish.publish(self.root, self.out, V, ["product"], allow_missing=self.allowed(), assume_yes=True)
        self.assertIn("install.sh does not match", str(raised.exception))
        self.assertEqual(self.calls(), [])

    def test_draft_with_a_missing_upload_is_not_published(self) -> None:
        publish.create_tags(self.root, V, ["product"])
        self.release_build()
        os.environ["FAKE_GH_DROP_ONE"] = "1"
        with self.assertRaises(build.ReleaseError):
            publish.publish(self.root, self.out, V, ["product"], allow_missing=self.allowed(), assume_yes=True)
        self.assertNotIn("edit", [call[1] for call in self.calls()])

    def test_import_checks_the_transfer_and_the_commit(self) -> None:
        self.release_build()
        other = self.tmp / "from-mac"
        (other / "v0.1.0").mkdir(parents=True)
        (other / "v0.1.0" / "bento-cli-0.1.0-macos-arm64.tar.gz").write_text("mac cli")
        signing.write_sums(other / "v0.1.0")
        commit = self.git(self.root, "rev-parse", "HEAD")
        mac = build.Report(version=V, mode="release", commit=commit, dirty=False, host="macos-arm64", created="2026-11-24T00:00:00+00:00")
        mac.components["cli@macos-arm64"] = {"status": "built"}
        (other / "report.json").write_text(json.dumps({**mac.__dict__, "channels": {}}))
        channels = publish.import_artifacts(self.root, self.out, V, [other], self.key)
        self.assertIn("bento-cli-0.1.0-macos-arm64.tar.gz", channels["v0.1.0"]["assets"])
        self.assertNotIn("cli-macos-arm64", channels["v0.1.0"]["missing"])
        self.assertEqual(signing.check_sums(self.out / "v0.1.0"), [])
        self.assertTrue(channels["v0.1.0"]["signed"])

        (other / "v0.1.0" / "bento-cli-0.1.0-macos-arm64.tar.gz").write_text("corrupted in transit")
        with self.assertRaises(build.ReleaseError):
            publish.import_artifacts(self.root, self.out, V, [other], self.key)
        mac.commit = "f" * 40
        signing.write_sums(other / "v0.1.0")
        (other / "report.json").write_text(json.dumps({**mac.__dict__, "channels": {}}))
        with self.assertRaises(build.ReleaseError):
            publish.import_artifacts(self.root, self.out, V, [other], self.key)


class AliasTest(unittest.TestCase):
    def test_publish_flag_is_an_alias(self) -> None:
        from bento_release import cli

        args = cli.parser().parse_args(["publish", "--channel", "android"])
        self.assertEqual(args.func, cli.cmd_publish)
        self.assertEqual(publish.github_asset_name("Bento-0.1.0 Setup.exe"), "Bento-0.1.0.Setup.exe")
        self.assertIsNone(publish.default_signing_key(None) if "BENTO_RELEASE_SIGNING_KEY" not in os.environ else None)
        self.assertEqual(Path(publish.default_signing_key("~/k")).name, "k")


if __name__ == "__main__":
    unittest.main()
