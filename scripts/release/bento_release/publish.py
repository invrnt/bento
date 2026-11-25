"""Importing artifacts built on other machines, signed tags, and the explicit publish step.

`publish` is the only code path that talks to GitHub. It refuses dry-run output, checks every
checksum and signature again, pushes the signed tags, creates each release as a draft, compares the
uploaded inventory with the local one and only then publishes the draft.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import inventory, signing
from .build import ALLOWED_SIGNERS, Report, ReleaseError, channel_dir, finalize, git, signed_tag_at
from .runner import say

REPOSITORY = "invrnt/bento"


# ---------------------------------------------------------------------------------------------- import


def import_artifacts(root: Path, out: Path, version: str, sources: list[Path], key: Path | None, *, replace: bool = False) -> dict[str, object]:
    """Adds the output of `bento-release build` on another machine (its dist/release/<version>/ folder)."""
    target_report = out / "report.json"
    if not target_report.is_file():
        raise ReleaseError(f"{out} has no report.json: run `bento-release build` here first")
    report = Report.load(target_report)
    for source in sources:
        source_report = source / "report.json"
        if not source_report.is_file():
            raise ReleaseError(f"{source} is not a bento-release output folder (no report.json)")
        other = Report.load(source_report)
        if other.version != version:
            raise ReleaseError(f"{source} is version {other.version}, not {version}")
        if other.commit != report.commit:
            raise ReleaseError(f"{source} was built from {other.commit[:10]}, this release from {report.commit[:10]}")
        if other.mode != report.mode:
            raise ReleaseError(f"{source} is a {other.mode} build; this release is a {report.mode} build")
        failed = [name for name, info in other.components.items() if info.get("status") != "built"]
        if failed:
            raise ReleaseError(f"{source} has failed components: {', '.join(failed)}")
        copied: list[str] = []
        for channel in (inventory.PRODUCT, inventory.ANDROID):
            origin = channel_dir(source, channel, version)
            if not origin.is_dir():
                continue
            problems = signing.check_sums(origin)
            if problems:
                raise ReleaseError(f"{origin}: transfer check failed: {'; '.join(problems)}")
            destination = channel_dir(out, channel, version)
            destination.mkdir(parents=True, exist_ok=True)
            for path in signing.asset_files(origin):
                owner = inventory.classify(path.name, version)
                if owner is None or owner.channel != channel:
                    raise ReleaseError(f"{path.name} is not part of a {inventory.tag_for(channel, version)} release")
                existing = destination / path.name
                if existing.exists() and signing.sha256(existing) != signing.sha256(path) and not replace:
                    raise ReleaseError(f"{path.name} already exists with different content (use --replace to overwrite)")
                shutil.copy2(path, existing)
                existing.chmod(0o644)
                copied.append(path.name)
        report.imported.append({"from": str(source), "host": other.host, "files": len(copied)})
        for name, info in other.components.items():
            report.components[name] = {**info, "status": "imported"}
        say(f"imported {len(copied)} files built on {other.host}")
    return finalize(root, out, version, report, key, release=report.mode == "release")


# ---------------------------------------------------------------------------------------------- tags


def create_tags(root: Path, version: str, channels: list[str]) -> list[str]:
    """Creates the signed, annotated tags at HEAD (local only; `publish` pushes them)."""
    commit = git(root, "rev-parse", "HEAD")
    if git(root, "status", "--porcelain"):
        raise ReleaseError("the working tree is not clean")
    created = []
    for channel in channels:
        tag = inventory.tag_for(channel, version)
        if git(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False):
            problems = signed_tag_at(root, tag, commit)
            if problems:
                raise ReleaseError("; ".join(problems))
            say(f"{tag} already exists, signed, at HEAD")
            continue
        title = f"Bento {version}" if channel == inventory.PRODUCT else f"Bento para Android {version}"
        # `git tag -s` signs with the configured key (gpg.format=ssh with user.signingkey, or GPG).
        result = subprocess.run(["git", "-C", str(root), "tag", "-s", tag, "-m", title, commit])
        if result.returncode != 0:
            raise ReleaseError(f"git tag -s {tag} failed (configure user.signingkey; see docs/dev/releasing.md)")
        created.append(tag)
    return created


# ---------------------------------------------------------------------------------------------- publish


def _gh(*args: str, capture: bool = False) -> str:
    gh = shutil.which("gh")
    if not gh:
        raise ReleaseError("the GitHub CLI (gh) is required to publish")
    result = subprocess.run([gh, *args], stdout=subprocess.PIPE if capture else None, text=True)
    if result.returncode != 0:
        raise ReleaseError(f"gh {' '.join(args[:3])} failed (exit {result.returncode})")
    return result.stdout or ""


def publish_problems(root: Path, out: Path, version: str, channels: list[str], allow_missing: set[str]) -> list[str]:
    report_path = out / "report.json"
    if not report_path.is_file():
        return [f"{out} has no report.json: build first"]
    data = json.loads(report_path.read_text(encoding="utf-8"))
    problems = []
    if data["mode"] != "release":
        problems.append("this is a dry-run build; rebuild with `bento-release build --release`")
    commit = git(root, "rev-parse", "HEAD")
    if data["commit"] != commit:
        problems.append(f"the build is from {data['commit'][:10]}, HEAD is {commit[:10]}")
    if data.get("dirty"):
        problems.append("the build was made from a dirty working tree")
    if git(root, "status", "--porcelain"):
        problems.append("the working tree is not clean")
    failed = [name for name, info in data["components"].items() if info.get("status") == "failed"]
    if failed:
        problems.append(f"failed components: {', '.join(failed)}")
    allowed = root / ALLOWED_SIGNERS
    for channel in channels:
        tag = inventory.tag_for(channel, version)
        directory = channel_dir(out, channel, version)
        if not directory.is_dir():
            problems.append(f"{tag}: no assets in {directory}")
            continue
        problems += [f"{tag}: {problem}" for problem in signing.check_sums(directory)]
        try:
            signing.verify(directory, allowed)
        except signing.SigningError as error:
            problems.append(f"{tag}: {error}")
        names = {p.name for p in directory.iterdir() if p.is_file()}
        for target_id, patterns in inventory.missing(names, channel, version).items():
            if target_id not in allow_missing:
                problems.append(f"{tag}: {target_id} is missing ({', '.join(patterns)}); build it or pass --allow-missing {target_id}")
        unsigned = inventory.unsigned_manifests(names)
        if unsigned:
            problems.append(f"{tag}: update manifests without signature: {', '.join(unsigned)}")
        unknown = sorted(n for n in names if n not in signing.EXCLUDED and inventory.classify(n, version) is None)
        if unknown:
            problems.append(f"{tag}: files outside the inventory: {', '.join(unknown)}")
        problems += signed_tag_at(root, tag, commit)
        if not (out / "notes" / f"{tag}.md").is_file():
            problems.append(f"{tag}: release notes are missing")
    return problems


def publish(root: Path, out: Path, version: str, channels: list[str], *, allow_missing: set[str], assume_yes: bool, remote: str = "origin") -> None:
    problems = publish_problems(root, out, version, channels, allow_missing)
    if problems:
        raise ReleaseError("refusing to publish:\n  - " + "\n  - ".join(problems))
    plan = []
    for channel in channels:
        tag = inventory.tag_for(channel, version)
        directory = channel_dir(out, channel, version)
        plan.append((channel, tag, directory, sorted(p for p in directory.iterdir() if p.is_file())))
    say("about to publish (this is public and cannot be undone cleanly):")
    for channel, tag, _, files in plan:
        say(f"  git push {remote} {tag}; gh release create {tag} ({len(files)} assets, latest={'yes' if channel == inventory.PRODUCT else 'no'})")
    if allow_missing:
        say(f"  missing targets accepted: {', '.join(sorted(allow_missing))}")
    if not assume_yes:
        if not sys.stdin.isatty():
            raise ReleaseError("publishing needs --yes when stdin is not a terminal")
        if input(f"Type the version ({version}) to publish: ").strip() != version:
            raise ReleaseError("not confirmed")
    for channel, tag, directory, files in plan:
        if subprocess.run([shutil.which("gh") or "gh", "release", "view", tag, "--repo", REPOSITORY], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            raise ReleaseError(f"release {tag} already exists on GitHub; inspect it (a published release is never modified)")
        result = subprocess.run(["git", "-C", str(root), "push", remote, f"refs/tags/{tag}"])
        if result.returncode != 0:
            raise ReleaseError(f"git push {remote} {tag} failed")
        title = f"Bento {version}" if channel == inventory.PRODUCT else f"Bento para Android {version}"
        _gh(
            "release", "create", tag, "--repo", REPOSITORY, "--verify-tag", "--draft", "--title", title,
            "--notes-file", str(out / "notes" / f"{tag}.md"), *map(str, files),
        )
        listed = json.loads(_gh("release", "view", tag, "--repo", REPOSITORY, "--json", "assets", capture=True))
        remote_assets = {asset["name"]: asset["size"] for asset in listed.get("assets", [])}
        local_assets = {github_asset_name(path.name): path.stat().st_size for path in files}
        if remote_assets != local_assets:
            raise ReleaseError(f"{tag}: the uploaded draft does not match the local assets; inspect the draft before retrying")
        latest = "--latest" if channel == inventory.PRODUCT else "--latest=false"
        _gh("release", "edit", tag, "--repo", REPOSITORY, "--draft=false", latest)
        say(f"published https://github.com/{REPOSITORY}/releases/tag/{tag}")
    say("next: update apps/site/site.config.json with the exact asset names (docs/dev/releasing.md)")


def github_asset_name(name: str) -> str:
    """GitHub stores an asset whose name has spaces with dots instead; staging already removes spaces."""
    return name.replace(" ", ".")


def default_signing_key(argument: str | None) -> Path | None:
    value = argument or os.environ.get("BENTO_RELEASE_SIGNING_KEY", "")
    return Path(value).expanduser().resolve() if value else None
