from __future__ import annotations

import json
import unittest

from helpers import REPO, TempDirTest

from bento_release import versioning


class RepositoryVersionTest(unittest.TestCase):
    def test_every_manifest_in_this_checkout_matches_version(self) -> None:
        self.assertEqual(versioning.check(REPO), [])

    def test_version_is_stable_semver(self) -> None:
        versioning.parse(versioning.read_version(REPO))


class BumpTest(unittest.TestCase):
    def test_kinds(self) -> None:
        self.assertEqual(versioning.bumped("0.1.9", "patch"), "0.1.10")
        self.assertEqual(versioning.bumped("0.1.9", "minor"), "0.2.0")
        self.assertEqual(versioning.bumped("0.1.9", "major"), "1.0.0")
        self.assertEqual(versioning.bumped("0.1.9", "2.3.4"), "2.3.4")

    def test_rejects_prerelease_and_android_overflow(self) -> None:
        for bad in ("1.0.0-rc.1", "v1.0.0", "01.0.0", "1.0", "1.1000.0"):
            with self.subTest(bad=bad), self.assertRaises(versioning.VersionError):
                versioning.parse(bad)
        with self.assertRaises(versioning.VersionError):
            versioning.bumped("0.999.0", "minor")
        with self.assertRaises(versioning.VersionError):
            versioning.bumped("0.1.0", "huge")


class FixtureTest(TempDirTest):
    def test_set_version_rewrites_every_site(self) -> None:
        root = self.version_fixture()
        before = {site.path: (root / site.path).read_text(encoding="utf-8") for site in versioning.SITES}
        written = versioning.set_version(root, "0.2.0")
        self.assertIn("VERSION", written)
        self.assertEqual(versioning.read_version(root), "0.2.0")
        self.assertEqual(versioning.check(root), [])
        for name in ("apps/desktop", "apps/web"):
            lock = json.loads((root / name / "package-lock.json").read_text(encoding="utf-8"))
            self.assertEqual((lock["version"], lock["packages"][""]["version"]), ("0.2.0", "0.2.0"))
        # Only the version changed: same number of lines, and no other dependency's version moved.
        for path, text in before.items():
            after = (root / path).read_text(encoding="utf-8")
            self.assertEqual(len(text.splitlines()), len(after.splitlines()), path)
        uv_lock = (root / "apps/api/uv.lock").read_text(encoding="utf-8")
        self.assertEqual(uv_lock.count('version = "0.2.0"'), before["apps/api/uv.lock"].count('version = "0.2.0"') + 1)

    def test_check_reports_a_drifted_manifest(self) -> None:
        root = self.version_fixture()
        path = root / "apps/api/src/bento/__init__.py"
        path.write_text(path.read_text(encoding="utf-8").replace('__version__ = "', '__version__ = "9'), encoding="utf-8")
        problems = versioning.check(root)
        self.assertEqual(len(problems), 1)
        self.assertIn("bento.__version__", problems[0])

    def test_bump_refuses_inconsistent_manifests_and_writes_nothing(self) -> None:
        root = self.version_fixture()
        lock = root / "apps/web/package-lock.json"
        lock.write_text(lock.read_text(encoding="utf-8").replace('"version": "0.1.0"', '"version": "0.0.9"', 1), encoding="utf-8")
        snapshot = {p: (root / p).read_text(encoding="utf-8") for p in ("VERSION", "apps/desktop/package.json")}
        with self.assertRaises(versioning.VersionError):
            versioning.set_version(root, "0.1.1")
        for path, text in snapshot.items():
            self.assertEqual((root / path).read_text(encoding="utf-8"), text)

    def test_android_must_keep_reading_version(self) -> None:
        root = self.version_fixture()
        gradle = root / versioning.ANDROID_GRADLE
        gradle.write_text(gradle.read_text(encoding="utf-8").replace('rootProject.file("../../VERSION")', '"0.1.0"'), encoding="utf-8")
        self.assertTrue(any("Android" in problem for problem in versioning.check(root)))


if __name__ == "__main__":
    unittest.main()
