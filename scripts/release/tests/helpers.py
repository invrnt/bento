"""Shared fixtures: throwaway SSH keys and minimal git repositories in temporary directories."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RELEASE_DIR = Path(__file__).resolve().parents[1]
REPO = RELEASE_DIR.parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from bento_release import versioning  # noqa: E402

# The repository files a version fixture copies (every version site, VERSION, CHANGELOG, the Android build).
FIXTURE_FILES = sorted({site.path for site in versioning.SITES} | {"VERSION", "CHANGELOG.md", versioning.ANDROID_GRADLE})

HAVE_SSH_KEYGEN = shutil.which("ssh-keygen") is not None


class TempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="bento-release-test-")
        self.tmp = Path(self._tmp.name)
        # Isolate git from the developer's own configuration (signing keys, hooks, templates).
        self._env = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")}
        os.environ.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="Test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
        )

    def tearDown(self) -> None:
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def ssh_key(self, name: str = "release") -> Path:
        """A throwaway, passphrase-less Ed25519 key that exists only inside this test's temp dir."""
        key = self.tmp / "keys" / name
        key.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "throwaway-test-key", "-f", str(key)], check=True)
        return key

    def version_fixture(self) -> Path:
        root = self.tmp / "repo"
        for relative in FIXTURE_FILES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / relative, target)
        return root

    def git(self, root: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()

    def git_fixture(self) -> Path:
        root = self.version_fixture()
        self.git(root, "init", "-q", "-b", "main")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "fixture")
        return root
