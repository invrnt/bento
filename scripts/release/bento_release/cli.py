"""Command line of the local release tool. Runbook: docs/dev/releasing.md."""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

from . import build, changelog, inventory, publish, signing, versioning
from .runner import say

ROOT = Path(__file__).resolve().parents[3]


def _version(args: argparse.Namespace) -> str:
    return args.version or versioning.read_version(ROOT)


def _out(args: argparse.Namespace, version: str) -> Path:
    return Path(args.out).expanduser().resolve() if args.out else ROOT / "dist" / "release" / version


def cmd_version(args: argparse.Namespace) -> int:
    if args.action == "show":
        print(versioning.read_version(ROOT))
        return 0
    if args.action == "check":
        problems = versioning.check(ROOT)
        for problem in problems:
            print(f"version mismatch: {problem}", file=sys.stderr)
        if not problems:
            print(f"every manifest is at {versioning.read_version(ROOT)}")
        return 1 if problems else 0
    current = versioning.read_version(ROOT)
    target = versioning.bumped(current, args.kind)
    # The changelog is cut in memory first, so an empty [Unreleased] stops the bump before any file changes.
    cut = None if args.no_changelog else changelog.cut(changelog.read(ROOT), target, _dt.date.today())
    written = versioning.set_version(ROOT, target)
    print(f"{current} -> {target}: {', '.join(written)}")
    if cut is not None:
        (ROOT / "CHANGELOG.md").write_text(cut, encoding="utf-8")
        print(f"CHANGELOG.md: [Unreleased] -> [{target}] - {_dt.date.today().isoformat()}")
    return 0


def cmd_changelog(args: argparse.Namespace) -> int:
    text = changelog.read(ROOT)
    if args.action == "check":
        problems = changelog.validate(text)
        for problem in problems:
            print(f"CHANGELOG.md: {problem}", file=sys.stderr)
        return 1 if problems else 0
    version = _version(args)
    if args.action == "notes":
        body, from_unreleased = changelog.release_notes(text, version, allow_unreleased=args.allow_unreleased)
        if from_unreleased:
            say(f"no [{version}] section yet; printing [Unreleased]")
        print(body, end="")
        return 0
    date = _dt.date.fromisoformat(args.date) if args.date else _dt.date.today()
    (ROOT / "CHANGELOG.md").write_text(changelog.cut(text, version, date), encoding="utf-8")
    print(f"CHANGELOG.md: [Unreleased] -> [{version}] - {date.isoformat()}")
    return 0


def _components(args: argparse.Namespace) -> tuple[str, ...]:
    chosen = list(args.only.split(",")) if args.only else list(build.default_components())
    skipped = set(args.skip.split(",")) if args.skip else set()
    unknown = (set(chosen) | skipped) - set(build.COMPONENTS)
    if unknown:
        raise build.ReleaseError(f"unknown component(s): {', '.join(sorted(unknown))} (choose from {', '.join(build.COMPONENTS)})")
    return tuple(c for c in build.COMPONENTS if c in chosen and c not in skipped)


def cmd_build(args: argparse.Namespace) -> int:
    version = _version(args)
    options = build.Options(
        root=ROOT,
        version=version,
        out=_out(args, version),
        release=args.release,
        components=_components(args),
        signing_key=publish.default_signing_key(args.signing_key),
        keep_work=args.keep_work,
        skip_ci_evidence=args.skip_ci_evidence,
        for_import=args.for_import,
    )
    say(f"{'RELEASE' if args.release else 'dry run'} {version}: {', '.join(options.components)} -> {options.out}")
    return build.Build(options).run()


def cmd_import(args: argparse.Namespace) -> int:
    version = _version(args)
    publish.import_artifacts(ROOT, _out(args, version), version, [Path(p).expanduser().resolve() for p in args.sources], publish.default_signing_key(args.signing_key), replace=args.replace)
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    version = _version(args)
    out = _out(args, version)
    report = build.Report.load(out / "report.json")
    key = publish.default_signing_key(args.signing_key)
    if key is None:
        raise build.ReleaseError("pass --signing-key or set BENTO_RELEASE_SIGNING_KEY")
    build.finalize(ROOT, out, version, report, key, release=report.mode == "release")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    directory = Path(args.directory).expanduser().resolve()
    allowed = Path(args.allowed_signers).expanduser().resolve() if args.allowed_signers else ROOT / build.ALLOWED_SIGNERS
    print(signing.verify(directory, allowed))
    problems = signing.check_sums(directory)
    for problem in problems:
        print(f"checksum: {problem}", file=sys.stderr)
    if not problems:
        print(f"every file in {directory} matches SHA256SUMS")
    return 1 if problems else 0


def _channels(value: str) -> list[str]:
    return {"product": [inventory.PRODUCT], "android": [inventory.ANDROID], "all": [inventory.PRODUCT, inventory.ANDROID]}[value]


def cmd_tag(args: argparse.Namespace) -> int:
    created = publish.create_tags(ROOT, _version(args), _channels(args.channel))
    for tag in created:
        print(f"created signed tag {tag} (not pushed)")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    version = _version(args)
    allow = set(filter(None, (args.allow_missing or "").split(",")))
    unknown = allow - {t.id for t in inventory.TARGETS}
    if unknown:
        raise build.ReleaseError(f"unknown target(s) for --allow-missing: {', '.join(sorted(unknown))}")
    publish.publish(ROOT, _out(args, version), version, _channels(args.channel), allow_missing=allow, assume_yes=args.yes, remote=args.remote)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="bento-release", description="Local release tool for Bento (docs/dev/releasing.md). Default: a dry-run build.")
    sub = root.add_subparsers(dest="command")

    def common(p: argparse.ArgumentParser, out: bool = True) -> None:
        p.add_argument("--version", help="defaults to the VERSION file")
        if out:
            p.add_argument("--out", help="defaults to dist/release/<version>")

    p = sub.add_parser("version", help="show, check or bump the product version")
    p.add_argument("action", choices=["show", "check", "bump"])
    p.add_argument("kind", nargs="?", default="patch", help="major, minor, patch or X.Y.Z (bump)")
    p.add_argument("--no-changelog", action="store_true", help="bump without cutting the CHANGELOG section")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("changelog", help="check CHANGELOG.md, print release notes, or cut [Unreleased]")
    p.add_argument("action", choices=["check", "notes", "cut"])
    p.add_argument("--date", help="release date for cut (YYYY-MM-DD, default today)")
    p.add_argument("--allow-unreleased", action="store_true", help="notes: fall back to [Unreleased]")
    common(p, out=False)
    p.set_defaults(func=cmd_changelog)

    p = sub.add_parser("build", help="build everything this machine can (dry run unless --release)")
    common(p)
    p.add_argument("--release", action="store_true", help="strict release build: signed tags at HEAD, clean tree, CI evidence, all keys")
    p.add_argument("--only", help=f"comma-separated components ({', '.join(build.COMPONENTS)})")
    p.add_argument("--skip", help="comma-separated components to leave out")
    p.add_argument("--signing-key", help="SSH key that signs SHA256SUMS (or BENTO_RELEASE_SIGNING_KEY); a .pub uses ssh-agent")
    p.add_argument("--keep-work", action="store_true", help="keep the work/ scratch directory")
    p.add_argument("--skip-ci-evidence", action="store_true", help="release: do not require a recorded local-CI PASS (noted in the report)")
    p.add_argument("--for-import", action="store_true", help="release build on a Windows/macOS/arm64 machine, imported on the Linux release machine")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("import", help="add the dist/release/<version> folder built on another machine")
    common(p)
    p.add_argument("sources", nargs="+")
    p.add_argument("--signing-key")
    p.add_argument("--replace", action="store_true", help="overwrite files that already exist with different content")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("sign", help="rewrite and sign SHA256SUMS (and unsigned update manifests)")
    common(p)
    p.add_argument("--signing-key")
    p.set_defaults(func=cmd_sign)

    p = sub.add_parser("verify", help="verify SHA256SUMS.sig and every checksum in a folder of downloaded assets")
    p.add_argument("directory")
    p.add_argument("--allowed-signers", help=f"defaults to {build.ALLOWED_SIGNERS}")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("tag", help="create the signed tags vX.Y.Z / android-vX.Y.Z at HEAD (local only)")
    common(p, out=False)
    p.add_argument("--channel", choices=["product", "android", "all"], default="all")
    p.set_defaults(func=cmd_tag)

    p = sub.add_parser("publish", help="push the signed tags and create the GitHub releases (explicit, never automatic)")
    common(p)
    p.add_argument("--channel", choices=["product", "android", "all"], default="all")
    p.add_argument("--allow-missing", help="comma-separated target ids knowingly left out of this release")
    p.add_argument("--remote", default="origin")
    p.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    p.set_defaults(func=cmd_publish)
    return root


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--publish"]:  # documented alias: `bento-release --publish` == `bento-release publish`
        argv[0] = "publish"
    if not argv or argv[0].startswith("-") and argv[0] not in {"-h", "--help"}:
        argv.insert(0, "build")
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (build.ReleaseError, versioning.VersionError, changelog.ChangelogError, signing.SigningError) as error:
        print(f"bento-release: {error}", file=sys.stderr)
        return 2
