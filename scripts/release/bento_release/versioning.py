"""The product version: `VERSION` at the repository root is the single source of truth.

Every manifest that carries the version is a *site* below. `check` compares each site with `VERSION`;
`set_version` rewrites all of them (the text is edited in place, so formatting and comments survive).
The relay and the public site deploy by commit and are deliberately not version sites.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
# Android derives versionCode = X*10^6 + Y*10^3 + Z, so each part must stay below 1000.
ANDROID_PART_LIMIT = 1000


class VersionError(Exception):
    """A version is malformed or the manifests disagree."""


@dataclass(frozen=True)
class Site:
    path: str
    label: str
    pattern: re.Pattern[str]
    # JSON files are also parsed after editing to prove the result is still valid JSON.
    json_check: tuple[str, ...] | None = None


def _site(path: str, label: str, pattern: str, json_check: tuple[str, ...] | None = None) -> Site:
    return Site(path, label, re.compile(pattern, re.MULTILINE), json_check)


# Each pattern has exactly one capture group (the version) and must match exactly once.
SITES: tuple[Site, ...] = (
    _site("apps/desktop/package.json", "desktop package.json", r'^  "version": "([^"]*)"', ("version",)),
    _site("apps/desktop/package-lock.json", "desktop lock (root)", r'^  "version": "([^"]*)"', ("version",)),
    _site(
        "apps/desktop/package-lock.json",
        "desktop lock (packages[''])",
        r'^    "": \{\n(?:      .*\n)*?      "version": "([^"]*)"',
        ("packages", "", "version"),
    ),
    _site("apps/web/package.json", "web package.json", r'^  "version": "([^"]*)"', ("version",)),
    _site("apps/web/package-lock.json", "web lock (root)", r'^  "version": "([^"]*)"', ("version",)),
    _site(
        "apps/web/package-lock.json",
        "web lock (packages[''])",
        r'^    "": \{\n(?:      .*\n)*?      "version": "([^"]*)"',
        ("packages", "", "version"),
    ),
    _site("apps/api/pyproject.toml", "API pyproject.toml", r'^version = "([^"]*)"$'),
    _site("apps/api/uv.lock", "API uv.lock", r'^\[\[package\]\]\nname = "bento-api"\nversion = "([^"]*)"$'),
    _site("apps/api/src/bento/__init__.py", "bento.__version__", r'^__version__ = "([^"]*)"$'),
    _site("apps/api/src/bento/infrastructure/settings.py", "API settings app_version", r'^    app_version: str = "([^"]*)"$'),
    _site(
        "apps/api/src/bento/domain/settings_registry.py",
        "settings registry APP_VERSION",
        r'_field\("app_version", \("APP_VERSION",\), "advanced", Type\.STRING, "([^"]*)"',
    ),
)

# Android reads VERSION itself (apps/android/app/build.gradle.kts); this proves it still does.
ANDROID_GRADLE = "apps/android/app/build.gradle.kts"
ANDROID_READS_VERSION = re.compile(r'rootProject\.file\("\.\./\.\./VERSION"\)')


def parse(version: str) -> tuple[int, int, int]:
    match = SEMVER.match(version)
    if not match:
        raise VersionError(f"'{version}' is not a stable SemVer version (MAJOR.MINOR.PATCH, no pre-release)")
    parts = tuple(int(part) for part in match.groups())
    if any(part >= ANDROID_PART_LIMIT for part in parts):
        raise VersionError(f"'{version}': each part must be below {ANDROID_PART_LIMIT} (Android versionCode)")
    return parts  # type: ignore[return-value]


def bumped(version: str, kind: str) -> str:
    if SEMVER.match(kind):
        parse(kind)
        return kind
    major, minor, patch = parse(version)
    candidates = {"major": f"{major + 1}.0.0", "minor": f"{major}.{minor + 1}.0", "patch": f"{major}.{minor}.{patch + 1}"}
    if kind not in candidates:
        raise VersionError(f"bump must be major, minor, patch or an explicit X.Y.Z, got '{kind}'")
    parse(candidates[kind])
    return candidates[kind]


def read_version(root: Path) -> str:
    path = root / "VERSION"
    if not path.is_file():
        raise VersionError("VERSION is missing at the repository root")
    version = path.read_text(encoding="utf-8").strip()
    parse(version)
    return version


def _matches(site: Site, text: str) -> list[re.Match[str]]:
    return list(site.pattern.finditer(text))


def check(root: Path) -> list[str]:
    """Returns one message per disagreement (an empty list means every manifest equals VERSION)."""
    expected = read_version(root)
    problems: list[str] = []
    for site in SITES:
        path = root / site.path
        if not path.is_file():
            problems.append(f"{site.label}: {site.path} is missing")
            continue
        found = _matches(site, path.read_text(encoding="utf-8"))
        if len(found) != 1:
            problems.append(f"{site.label}: expected one version field in {site.path}, found {len(found)}")
        elif found[0].group(1) != expected:
            problems.append(f"{site.label}: {site.path} has {found[0].group(1)}, VERSION has {expected}")
    gradle = root / ANDROID_GRADLE
    if not gradle.is_file() or not ANDROID_READS_VERSION.search(gradle.read_text(encoding="utf-8")):
        problems.append(f"Android versionName: {ANDROID_GRADLE} no longer falls back to the VERSION file")
    return problems


def _json_value(text: str, keys: tuple[str, ...]) -> object:
    value: object = json.loads(text)
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def set_version(root: Path, version: str) -> list[str]:
    """Writes `version` to VERSION and every site. All-or-nothing: nothing is written if any site fails."""
    parse(version)
    problems = check(root)
    if problems:
        raise VersionError("refusing to bump inconsistent manifests (run `version check`): " + "; ".join(problems))

    pending: dict[str, str] = {}
    for site in SITES:
        text = pending.get(site.path) or (root / site.path).read_text(encoding="utf-8")
        match = _matches(site, text)[0]
        start, end = match.span(1)
        text = text[:start] + version + text[end:]
        if site.json_check and _json_value(text, site.json_check) != version:
            raise VersionError(f"{site.label}: edit did not produce valid JSON with the new version")
        pending[site.path] = text
    pending["VERSION"] = f"{version}\n"
    for relative, text in pending.items():
        (root / relative).write_text(text, encoding="utf-8")
    return sorted(pending)
