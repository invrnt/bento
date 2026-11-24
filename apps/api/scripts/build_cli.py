"""Build the standalone `bento` CLI (PyInstaller onedir) and, optionally, its release archive.

    uv run --project apps/api --extra desktop python apps/api/scripts/build_cli.py --output dist/cli \
        [--build-config apps/desktop/resources/build-config.json] [--archive dist/cli-release]

The onedir lands in `<output>/bento/` (`bento` or `bento.exe` inside). `--build-config` copies the
desktop build configuration (Telegram build credentials, relay URL, public site URL) next to the
executable; only the four public build keys are kept and values are never printed. `--archive` writes
`bento-cli-<version>-<os>-<arch>.tar.gz` (`.zip` on Windows) whose single top-level directory is
`bento/`, plus `<archive>.sha256` in `sha256sum` format.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import PyInstaller.__main__

BUILD_CONFIG_FILE = "build-config.json"
BUILD_CONFIG_KEYS = (
    "BENTO_TELEGRAM_API_ID",
    "BENTO_TELEGRAM_API_HASH",
    "BENTO_RELAY_URL",
    "BENTO_PUBLIC_SITE_URL",
)
API_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-config", type=Path, help="JSON written by apps/desktop/scripts/write-build-config.mjs")
    parser.add_argument("--archive", type=Path, help="directory for the release archive and its .sha256")
    parser.add_argument("--version", help="archive version (default: apps/api/pyproject.toml)")
    arguments = parser.parse_args()

    output = arguments.output.resolve()
    work = output / ".pyinstaller-work"
    PyInstaller.__main__.run(
        [
            str(API_ROOT / "packaging" / "bento-cli.spec"),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(output),
            "--workpath",
            str(work),
        ]
    )
    shutil.rmtree(work, ignore_errors=True)
    bundle = output / "bento"
    if arguments.build_config:
        copy_build_config(arguments.build_config, bundle / BUILD_CONFIG_FILE)
    if arguments.archive:
        version = arguments.version or project_version()
        archive = write_archive(bundle, arguments.archive.resolve(), version)
        print(f"build_cli: wrote {archive.name}")


def copy_build_config(source: Path, target: Path) -> None:
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"build_cli: cannot read build configuration ({type(error).__name__})") from None
    if not isinstance(document, dict):
        raise SystemExit("build_cli: build configuration must be a JSON object")
    config = {key: document[key] for key in BUILD_CONFIG_KEYS if isinstance(document.get(key), str) and document[key]}
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    # World-readable on purpose: system installs are root-owned and the CLI reads it as the user.
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)
    print(f"build_cli: build configuration keys: {', '.join(config) or 'none'}")


def project_version() -> str:
    with (API_ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def platform_id() -> tuple[str, str]:
    system = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(sys.platform)
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if system is None or arch is None:
        raise SystemExit(f"build_cli: unsupported platform {sys.platform}/{machine}")
    return system, arch


def write_archive(bundle: Path, directory: Path, version: str) -> Path:
    system, arch = platform_id()
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"bento-cli-{version}-{system}-{arch}"
    if system == "windows":
        archive = directory / f"{stem}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for path in sorted(bundle.rglob("*")):
                handle.write(path, Path("bento") / path.relative_to(bundle))
    else:
        archive = directory / f"{stem}.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(bundle, arcname="bento", filter=_normalize_member)
    digest = sha256(archive)
    (directory / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive


def _normalize_member(member: tarfile.TarInfo) -> tarfile.TarInfo:
    member.uid = member.gid = 0
    member.uname = member.gname = ""
    return member


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
