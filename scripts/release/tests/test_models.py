"""The smart search model mirror hook (D3) against a temporary manifest, tiny fake model files and a fake
`gh`: nothing is downloaded and nothing reaches GitHub."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import unittest
from pathlib import Path

from helpers import HAVE_SSH_KEYGEN, TempDirTest
from test_publish import FAKE_GH

from bento_release import build, cli, models, signing

REVISION = "6ea3e3a309d12a4779cfda98b8c19800d2d5da71"
TAG = "models-embeddinggemma-2-6ea3e3a3"
WEIGHTS = b"GGUF fake weights for the mirror test\n" * 64


def manifest(*, mirror: str | None = None, sha256: str | None = None, size: int | None = None) -> dict[str, object]:
    name = "embeddinggemma-2-Q8_0.gguf"
    return {
        "schema_version": 1,
        "default_model_id": "embeddinggemma-2-q8_0",
        "models": [
            {
                "model_id": "embeddinggemma-2-q8_0",
                "revision": REVISION,
                "display_name": "EmbeddingGemma 2",
                "license_spdx": "Apache-2.0",
                "source_url": f"https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/tree/{REVISION}",
                "files": [
                    {
                        "name": name,
                        "role": "weights",
                        "urls": [
                            f"https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/{REVISION}/{name}",
                            mirror or models.mirror_url(TAG, name),
                        ],
                        "size_bytes": len(WEIGHTS) if size is None else size,
                        "sha256": sha256 or hashlib.sha256(WEIGHTS).hexdigest(),
                    }
                ],
            },
            {
                "model_id": "qwen3-embedding-0.6b-q8_0",
                "revision": "370f27d7550e0def9b39c1f16d3fbaa13aa67728",
                "display_name": "Qwen3-Embedding-0.6B",
                "license_spdx": "Apache-2.0",
                "source_url": "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/tree/370f27d7550e0def9b39c1f16d3fbaa13aa67728",
                "files": [
                    {
                        "name": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                        "role": "weights",
                        "urls": ["https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/370f27d7550e0def9b39c1f16d3fbaa13aa67728/Qwen3-Embedding-0.6B-Q8_0.gguf"],
                        "size_bytes": 639150592,
                        "sha256": "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439",
                    }
                ],
            },
        ],
    }


class MirrorTestCase(TempDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.manifest_path = self.tmp / "manifest.json"
        self.write_manifest(manifest())
        self.source = self.tmp / "downloads"
        self.source.mkdir()
        (self.source / "embeddinggemma-2-Q8_0.gguf").write_bytes(WEIGHTS)
        self.licenses = self.tmp / "licenses"
        self.licenses.mkdir()
        (self.licenses / "Apache-2.0.txt").write_text("Apache License\nVersion 2.0, January 2004\n")
        self.out = self.tmp / "models-out"

    def write_manifest(self, data: dict[str, object]) -> None:
        self.manifest_path.write_text(json.dumps(data))


class PlanTest(MirrorTestCase):
    def test_only_files_with_a_github_mirror_are_planned(self) -> None:
        grouped, problems = models.plan(self.tmp, self.manifest_path)
        self.assertEqual(problems, [])
        self.assertEqual(list(grouped), [TAG])
        self.assertEqual([item.name for item in grouped[TAG]], ["embeddinggemma-2-Q8_0.gguf"])
        self.assertEqual(models.mirror_tag("EmbeddingGemma 2", REVISION), TAG)
        self.assertEqual(models.mirror_url(TAG, "x.gguf"), f"https://github.com/invrnt/bento/releases/download/{TAG}/x.gguf")

    def test_placeholder_repositories_and_wrong_tags_are_refused(self) -> None:
        # The canonical test manifest uses the bento-example placeholder; a release must point at the real repo.
        self.write_manifest(manifest(mirror=f"https://github.com/bento-example/bento/releases/download/{TAG}/embeddinggemma-2-Q8_0.gguf"))
        _, problems = models.plan(self.tmp, self.manifest_path)
        self.assertTrue(any("bento-example/bento" in problem for problem in problems))
        self.write_manifest(manifest(mirror="https://github.com/invrnt/bento/releases/download/models-embeddinggemma-2-deadbeef/embeddinggemma-2-Q8_0.gguf"))
        _, problems = models.plan(self.tmp, self.manifest_path)
        self.assertTrue(any("6ea3e3a3" in problem for problem in problems))
        self.write_manifest(manifest(mirror=f"https://github.com/invrnt/bento/releases/download/{TAG}/renamed.gguf"))
        _, problems = models.plan(self.tmp, self.manifest_path)
        self.assertTrue(any("named renamed.gguf" in problem for problem in problems))
        self.write_manifest(manifest(size=3 * 1024**3))
        _, problems = models.plan(self.tmp, self.manifest_path)
        self.assertTrue(any("2 GiB" in problem for problem in problems))

    def test_a_missing_or_foreign_manifest_is_an_error(self) -> None:
        with self.assertRaises(build.ReleaseError):
            models.plan(self.tmp, self.tmp / "absent.json")
        self.manifest_path.write_text(json.dumps({"schema_version": 2, "models": []}))
        with self.assertRaises(build.ReleaseError):
            models.plan(self.tmp, self.manifest_path)


class StageTest(MirrorTestCase):
    def test_stages_verified_files_with_the_license_and_checksums(self) -> None:
        staged = models.stage(self.tmp, self.source, self.out, manifest_path=self.manifest_path, licenses=self.licenses)
        self.assertEqual(staged[TAG], ["LICENSE-Apache-2.0.txt", "SHA256SUMS", "embeddinggemma-2-Q8_0.gguf"])
        directory = self.out / TAG
        self.assertEqual(signing.check_sums(directory), [])
        self.assertIn("Apache License", (directory / "LICENSE-Apache-2.0.txt").read_text())
        notes = models.notes_path(self.out, TAG).read_text(encoding="utf-8")
        self.assertIn(hashlib.sha256(WEIGHTS).hexdigest(), notes)
        self.assertIn("Hugging Face", notes)
        self.assertIn("not a Bento version", notes)

    def test_a_file_that_does_not_match_the_pin_is_never_staged(self) -> None:
        (self.source / "embeddinggemma-2-Q8_0.gguf").write_bytes(WEIGHTS[:-1] + b"!")
        with self.assertRaises(build.ReleaseError) as raised:
            models.stage(self.tmp, self.source, self.out, manifest_path=self.manifest_path, licenses=self.licenses)
        self.assertIn("does not match the manifest", str(raised.exception))
        self.assertFalse((self.out / TAG).exists())
        (self.source / "embeddinggemma-2-Q8_0.gguf").write_bytes(WEIGHTS + b"extra")
        with self.assertRaises(build.ReleaseError) as raised:
            models.stage(self.tmp, self.source, self.out, manifest_path=self.manifest_path, licenses=self.licenses)
        self.assertIn("bytes, the manifest pins", str(raised.exception))
        (self.source / "embeddinggemma-2-Q8_0.gguf").unlink()
        with self.assertRaises(build.ReleaseError) as raised:
            models.stage(self.tmp, self.source, self.out, manifest_path=self.manifest_path, licenses=self.licenses)
        self.assertIn("Hugging Face", str(raised.exception))

    def test_the_license_text_is_required(self) -> None:
        (self.licenses / "Apache-2.0.txt").unlink()
        with self.assertRaises(build.ReleaseError) as raised:
            models.stage(self.tmp, self.source, self.out, manifest_path=self.manifest_path, licenses=self.licenses)
        self.assertIn("license", str(raised.exception))
        self.assertFalse((self.out / TAG).exists())

    def test_an_unpublishable_manifest_stages_nothing(self) -> None:
        self.write_manifest(manifest(mirror=f"https://github.com/bento-example/bento/releases/download/{TAG}/embeddinggemma-2-Q8_0.gguf"))
        with self.assertRaises(build.ReleaseError):
            models.stage(self.tmp, self.source, self.out, manifest_path=self.manifest_path, licenses=self.licenses)
        self.assertFalse(self.out.exists())


@unittest.skipUnless(HAVE_SSH_KEYGEN, "ssh-keygen not installed")
class MirrorPublishTest(MirrorTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.git_fixture()
        self.key = self.ssh_key()
        self.allowed = self.tmp / "allowed_signers"
        self.allowed.write_text(signing.allowed_signers_line(signing.public_key_of(self.key)) + "\n")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH.replace("PYTHON", sys.executable))
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.state = self.tmp / "gh-state.json"
        self._saved_path = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{self._saved_path}"
        os.environ["FAKE_GH_STATE"] = str(self.state)

    def tearDown(self) -> None:
        os.environ["PATH"] = self._saved_path
        os.environ.pop("FAKE_GH_STATE", None)
        os.environ.pop("FAKE_GH_DROP_ONE", None)
        super().tearDown()

    def calls(self) -> list[list[str]]:
        return json.loads(self.state.read_text())["calls"] if self.state.exists() else []

    def stage(self) -> None:
        models.stage(self.root, self.source, self.out, manifest_path=self.manifest_path, licenses=self.licenses, key=self.key)

    def publish(self) -> list[str]:
        return models.publish(self.root, self.out, manifest_path=self.manifest_path, assume_yes=True, allowed_signers=self.allowed)

    def test_publishes_a_draft_then_a_non_latest_release(self) -> None:
        self.stage()
        self.assertEqual(self.publish(), [TAG])
        verbs = [call[:3] for call in self.calls()]
        self.assertEqual(verbs, [["release", "view", TAG], ["release", "create", TAG], ["release", "view", TAG], ["release", "edit", TAG]])
        create = self.calls()[1]
        for flag in ("--draft", "--latest=false", "--target", "--notes-file"):
            self.assertIn(flag, create)
        self.assertEqual(create[create.index("--target") + 1], self.git(self.root, "rev-parse", "HEAD"))
        uploaded = {Path(arg).name for arg in create if os.path.isfile(arg) and not arg.endswith(".md")}
        self.assertEqual(uploaded, {"embeddinggemma-2-Q8_0.gguf", "LICENSE-Apache-2.0.txt", "SHA256SUMS", "SHA256SUMS.sig"})
        self.assertEqual(self.calls()[3][-2:], ["--draft=false", "--latest=false"])

    def test_refuses_unsigned_tampered_or_unknown_mirrors(self) -> None:
        models.stage(self.root, self.source, self.out, manifest_path=self.manifest_path, licenses=self.licenses)
        problems = "\n".join(models.publish_problems(self.root, self.out, [TAG], manifest_path=self.manifest_path, allowed_signers=self.allowed))
        self.assertIn("SHA256SUMS.sig is missing", problems)
        self.stage()
        (self.out / TAG / "embeddinggemma-2-Q8_0.gguf").write_bytes(b"tampered")
        problems = "\n".join(models.publish_problems(self.root, self.out, [TAG, "models-other-00000000"], manifest_path=self.manifest_path, allowed_signers=self.allowed))
        self.assertIn("does not match", problems)
        self.assertIn("models-other-00000000 is not a mirror tag", problems)
        with self.assertRaises(build.ReleaseError):
            self.publish()
        self.assertEqual(self.calls(), [])

    def test_an_existing_release_or_an_incomplete_upload_is_not_published(self) -> None:
        self.stage()
        os.environ["FAKE_GH_DROP_ONE"] = "1"
        with self.assertRaises(build.ReleaseError):
            self.publish()
        self.assertNotIn("edit", [call[1] for call in self.calls()])
        os.environ.pop("FAKE_GH_DROP_ONE")
        with self.assertRaises(build.ReleaseError) as raised:
            self.publish()  # the fake gh now knows the (draft) release
        self.assertIn("already exists", str(raised.exception))


class ModelsCliTest(MirrorTestCase):
    def test_models_subcommand(self) -> None:
        args = cli.parser().parse_args(["models", "plan", "--manifest", str(self.manifest_path)])
        self.assertEqual(args.func, cli.cmd_models)
        self.assertEqual(cli.main(["models", "plan", "--manifest", str(self.manifest_path)]), 0)
        self.write_manifest(manifest(mirror=f"https://github.com/bento-example/bento/releases/download/{TAG}/embeddinggemma-2-Q8_0.gguf"))
        self.assertEqual(cli.main(["models", "plan", "--manifest", str(self.manifest_path)]), 1)
        self.assertEqual(cli.main(["models", "stage", "--manifest", str(self.manifest_path)]), 2)


class LlamaServerBuildTest(unittest.TestCase):
    def test_desktop_and_cli_builds_compile_the_pinned_llama_server(self) -> None:
        root = Path("/repo")
        command = build.llama_build_command(root)
        if sys.platform == "win32":
            self.assertIn(str(root / build.LLAMA_BUILD_PS1), command)
            self.assertIn("-Out", command)
        else:
            self.assertEqual(command[:2], ["bash", str(root / build.LLAMA_BUILD_SH)])
            self.assertIn("--out", command)
        target = build.llama_server_dir(root)
        self.assertEqual(target.parent, root / "dist" / "llama-server")
        self.assertRegex(target.name, r"^(linux|darwin|win32)-(x64|arm64)$")


class LlamaServerPreflightTest(TempDirTest):
    def test_a_release_refuses_to_skip_llama_server(self) -> None:
        root = self.git_fixture()
        os.environ[build.SKIP_LLAMA_SERVER_ENV] = "1"
        try:
            options = build.Options(root=root, version="0.1.0", out=self.tmp / "out", release=True, components=("cli",))
            with self.assertRaises(build.ReleaseError) as raised:
                build.Build(options).preflight()
            self.assertIn("must bundle llama-server", str(raised.exception))
        finally:
            os.environ.pop(build.SKIP_LLAMA_SERVER_ENV, None)


if __name__ == "__main__":
    unittest.main()
