from __future__ import annotations

import os
import subprocess
import unittest

from helpers import HAVE_SSH_KEYGEN, REPO, TempDirTest

from bento_release import signing


def assets(directory, files=None):
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {"a.zip": b"alpha", "b.deb": b"beta"}).items():
        (directory / name).write_bytes(content)
    return directory


class ChecksumTest(TempDirTest):
    def test_sums_cover_every_asset_and_detect_changes(self) -> None:
        directory = assets(self.tmp / "assets")
        signing.write_sums(directory)
        entries = signing.parse_sums((directory / "SHA256SUMS").read_text())
        self.assertEqual(sorted(entries), ["a.zip", "b.deb"])
        self.assertEqual(signing.check_sums(directory), [])
        (directory / "a.zip").write_bytes(b"tampered")
        (directory / "c.txt").write_bytes(b"new")
        problems = signing.check_sums(directory)
        self.assertIn("a.zip does not match its SHA-256", problems)
        self.assertIn("c.txt is not listed in SHA256SUMS", problems)

    def test_sha256sum_tool_accepts_the_format(self) -> None:
        directory = assets(self.tmp / "assets")
        signing.write_sums(directory)
        if subprocess.run(["sha256sum", "--version"], capture_output=True).returncode == 0:
            subprocess.run(["sha256sum", "--check", "--strict", "SHA256SUMS"], cwd=directory, check=True, capture_output=True)

    def test_refuses_collisions_links_dirs_and_empty_files(self) -> None:
        for name, setup in (
            ("case", lambda d: (d / "A.ZIP").write_bytes(b"x")),
            ("dir", lambda d: (d / "sub").mkdir()),
            ("link", lambda d: os.symlink(d / "a.zip", d / "l.zip")),
            ("empty", lambda d: (d / "e.bin").write_bytes(b"")),
        ):
            with self.subTest(name=name):
                directory = assets(self.tmp / name)
                setup(directory)
                with self.assertRaises(signing.SigningError):
                    signing.write_sums(directory)

    def test_rejects_malformed_lines(self) -> None:
        for line in ("abc  file", "0" * 64 + " file", "0" * 64 + "  dir/file"):
            with self.subTest(line=line), self.assertRaises(signing.SigningError):
                signing.parse_sums(line + "\n")


@unittest.skipUnless(HAVE_SSH_KEYGEN, "ssh-keygen not installed")
class SignatureTest(TempDirTest):
    def signed(self):
        key = self.ssh_key()
        directory = assets(self.tmp / "assets")
        signing.write_sums(directory)
        signing.sign(directory, key)
        allowed = self.tmp / "allowed_signers"
        allowed.write_text(signing.allowed_signers_line(signing.public_key_of(key)) + "\n")
        return key, directory, allowed

    def test_sign_and_verify(self) -> None:
        _, directory, allowed = self.signed()
        self.assertIn('Good "bento-release" signature', signing.verify(directory, allowed))

    def test_tampered_sums_fail(self) -> None:
        _, directory, allowed = self.signed()
        sums = directory / "SHA256SUMS"
        sums.write_text(sums.read_text().replace("a.zip", "x.zip"))
        with self.assertRaises(signing.SigningError):
            signing.verify(directory, allowed)

    def test_other_key_and_empty_allowed_signers_fail(self) -> None:
        _, directory, _ = self.signed()
        stranger = self.ssh_key("stranger")
        other = self.tmp / "other_signers"
        other.write_text(signing.allowed_signers_line(signing.public_key_of(stranger)) + "\n")
        with self.assertRaises(signing.SigningError):
            signing.verify(directory, other)
        empty = self.tmp / "empty"
        empty.write_text("# comments only\n")
        with self.assertRaises(signing.SigningError):
            signing.verify(directory, empty)

    def test_signature_from_another_namespace_is_rejected(self) -> None:
        key, directory, allowed = self.signed()
        (directory / "SHA256SUMS.sig").unlink()
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "git", str(directory / "SHA256SUMS")], check=True, capture_output=True)
        with self.assertRaises(signing.SigningError):
            signing.verify(directory, allowed)

    def test_public_key_from_private_key_without_pub_file(self) -> None:
        key = self.ssh_key()
        expected = key.with_name(key.name + ".pub").read_text().split()[:2]
        key.with_name(key.name + ".pub").unlink()
        self.assertEqual(signing.public_key_of(key).split()[:2], expected)

    def test_rewriting_sums_drops_a_stale_signature(self) -> None:
        _, directory, _ = self.signed()
        signing.write_sums(directory)
        self.assertFalse((directory / "SHA256SUMS.sig").exists())


class AllowedSignersFileTest(unittest.TestCase):
    def test_committed_file_has_only_valid_entries(self) -> None:
        for entry in signing.allowed_signers_entries(REPO / "scripts/release/allowed_signers"):
            fields = entry.split()
            self.assertEqual(fields[0], signing.PRINCIPAL)
            self.assertEqual(fields[1], f'namespaces="{signing.NAMESPACE}"')
            self.assertTrue(fields[2].startswith("ssh-"))


if __name__ == "__main__":
    unittest.main()
