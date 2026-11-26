"""`bento-release build`: everything this machine can build for one version, into dist/release/<version>/.

Layout of the output directory:

    v<version>/           assets of the GitHub release vX.Y.Z (desktop, CLI, backend, SBOMs, installers)
    android-v<version>/   assets of the GitHub release android-vX.Y.Z (APKs, update manifests, Gradle SBOM)
    notes/<tag>.md        release notes from CHANGELOG.md
    private/              never published (R8 mappings)
    logs/                 one log per step
    report.json, REPORT.md

A dry run (the default) never needs a tag, a clean tree or production credentials, and its output can
never be published. `--release` is strict: signed tags at HEAD, clean tree, local-CI evidence, every key.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import changelog, inventory, signing, versioning
from .runner import Runner, StepError, find_node_dir, say, tool_version

COMPONENTS = ("sbom", "backend", "cli", "desktop", "android", "android-sbom")
LINUX_ONLY = {"android", "android-sbom"}
CYCLONEDX_NPM = "@cyclonedx/cyclonedx-npm@6.0.1"
CYCLONEDX_GRADLE_INIT = "scripts/release/sbom/cyclonedx.init.gradle.kts"
MIN_FREE_GB = {"desktop": 6, "android": 6, "android-sbom": 1, "cli": 2, "backend": 1, "sbom": 1}
EVIDENCE = "orchestration/execution/evidence/local-ci.md"
# Smart search runtime (D4): built from the pinned llama.cpp source and bundled by the desktop and CLI builds.
LLAMA_BUILD_SH = "scripts/build-llama-server.sh"
LLAMA_BUILD_PS1 = "scripts/build-llama-server.ps1"
SKIP_LLAMA_SERVER_ENV = "BENTO_SKIP_LLAMA_SERVER"
ALLOWED_SIGNERS = "scripts/release/allowed_signers"


class ReleaseError(Exception):
    pass


@dataclass
class Options:
    root: Path
    version: str
    out: Path
    release: bool = False
    components: tuple[str, ...] = ()
    signing_key: Path | None = None
    keep_work: bool = False
    skip_ci_evidence: bool = False
    # A strict build on a Windows/macOS/arm64 machine whose folder is imported on the Linux release machine:
    # SHA256SUMS and the update manifests are signed there, and local CI ran there.
    for_import: bool = False


@dataclass
class Report:
    version: str
    mode: str
    commit: str
    dirty: bool
    host: str
    created: str
    components: dict[str, dict[str, str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    imported: list[dict[str, object]] = field(default_factory=list)
    tools: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Report":
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("channels", None)
        return cls(**data)


# ---------------------------------------------------------------------------------------------- helpers


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def host_id() -> str:
    system = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)
    return f"{system}-{arch}"


def default_components() -> tuple[str, ...]:
    if sys.platform.startswith("linux") and host_id() == "linux-x64":
        return COMPONENTS
    if sys.platform.startswith("linux"):
        return ("cli",)  # Linux arm64: the CLI is the only artifact built there
    return ("desktop", "cli")


def llama_server_dir(root: Path) -> Path:
    """dist/llama-server/<platform>-<arch> (Node names), the build scripts' output folder."""
    platform_name = {"linux": "linux", "macos": "darwin", "windows": "win32"}[host_id().split("-")[0]]
    return root / "dist" / "llama-server" / f"{platform_name}-{host_id().split('-')[1]}"


def llama_build_command(root: Path) -> list[str]:
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / LLAMA_BUILD_PS1), "-Out", str(llama_server_dir(root))]
    return ["bash", str(root / LLAMA_BUILD_SH), "--out", str(llama_server_dir(root))]


def channel_dir(out: Path, channel: str, version: str) -> Path:
    return out / inventory.tag_for(channel, version)


def update_key_text() -> str | None:
    """The Ed25519 update-manifest signing key (PEM) from BENTO_UPDATE_SIGNING_KEY_FILE or _KEY. Never printed."""
    path = os.environ.get("BENTO_UPDATE_SIGNING_KEY_FILE", "").strip()
    if path:
        file = Path(path).expanduser()
        if not file.is_file():
            raise ReleaseError("BENTO_UPDATE_SIGNING_KEY_FILE does not name a readable file")
        return file.read_text(encoding="utf-8")
    text = os.environ.get("BENTO_UPDATE_SIGNING_KEY", "")
    return text if text.strip() else None


def signed_tag_at(root: Path, tag: str, commit: str) -> list[str]:
    problems = []
    if git(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False) == "":
        return [f"tag {tag} does not exist (create it with `bento-release tag`)"]
    if git(root, "cat-file", "-t", f"refs/tags/{tag}") != "tag":
        problems.append(f"tag {tag} is lightweight; it must be an annotated, signed tag")
    else:
        body = git(root, "cat-file", "tag", f"refs/tags/{tag}")
        if "-----BEGIN SSH SIGNATURE-----" not in body and "-----BEGIN PGP SIGNATURE-----" not in body:
            problems.append(f"tag {tag} is not signed (`git tag -s`)")
    if git(root, "rev-parse", f"{tag}^{{commit}}") != commit:
        problems.append(f"tag {tag} does not point at HEAD")
    return problems


def ci_evidence_problems(root: Path, commit: str) -> list[str]:
    """Release builds need a recorded local-CI PASS for HEAD or for an ancestor that differs only in the evidence log."""
    path = root / EVIDENCE
    if not path.is_file():
        return [f"{EVIDENCE} is missing"]
    passed = re.findall(r"^### Local CI PASS — `[0-9a-f]+`.*\n\n- Commit `([0-9a-f]{40})`", path.read_text(encoding="utf-8"), re.MULTILINE)
    for candidate in reversed(passed):
        if candidate == commit:
            return []
        if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", candidate, commit], capture_output=True).returncode == 0:
            changed = set(git(root, "diff", "--name-only", candidate, commit).splitlines())
            if changed <= {EVIDENCE}:
                return []
    return [f"no local-CI PASS recorded in {EVIDENCE} for HEAD (run scripts/local-ci.sh --full --record {EVIDENCE})"]


def remove_targets(directory: Path, version: str, target_ids: set[str]) -> None:
    """Deletes the files of the targets about to be rebuilt; artifacts imported from other machines stay."""
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        owner = inventory.classify(entry.name, version)
        if entry.is_file() and owner is not None and owner.id in target_ids:
            entry.unlink()


def copy_into(files: list[Path], directory: Path) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    names = []
    for source in files:
        if not source.is_file() or source.stat().st_size == 0:
            raise ReleaseError(f"expected artifact is missing or empty: {source}")
        shutil.copy2(source, directory / source.name)
        (directory / source.name).chmod(0o644)
        names.append(source.name)
    return names


# ---------------------------------------------------------------------------------------------- the build


class Build:
    def __init__(self, options: Options) -> None:
        self.o = options
        self.root = options.root
        self.version = options.version
        self.tag = f"v{options.version}"
        self.work = options.out / "work"
        self.product = channel_dir(options.out, inventory.PRODUCT, options.version)
        self.android = channel_dir(options.out, inventory.ANDROID, options.version)
        env = dict(os.environ)
        env.pop("BENTO_UPDATE_SIGNING_KEY", None)  # only the finalize step receives the update key
        env.pop("BENTO_UPDATE_SIGNING_KEY_FILE", None)
        self.node_dir = find_node_dir()
        if self.node_dir:
            env["PATH"] = self.node_dir + os.pathsep + env.get("PATH", "")
        env.setdefault("UV_NO_PROGRESS", "1")
        self.runner = Runner(self.root, options.out / "logs", env)
        self.commit = git(self.root, "rev-parse", "HEAD")
        self.dirty = bool(git(self.root, "status", "--porcelain"))
        self.report = Report(
            version=self.version,
            mode="release" if options.release else "dry-run",
            commit=self.commit,
            dirty=self.dirty,
            host=host_id(),
            created=_dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        )

    # -------------------------------------------------------------------------------------- preflight

    def preflight(self) -> None:
        o = self.o
        problems = versioning.check(self.root)
        if versioning.read_version(self.root) != self.version:
            problems.append(f"--version {self.version} differs from VERSION ({versioning.read_version(self.root)})")
        text = changelog.read(self.root)
        problems += [f"CHANGELOG.md: {problem}" for problem in changelog.validate(text)]
        try:
            _, from_unreleased = changelog.release_notes(text, self.version, allow_unreleased=not o.release)
            if from_unreleased:
                self.report.notes.append("release notes come from [Unreleased]: run `bento-release changelog cut` before a release")
        except changelog.ChangelogError as error:
            problems.append(str(error))
        unsupported = [c for c in o.components if c in LINUX_ONLY and not sys.platform.startswith("linux")]
        if unsupported:
            problems.append(f"{', '.join(unsupported)} can only be built on Linux")
        if {"desktop", "cli"} & set(o.components):
            if os.environ.get(SKIP_LLAMA_SERVER_ENV) == "1":
                if o.release:
                    problems.append(f"{SKIP_LLAMA_SERVER_ENV}=1: a release must bundle llama-server (smart search)")
                else:
                    self.report.notes.append(f"{SKIP_LLAMA_SERVER_ENV}=1: desktop/CLI built without llama-server")
            elif not shutil.which("cmake"):
                problems.append("cmake not found: the desktop and CLI builds compile llama-server (scripts/build-llama-server.sh)")
        needs_node = {"sbom", "cli", "desktop", "android"} & set(o.components)
        if needs_node and not self.node_dir:
            problems.append("Node.js 22-25 not found (desktop refuses 26): install node@24 with mise or set BENTO_RELEASE_NODE_DIR")
        free_gb = shutil.disk_usage(o.out if o.out.exists() else o.out.parent if o.out.parent.exists() else self.root).free / 1e9
        needed = sum(MIN_FREE_GB.get(component, 1) for component in o.components)
        if free_gb < needed:
            problems.append(f"only {free_gb:.1f} GB free; this build needs about {needed} GB")

        if o.release:
            if self.dirty:
                problems.append("the working tree is not clean")
            problems += signed_tag_at(self.root, self.tag, self.commit)
            if "android" in o.components:
                problems += signed_tag_at(self.root, inventory.tag_for(inventory.ANDROID, self.version), self.commit)
            if not o.skip_ci_evidence and not o.for_import:
                problems += ci_evidence_problems(self.root, self.commit)
            if not o.signing_key and not o.for_import:
                problems.append("a release needs the SHA256SUMS signing key (--signing-key or BENTO_RELEASE_SIGNING_KEY)")
            if not signing.allowed_signers_entries(self.root / ALLOWED_SIGNERS):
                problems.append(f"{ALLOWED_SIGNERS} has no release key: add the public key before the first release")
            if {"desktop", "cli"} & set(o.components):
                for name in ("BENTO_TELEGRAM_API_ID", "BENTO_TELEGRAM_API_HASH", "BENTO_RELAY_URL", "BENTO_PUBLIC_SITE_URL"):
                    if not os.environ.get(name):
                        problems.append(f"{name} is not set (production builds embed it)")
            if sys.platform.startswith("linux") and {"desktop", "cli"} & set(o.components):
                missing_tools = [tool for tool in ("dpkg-deb", "fakeroot") if not shutil.which(tool)]
                if missing_tools:
                    problems.append(f"{' and '.join(missing_tools)} needed for the .deb packages (Arch: pacman -S dpkg fakeroot)")
            if {"desktop", "android"} & set(o.components):
                if not os.environ.get("BENTO_UPDATE_PUBLIC_KEY"):
                    problems.append("BENTO_UPDATE_PUBLIC_KEY is not set")
                if update_key_text() is None and not o.for_import:
                    problems.append("set BENTO_UPDATE_SIGNING_KEY_FILE (Ed25519 PEM that signs update manifests)")
        elif self.dirty:
            self.report.notes.append("built from a working tree with uncommitted changes")
        if o.skip_ci_evidence and o.release:
            self.report.notes.append("local-CI evidence check skipped (--skip-ci-evidence)")
        if o.for_import:
            self.report.notes.append("built for import: SHA256SUMS and update manifests are signed on the release machine")
        if problems:
            raise ReleaseError("preflight failed:\n  - " + "\n  - ".join(problems))

    # -------------------------------------------------------------------------------------- components

    def build_config(self) -> None:
        args = ["node", "apps/desktop/scripts/write-build-config.mjs"]
        if self.o.release:
            args.append("--require-telegram")
        self.runner.run("build-config", args)

    def c_sbom(self) -> list[str]:
        v, out = self.version, self.work / "sbom"
        out.mkdir(parents=True, exist_ok=True)
        python = out / f"bento-{v}-python.cdx.json"
        self.runner.run(
            "sbom-python",
            ["uv", "export", "--project", "apps/api", "--frozen", "--no-dev", "--extra", "desktop", "--format", "cyclonedx1.5", "--output-file", str(python)],
        )
        npm = []
        for app, omit in (("web", ["--omit", "dev"]), ("desktop", [])):
            target = out / f"bento-{v}-npm-{app}.cdx.json"
            # --ignore-npm-errors: npm reports optional, platform-specific packages (e.g. wasm32 builds of
            # native tools) that the lock file lists without their own dependencies; the tree is still complete.
            self.runner.run(
                f"sbom-npm-{app}",
                ["npx", "--yes", CYCLONEDX_NPM, "--package-lock-only", "--ignore-npm-errors", "--output-reproducible", "--spec-version", "1.5", "--mc-type", "application", *omit, "--output-file", str(target)],
                cwd=self.root / "apps" / app,
            )
            npm.append(target)
        return copy_into([python, *npm], self.product)

    def c_backend(self) -> list[str]:
        out = self.work / "backend"
        shutil.rmtree(out, ignore_errors=True)
        self.runner.run("backend-build", ["uv", "build", "--project", "apps/api", "--out-dir", str(out), "--sdist", "--wheel"])
        files = sorted(path for path in out.iterdir() if path.suffix in {".whl", ".gz"})
        return copy_into(files, self.product)

    def c_cli(self) -> list[str]:
        v = self.version
        bundle, archives = self.work / "cli", self.work / "cli-release"
        shutil.rmtree(bundle, ignore_errors=True)
        shutil.rmtree(archives, ignore_errors=True)
        with_llama = os.environ.get(SKIP_LLAMA_SERVER_ENV) != "1"
        if with_llama:
            # A no-op when dist/llama-server/<target> already matches the pin; bento-cli.spec bundles it.
            self.runner.run("llama-server-build", llama_build_command(self.root), timeout=10800)
        self.runner.run(
            "cli-build",
            ["uv", "run", "--project", "apps/api", "--frozen", "--extra", "desktop", "python", "apps/api/scripts/build_cli.py",
             "--output", str(bundle), "--build-config", "apps/desktop/resources/build-config.json", "--archive", str(archives), "--version", v],
            env={"BENTO_REQUIRE_LLAMA_SERVER": "1"} if with_llama else None,
        )
        executable = bundle / "bento" / ("bento.exe" if sys.platform == "win32" else "bento")
        if with_llama:
            name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
            bundled = sorted((bundle / "bento").rglob(f"llama-server/{name}"))
            if not bundled:
                raise StepError("cli-llama-server", "the CLI bundle has no llama-server")
            self.runner.run("cli-smoke-llama-server", [str(bundled[0]), "--version"])
        home = self.work / "cli-smoke"
        smoke_env = {"STORAGE_BACKEND": "local", "BENTO_LANG": "en", "BENTO_HOME": str(home), "BENTO_DESKTOP_USER_DATA": str(self.work / "no-desktop")}
        self.runner.run("cli-smoke-version", [str(executable), "--version"], env=smoke_env)
        self.runner.run("cli-smoke-daemon-start", [str(executable), "--json", "daemon", "start"], env=smoke_env)
        try:
            self.runner.run("cli-smoke-daemon-status", [str(executable), "--json", "daemon", "status"], env=smoke_env)
        finally:
            self.runner.run("cli-smoke-daemon-stop", [str(executable), "--json", "daemon", "stop"], env=smoke_env)
        shutil.rmtree(home, ignore_errors=True)
        files = sorted(path for path in archives.iterdir() if path.name.endswith((".tar.gz", ".zip")))
        if sys.platform.startswith("linux"):
            arch = {"linux-x64": "amd64", "linux-arm64": "arm64"}[host_id()]
            if shutil.which("dpkg-deb"):
                self.runner.run("cli-deb", ["sh", "scripts/install/build_deb.sh", str(bundle / "bento"), v, str(archives), arch])
                files.append(archives / f"bento-cli_{v}_{arch}.deb")
            elif self.o.release:
                raise StepError("cli-deb", "dpkg-deb is required for the CLI .deb (Arch: pacman -S dpkg)")
            else:
                self.report.notes.append("CLI .deb skipped: dpkg-deb not installed")
        files += [self.root / "scripts/install/install.sh", self.root / "scripts/install/install.ps1"]
        return copy_into(files, self.product)

    def c_desktop(self) -> list[str]:
        host = host_id()
        platform_name, arch = {"linux-x64": ("linux", "x64"), "macos-x64": ("darwin", "x64"), "macos-arm64": ("darwin", "arm64"), "windows-x64": ("win32", "x64")}.get(host, (None, None))
        if platform_name is None:
            raise StepError("desktop", f"no desktop target for {host}")
        deb_tools = bool(shutil.which("dpkg-deb") and shutil.which("fakeroot"))
        zip_only = platform_name == "linux" and not deb_tools
        if zip_only and self.o.release:
            raise StepError("desktop", "the .deb maker needs dpkg-deb and fakeroot (Arch: pacman -S dpkg fakeroot)")
        npm_ci = ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"]
        self.runner.run("desktop-npm-ci-web", npm_ci, cwd=self.root / "apps/web")
        self.runner.run("desktop-npm-ci", npm_ci, cwd=self.root / "apps/desktop")
        shutil.rmtree(self.root / "dist/desktop", ignore_errors=True)
        make = ["npm", "--prefix", "apps/desktop", "run", "make"]
        if zip_only:
            make += ["--", "--targets", "@electron-forge/maker-zip"]
            self.report.notes.append("desktop .deb skipped: dpkg-deb/fakeroot not installed (zip only, no linux update manifest)")
        self.runner.run("desktop-make", make)
        smoke = ["npm", "--prefix", "apps/desktop", "run", "smoke:packaged"]
        if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and shutil.which("xvfb-run"):
            smoke = ["xvfb-run", "-a", *smoke]
        self.runner.run("desktop-smoke", smoke)
        self.runner.run("desktop-verify", ["node", "apps/desktop/scripts/verify-artifacts.mjs", *(["--package-only"] if zip_only else [])])
        site_id = {"linux": "linux", "darwin": "macos", "win32": "windows"}[platform_name] + f"-{arch}"
        stage = self.work / f"desktop-{site_id}"
        self.runner.run("desktop-stage", ["node", "apps/desktop/scripts/stage-artifacts.mjs", "dist/desktop", str(stage)])
        # GitHub turns spaces in asset names into dots, which would break the update manifest URL and the
        # SHA256SUMS entry of Squirrel's "Bento-X.Y.Z Setup.exe"; the manifest is written after this rename.
        for path in stage.iterdir():
            if " " in path.name:
                path.rename(path.with_name(path.name.replace(" ", "-")))
        if not zip_only:
            published_at = git(self.root, "log", "-1", "--format=%cI", self.commit)
            self.runner.run(
                "desktop-update-manifest",
                ["node", "apps/desktop/scripts/generate-update-manifest.mjs", "--stage", str(stage), "--platform", platform_name, "--arch", arch,
                 "--tag", self.tag, "--published-at", published_at, "--commit", self.commit],
            )
        self.runner.run("desktop-checksums", ["node", "apps/desktop/scripts/checksums.mjs", str(stage), f"SHA256SUMS-{site_id}"])
        names = copy_into(sorted(p for p in stage.iterdir() if p.is_file()), self.product)
        shutil.rmtree(self.root / "dist/desktop", ignore_errors=True)
        return names

    def _android_wheels(self) -> None:
        dist = self.root / "apps/android/python-wheels/dist"
        if dist.exists():
            return
        source = os.environ.get("BENTO_ANDROID_WHEELS")
        if not source:
            main = git(self.root, "worktree", "list", "--porcelain").splitlines()[0].removeprefix("worktree ")
            source = str(Path(main) / "apps/android/python-wheels/dist")
        if not Path(source).is_dir():
            raise StepError("android", "no Android wheels: run apps/android/python-wheels/build_all.sh or set BENTO_ANDROID_WHEELS")
        dist.symlink_to(source, target_is_directory=True)

    def android_env(self) -> dict[str, str]:
        # JDK 17 like scripts/local-ci.sh: BENTO_JAVA17, else the mise temurin-17 install, else JAVA_HOME.
        mise17 = Path.home() / ".local/share/mise/installs/java/temurin-17"
        java = os.environ.get("BENTO_JAVA17") or (str(mise17) if mise17.is_dir() else os.environ.get("JAVA_HOME", ""))
        python = os.environ.get("BENTO_BUILD_PYTHON") or str(Path.home() / ".local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13")
        sdk = os.environ.get("ANDROID_HOME") or str(Path.home() / "Android/Sdk")
        return {"JAVA_HOME": java, "BENTO_BUILD_PYTHON": python, "ANDROID_HOME": sdk, "ANDROID_SDK_ROOT": sdk}

    def c_android(self) -> list[str]:
        self._android_wheels()
        out = self.work / "android"
        args = ["bash", "apps/android/scripts/release.sh", "--version", self.version, "--out", str(out)]
        if not self.o.release:
            args.insert(2, "--dry-run")
            self.report.notes.append("Android APKs are dry-run builds: throwaway keystore and update key, local feed URL")
        env = self.android_env()
        if self.o.release:
            key = update_key_text()
            env["BENTO_UPDATE_SIGNING_KEY"] = key or ""
        self.runner.run("android-release", args, env=env, timeout=10800)
        v = self.version
        files = sorted(out.glob(f"bento-android-{v}-*.apk")) + sorted(out.glob("bento-update-android-*.json*")) + [out / f"SHA256SUMS-android-{v}.txt"]
        names = copy_into(files, self.android)
        private = self.o.out / "private" / "mapping"
        if (out / "mapping").is_dir():
            private.mkdir(parents=True, exist_ok=True)
            for mapping in (out / "mapping").iterdir():
                shutil.copy2(mapping, private / mapping.name)
        return names

    def c_android_sbom(self) -> list[str]:
        v = self.version
        out = self.work / "android-sbom"
        out.mkdir(parents=True, exist_ok=True)
        env = self.android_env()
        self._android_wheels()
        self.runner.run(
            "android-sbom-gradle",
            ["./gradlew", "--no-daemon", "--init-script", str(self.root / CYCLONEDX_GRADLE_INIT), "--console=plain", "--max-workers=3", "-Dorg.gradle.jvmargs=-Xmx2g",
             f"-PbentoBuildPython={env['BENTO_BUILD_PYTHON']}", "-PbentoAbis=arm64-v8a,x86_64", ":app:cyclonedxDirectBom"],
            cwd=self.root / "apps/android",
            env=env,
            timeout=5400,
        )
        gradle = out / f"bento-{v}-android-gradle.cdx.json"
        # :app's releaseRuntimeClasspath is exactly what the APK ships (feature and core modules included);
        # the aggregate would add the benchmark, baseline-profile and smoke test modules.
        bom = json.loads((self.root / "apps/android/app/build/reports/cyclonedx-direct/bom.json").read_text(encoding="utf-8"))
        component = bom.setdefault("metadata", {}).setdefault("component", {})
        component.update(name="bento-android", version=v)  # Gradle reports the module as `app`, version unspecified
        gradle.write_text(json.dumps(bom, indent=2) + "\n", encoding="utf-8")
        python = out / f"bento-{v}-android-python.cdx.json"
        self.runner.run(
            "android-sbom-python",
            ["uv", "export", "--project", "apps/api", "--frozen", "--no-dev", "--extra", "android", "--format", "cyclonedx1.5", "--output-file", str(python)],
        )
        return copy_into([gradle, python], self.android)

    # -------------------------------------------------------------------------------------- run

    def run(self) -> int:
        o = self.o
        o.out.mkdir(parents=True, exist_ok=True)
        previous = o.out / "report.json"
        if previous.is_file():
            old = Report.load(previous)
            if old.commit != self.commit or old.mode != self.report.mode:
                say(f"discarding {o.out}: it was built from {old.commit[:10]} ({old.mode})")
                for name in ("v" + self.version, "android-v" + self.version, "private", "notes", "logs"):
                    shutil.rmtree(o.out / name, ignore_errors=True)
            else:
                self.report.imported = old.imported
                self.report.components = old.components
        self.preflight()
        self.report.tools = {
            "python": sys.version.split()[0],
            "uv": tool_version(["uv", "--version"]).removeprefix("uv "),
            "node": tool_version([str(Path(self.node_dir) / "node"), "--version"]) if self.node_dir else "unavailable",
            "ssh-keygen": "OpenSSH" if shutil.which("ssh-keygen") else "unavailable",
            "cyclonedx-npm": CYCLONEDX_NPM,
            "cyclonedx-gradle": "org.cyclonedx.bom 3.6.1 (init script)",
        }
        if {"cli", "desktop"} & set(o.components):
            self.build_config()
        failed = False
        for component in COMPONENTS:
            if component not in o.components:
                continue
            channel = inventory.ANDROID if component.startswith("android") else inventory.PRODUCT
            owned = {t.id for t in inventory.targets(channel) if self._owns(component, t.id)}
            remove_targets(channel_dir(o.out, channel, self.version), self.version, owned)
            try:
                names = getattr(self, "c_" + component.replace("-", "_"))()
                self.report.components[f"{component}@{host_id()}"] = {"status": "built", "files": ", ".join(sorted(names))}
            except (StepError, ReleaseError) as error:
                failed = True
                log = getattr(error, "log", None)
                self.report.components[f"{component}@{host_id()}"] = {"status": "failed", "detail": f"{error}" + (f" (log {log})" if log else "")}
                if o.release:
                    break
        finalize(o.root, o.out, self.version, self.report, o.signing_key, release=o.release)
        if not o.keep_work:
            shutil.rmtree(self.work, ignore_errors=True)
        return 1 if failed else 0

    @staticmethod
    def _owns(component: str, target_id: str) -> bool:
        host = host_id()
        if component in {"sbom", "backend", "android", "android-sbom"}:
            return target_id == component
        if component == "cli":
            return target_id in {f"cli-{host}", "cli-installers"}
        if component == "desktop":
            return target_id == f"desktop-{host}"
        return False


# ---------------------------------------------------------------------------------------------- finalize


def sign_update_manifests(root: Path, directory: Path, key_text: str, runner_env: dict[str, str]) -> list[str]:
    """Signs desktop update manifests that have no `.sig` yet (Android's are signed by release.sh)."""
    manifests = sorted(p for p in directory.iterdir() if inventory.DESKTOP_UPDATE_MANIFEST.match(p.name) and not (directory / f"{p.name}.sig").exists())
    if not manifests:
        return []
    env = {**runner_env, "BENTO_UPDATE_SIGNING_KEY": key_text}
    result = subprocess.run(
        ["node", str(root / "apps/desktop/scripts/sign-update-manifest.mjs"), *map(str, manifests)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise ReleaseError(f"update manifest signing failed: {(result.stderr.strip().splitlines() or [''])[-1]}")
    return [p.name for p in manifests]


def finalize(root: Path, out: Path, version: str, report: Report, key: Path | None, *, release: bool) -> dict[str, dict[str, object]]:
    """Signs update manifests, writes and signs SHA256SUMS per channel, writes notes and the report."""
    text = changelog.read(root)
    notes_dir = out / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    channels: dict[str, dict[str, object]] = {}
    env = dict(os.environ)
    node_dir = find_node_dir()
    if node_dir:
        env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
    update_key = update_key_text()
    for channel in (inventory.PRODUCT, inventory.ANDROID):
        directory = channel_dir(out, channel, version)
        tag = inventory.tag_for(channel, version)
        if not directory.is_dir() or not any(directory.iterdir()):
            continue
        info: dict[str, object] = {"tag": tag}
        if update_key and channel == inventory.PRODUCT:
            info["update_manifests_signed"] = sign_update_manifests(root, directory, update_key, env)
        signing.write_sums(directory)
        if key is not None:
            signing.sign(directory, key)
            allowed = root / ALLOWED_SIGNERS
            own_line = signing.allowed_signers_line(signing.public_key_of(key))
            listed = own_line.split()[-1] in {entry.split()[-1] for entry in signing.allowed_signers_entries(allowed)}
            if not release and not listed:
                # Dry runs may use a throwaway key; a release must verify against the committed allowed_signers.
                allowed = out / "work" / "allowed_signers.dry-run"
                allowed.parent.mkdir(parents=True, exist_ok=True)
                allowed.write_text(own_line + "\n", encoding="utf-8")
                info["signature_checked_against"] = "the signing key's own public key (it is not in allowed_signers)"
            else:
                info["signature_checked_against"] = ALLOWED_SIGNERS
            signing.verify(directory, allowed)
            info["signed"] = True
        else:
            info["signed"] = False
        names = {p.name for p in directory.iterdir() if p.is_file()}
        info["assets"] = sorted(names)
        info["missing"] = inventory.missing(names, channel, version)
        info["unsigned_update_manifests"] = inventory.unsigned_manifests(names)
        unknown = sorted(n for n in names if n not in signing.EXCLUDED and inventory.classify(n, version) is None)
        info["unknown"] = unknown
        body, _ = changelog.release_notes(text, version, allow_unreleased=not release)
        (notes_dir / f"{tag}.md").write_text(release_notes_document(body, tag, channel), encoding="utf-8")
        channels[tag] = info
    data = {**report.__dict__, "channels": channels}
    (out / "report.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "REPORT.md").write_text(render_report(data), encoding="utf-8")
    say(f"report: {out / 'REPORT.md'}")
    return channels


def release_notes_document(body: str, tag: str, channel: str) -> str:
    title = "Bento" if channel == inventory.PRODUCT else "Bento para Android"
    return (
        f"{body.rstrip()}\n\n"
        "## Verify your download · Verifica tu descarga\n\n"
        f"Every file of {title} `{tag}` is listed in `SHA256SUMS`, signed with the Bento release key "
        "(`SHA256SUMS.sig`, OpenSSH signature, namespace `bento-release`):\n\n"
        "```sh\n"
        "curl -fsSLO https://raw.githubusercontent.com/invrnt/bento/main/scripts/release/allowed_signers\n"
        "ssh-keygen -Y verify -f allowed_signers -I bento-release -n bento-release -s SHA256SUMS.sig < SHA256SUMS\n"
        "sha256sum --check --ignore-missing SHA256SUMS\n"
        "```\n\n"
        "Guía: https://github.com/invrnt/bento/blob/main/docs/user/es/verificar-descargas.md · "
        "Guide: https://github.com/invrnt/bento/blob/main/docs/user/en/verify-downloads.md\n"
    )


def render_report(data: dict[str, object]) -> str:
    lines = [
        f"# Bento {data['version']} — {data['mode']}",
        "",
        f"- Commit `{data['commit']}`{' (uncommitted changes)' if data['dirty'] else ''} · built on {data['host']} · {data['created']}",
        f"- Tools: {', '.join(f'{k} {v}' for k, v in dict(data['tools']).items())}" if data.get("tools") else "- Tools: (finalize only)",
    ]
    if data["mode"] != "release":
        lines.append("- **Dry run: these files must never be published.**")
    lines += ["", "## Components", "", "| Component | Status | Detail |", "|---|---|---|"]
    for name, info in dict(data["components"]).items():
        lines.append(f"| {name} | {info.get('status')} | {info.get('detail') or info.get('files', '')} |")
    for item in data.get("imported") or []:
        lines.append(f"| import {item.get('host')} | imported | {item.get('files')} files from {item.get('from')} |")
    for tag, info in dict(data["channels"]).items():
        lines += ["", f"## {tag}", "", f"- SHA256SUMS signed: {'yes' if info['signed'] else '**no**'}"]
        if info.get("signature_checked_against"):
            lines.append(f"- Signature verified against {info['signature_checked_against']}")
        if info["unsigned_update_manifests"]:
            lines.append(f"- Update manifests without `.sig`: {', '.join(info['unsigned_update_manifests'])}")
        if info["unknown"]:
            lines.append(f"- Files outside the inventory: {', '.join(info['unknown'])}")
        missing = dict(info["missing"])
        if missing:
            lines.append("- Missing for a complete release:")
            for target_id, patterns in missing.items():
                built_on = inventory.target(target_id).built_on
                shown = (re.sub(r"\\(.)", r"\1", p.strip("^$")) for p in patterns)
                lines.append(f"  - `{target_id}` (build on {built_on}): {', '.join(f'`{p}`' for p in shown)}")
        else:
            lines.append("- Complete: every target is present.")
        lines.append(f"- Assets ({len(info['assets'])}): " + ", ".join(f"`{name}`" for name in info["assets"]))
    if data.get("notes"):
        lines += ["", "## Notes", ""] + [f"- {note}" for note in data["notes"]]
    return "\n".join(lines) + "\n"
