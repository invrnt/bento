"""The optional smart search model mirror (decision D3): a Bento GitHub release that holds a copy of each
managed model file, the downloader's fallback after Hugging Face.

The model manifest (`apps/api/src/bento/infrastructure/models/manifest.json`, reviewed like code) lists
each file's URLs: the Hugging Face URL pinned to a commit first, then
`https://github.com/invrnt/bento/releases/download/<tag>/<file>`. Each model revision gets its own
release (`models-<name>-<revision[:8]>`, never "latest"), so a 310 MB file is uploaded once per pin
instead of on every product release. Both URLs must yield the manifest's SHA-256.

    bento-release models plan                    the mirror releases the manifest expects, and any problem
    bento-release models stage --source DIR      verify local copies against the manifest, add the license
    bento-release models publish                 upload a staged mirror release (explicit, never automatic)

The model files come from the pinned Hugging Face URL (or a previous download); this module never
downloads anything. `publish` is the only code path here that talks to GitHub.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import signing
from .build import ReleaseError, git
from .runner import say

REPOSITORY = "invrnt/bento"
MANIFEST = "apps/api/src/bento/infrastructure/models/manifest.json"
LICENSES = "apps/api/src/bento/infrastructure/models/licenses"
STAGE = "dist/release/models"
MIRROR_URL = re.compile(r"^https://github\.com/(?P<repo>[^/]+/[^/]+)/releases/download/(?P<tag>[^/]+)/(?P<name>[^/]+)$")
MIRROR_TAG = re.compile(r"^models-[a-z0-9][a-z0-9.-]*-(?P<rev>[0-9a-f]{8})$")
# GitHub refuses release assets of 2 GiB or more.
MAX_ASSET_BYTES = 2 * 1024**3 - 1


@dataclass(frozen=True)
class MirrorFile:
    model_id: str
    display_name: str
    revision: str
    license_spdx: str
    source_url: str
    name: str
    size_bytes: int
    sha256: str
    url: str
    tag: str
    repository: str


def mirror_tag(name: str, revision: str) -> str:
    """The canonical mirror tag for a model name (e.g. `embeddinggemma-2`) at a revision."""
    slug = re.sub(r"[^a-z0-9.]+", "-", name.lower()).strip("-")
    return f"models-{slug}-{revision[:8]}"


def mirror_url(tag: str, name: str, repository: str = REPOSITORY) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}/{name}"


def load_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ReleaseError(f"model manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ReleaseError(f"{path} is not valid JSON: {error}") from None
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("models"), list):
        raise ReleaseError(f"{path} is not a schema 1 model manifest")
    return data


def mirror_files(manifest: dict[str, object]) -> tuple[list[MirrorFile], list[str]]:
    """Every manifest file with a GitHub Releases mirror URL, plus the problems with those URLs."""
    files: list[MirrorFile] = []
    problems: list[str] = []
    for model in manifest["models"]:  # type: ignore[union-attr]
        model_id = str(model.get("model_id", "?"))
        revision = str(model.get("revision", ""))
        for entry in model.get("files", []):
            name = str(entry.get("name", ""))
            mirrors = [url for url in entry.get("urls", []) if str(url).startswith("https://github.com/")]
            for url in mirrors:
                match = MIRROR_URL.match(str(url))
                where = f"{model_id}/{name}"
                if not match:
                    problems.append(f"{where}: {url} is not a GitHub release asset URL")
                    continue
                if match["repo"] != REPOSITORY:
                    problems.append(f"{where}: the mirror points at {match['repo']}, not {REPOSITORY}")
                if match["name"] != name:
                    problems.append(f"{where}: the mirror asset is named {match['name']}")
                tag_match = MIRROR_TAG.match(match["tag"])
                if not tag_match or tag_match["rev"] != revision[:8]:
                    problems.append(f"{where}: mirror tag {match['tag']} must be models-<name>-{revision[:8]}")
                if int(entry.get("size_bytes", 0)) > MAX_ASSET_BYTES:
                    problems.append(f"{where}: {entry.get('size_bytes')} bytes exceeds GitHub's 2 GiB asset limit")
                files.append(
                    MirrorFile(
                        model_id=model_id,
                        display_name=str(model.get("display_name", model_id)),
                        revision=revision,
                        license_spdx=str(model.get("license_spdx", "")),
                        source_url=str(model.get("source_url", "")),
                        name=name,
                        size_bytes=int(entry.get("size_bytes", 0)),
                        sha256=str(entry.get("sha256", "")),
                        url=str(url),
                        tag=match["tag"],
                        repository=match["repo"],
                    )
                )
    return files, problems


def license_file(licenses: Path, spdx: str) -> Path:
    """The license text shipped with the package for an SPDX id (`Apache-2.0.txt`, `LICENSE-Apache-2.0`, ...)."""
    if licenses.is_dir() and spdx:
        for candidate in sorted(licenses.iterdir()):
            if candidate.is_file() and spdx.lower() in candidate.name.lower():
                return candidate
    raise ReleaseError(f"no {spdx or 'license'} text in {licenses}: the mirror must carry the model's license")


def plan(root: Path, manifest_path: Path | None = None) -> tuple[dict[str, list[MirrorFile]], list[str]]:
    files, problems = mirror_files(load_manifest(manifest_path or root / MANIFEST))
    grouped: dict[str, list[MirrorFile]] = {}
    for item in files:
        grouped.setdefault(item.tag, []).append(item)
    return grouped, problems


def stage(root: Path, source: Path, out: Path, *, manifest_path: Path | None = None, licenses: Path | None = None, key: Path | None = None) -> dict[str, list[str]]:
    """Copies verified model files into `<out>/<tag>/` with their license, notes and SHA256SUMS."""
    grouped, problems = plan(root, manifest_path)
    if problems:
        raise ReleaseError("the manifest's mirror URLs are not publishable:\n  - " + "\n  - ".join(problems))
    if not grouped:
        raise ReleaseError("the manifest lists no GitHub Releases mirror URL")
    licenses = licenses or root / LICENSES
    staged: dict[str, list[str]] = {}
    for tag, items in grouped.items():
        directory = out / tag
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
        try:
            for item in items:
                local = source / item.name
                if not local.is_file():
                    raise ReleaseError(f"{item.name} is not in {source} (download it from the pinned Hugging Face URL)")
                if local.stat().st_size != item.size_bytes:
                    raise ReleaseError(f"{item.name}: {local.stat().st_size} bytes, the manifest pins {item.size_bytes}")
                digest = signing.sha256(local)
                if digest != item.sha256:
                    raise ReleaseError(f"{item.name}: SHA-256 {digest} does not match the manifest's {item.sha256}")
                shutil.copy2(local, directory / item.name)
                (directory / item.name).chmod(0o644)
            spdx = {item.license_spdx for item in items}
            for identifier in sorted(spdx):
                shutil.copy2(license_file(licenses, identifier), directory / f"LICENSE-{identifier}.txt")
            notes_path(out, tag).parent.mkdir(parents=True, exist_ok=True)
            notes_path(out, tag).write_text(notes(tag, items), encoding="utf-8")
            signing.write_sums(directory)
            if key is not None:
                signing.sign(directory, key)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        staged[tag] = sorted(p.name for p in directory.iterdir() if p.is_file())
        say(f"staged {tag}: {', '.join(item.name for item in items)}")
    return staged


def notes_path(out: Path, tag: str) -> Path:
    """Release notes live outside the asset folder, so SHA256SUMS lists exactly the uploaded files."""
    return out / "notes" / f"{tag}.md"


def notes(tag: str, items: list[MirrorFile]) -> str:
    lines = [
        f"# {tag}",
        "",
        "Mirror of the model files Bento's smart search downloads when the person turns it on. Bento tries the",
        "pinned Hugging Face URL first and this release only as a fallback; both must match the SHA-256 below,",
        "which is pinned in the app's model manifest. This release is not a Bento version.",
        "",
        "Espejo de los archivos del modelo que la búsqueda inteligente de Bento descarga cuando la activas.",
        "Bento usa primero Hugging Face y este release solo como alternativa; ambos deben coincidir con el SHA-256.",
        "",
    ]
    for item in items:
        lines += [
            f"- `{item.name}`: {item.display_name} (`{item.model_id}`), revision `{item.revision}`",
            f"  - {item.size_bytes} bytes, SHA-256 `{item.sha256}`",
            f"  - License {item.license_spdx} (`LICENSE-{item.license_spdx}.txt`); source {item.source_url}",
        ]
    return "\n".join(lines) + "\n"


def _gh(*args: str, capture: bool = False) -> str:
    gh = shutil.which("gh")
    if not gh:
        raise ReleaseError("the GitHub CLI (gh) is required to publish")
    result = subprocess.run([gh, *args], stdout=subprocess.PIPE if capture else None, text=True)
    if result.returncode != 0:
        raise ReleaseError(f"gh {' '.join(args[:3])} failed (exit {result.returncode})")
    return result.stdout or ""


def publish_problems(root: Path, out: Path, tags: list[str], *, manifest_path: Path | None = None, allowed_signers: Path | None = None) -> list[str]:
    grouped, problems = plan(root, manifest_path)
    allowed = allowed_signers or root / "scripts/release/allowed_signers"
    for tag in tags:
        if tag not in grouped:
            problems.append(f"{tag} is not a mirror tag in the manifest")
            continue
        directory = out / tag
        if not directory.is_dir():
            problems.append(f"{tag}: nothing staged in {directory} (run `bento-release models stage`)")
            continue
        problems += [f"{tag}: {problem}" for problem in signing.check_sums(directory)]
        try:
            signing.verify(directory, allowed)
        except signing.SigningError as error:
            problems.append(f"{tag}: {error}")
        present = {p.name for p in directory.iterdir() if p.is_file()}
        for item in grouped[tag]:
            if item.name not in present:
                problems.append(f"{tag}: {item.name} is not staged")
            elif signing.sha256(directory / item.name) != item.sha256:
                problems.append(f"{tag}: {item.name} does not match the manifest's SHA-256")
        if not any(name.startswith("LICENSE-") for name in present):
            problems.append(f"{tag}: the license text is missing")
        if not notes_path(out, tag).is_file():
            problems.append(f"{tag}: release notes are missing")
    return problems


def publish(root: Path, out: Path, tags: list[str] | None = None, *, manifest_path: Path | None = None, assume_yes: bool = False, allowed_signers: Path | None = None) -> list[str]:
    """Creates each mirror release as a draft, checks the uploaded inventory, then publishes it (never latest)."""
    grouped, _ = plan(root, manifest_path)
    chosen = tags or sorted(grouped)
    problems = publish_problems(root, out, chosen, manifest_path=manifest_path, allowed_signers=allowed_signers)
    if problems:
        raise ReleaseError("refusing to publish the model mirror:\n  - " + "\n  - ".join(problems))
    commit = git(root, "rev-parse", "HEAD")
    say("about to publish the model mirror (public; a published release is never modified):")
    for tag in chosen:
        say(f"  gh release create {tag} --latest=false ({', '.join(item.name for item in grouped[tag])})")
    if not assume_yes:
        if not sys.stdin.isatty():
            raise ReleaseError("publishing needs --yes when stdin is not a terminal")
        if input("Type 'mirror' to publish: ").strip() != "mirror":
            raise ReleaseError("not confirmed")
    published = []
    for tag in chosen:
        directory = out / tag
        files = sorted(p for p in directory.iterdir() if p.is_file())
        if subprocess.run([shutil.which("gh") or "gh", "release", "view", tag, "--repo", REPOSITORY], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            raise ReleaseError(f"release {tag} already exists on GitHub; a mirror for a pinned revision is never replaced")
        title = f"Model mirror: {', '.join(sorted({item.display_name for item in grouped[tag]}))} ({tag.rsplit('-', 1)[-1]})"
        _gh(
            "release", "create", tag, "--repo", REPOSITORY, "--target", commit, "--draft", "--latest=false", "--title", title,
            "--notes-file", str(notes_path(out, tag)), *map(str, files),
        )
        listed = json.loads(_gh("release", "view", tag, "--repo", REPOSITORY, "--json", "assets", capture=True))
        remote_assets = {asset["name"]: asset["size"] for asset in listed.get("assets", [])}
        local_assets = {path.name: path.stat().st_size for path in files}
        if remote_assets != local_assets:
            raise ReleaseError(f"{tag}: the uploaded draft does not match the staged files; inspect the draft before retrying")
        _gh("release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--latest=false")
        say(f"published https://github.com/{REPOSITORY}/releases/tag/{tag}")
        published.append(tag)
    return published
