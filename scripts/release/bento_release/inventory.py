"""Which files a complete release contains, per GitHub release (channel) and per build target.

Two GitHub releases share one product version:

* `vX.Y.Z`: desktop (four targets), CLI (five targets), backend wheel/sdist, SBOMs, installers.
* `android-vX.Y.Z`: the APKs and their update manifests (`--latest=false`, so the desktop updater,
  which reads `releases/latest`, never sees them).

Desktop and Android file names are the ones the site download buttons and the updaters already use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    id: str
    channel: str  # "product" or "android"
    built_on: str  # where it can be built
    patterns: tuple[str, ...]  # one file must match each pattern ({v} = version, escaped)

    def regexes(self, version: str) -> list[re.Pattern[str]]:
        return [re.compile("^" + pattern.replace("{v}", re.escape(version)) + "$") for pattern in self.patterns]


PRODUCT = "product"
ANDROID = "android"

TARGETS: tuple[Target, ...] = (
    Target("desktop-linux-x64", PRODUCT, "Linux x64", (r"bento(?:-desktop)?_{v}_amd64\.deb", r"Bento-linux-x64-{v}\.zip", r"bento-update-linux-x64\.json", r"SHA256SUMS-linux-x64")),
    Target(
        "desktop-windows-x64",
        PRODUCT,
        "Windows x64",
        (r"Bento-{v}-Setup\.exe", r"bento-{v}-full\.nupkg", r"RELEASES", r"bento-update-win32-x64\.json", r"SHA256SUMS-windows-x64"),
    ),
    Target("desktop-macos-x64", PRODUCT, "macOS Intel", (r"Bento-{v}-x64\.dmg", r"Bento-darwin-x64-{v}\.zip", r"bento-update-darwin-x64\.json", r"SHA256SUMS-macos-x64")),
    Target(
        "desktop-macos-arm64",
        PRODUCT,
        "macOS Apple silicon",
        (r"Bento-{v}-arm64\.dmg", r"Bento-darwin-arm64-{v}\.zip", r"bento-update-darwin-arm64\.json", r"SHA256SUMS-macos-arm64"),
    ),
    Target("cli-linux-x64", PRODUCT, "Linux x64", (r"bento-cli-{v}-linux-x64\.tar\.gz", r"bento-cli_{v}_amd64\.deb")),
    Target("cli-linux-arm64", PRODUCT, "Linux arm64", (r"bento-cli-{v}-linux-arm64\.tar\.gz", r"bento-cli_{v}_arm64\.deb")),
    Target("cli-macos-x64", PRODUCT, "macOS Intel", (r"bento-cli-{v}-macos-x64\.tar\.gz",)),
    Target("cli-macos-arm64", PRODUCT, "macOS Apple silicon", (r"bento-cli-{v}-macos-arm64\.tar\.gz",)),
    Target("cli-windows-x64", PRODUCT, "Windows x64", (r"bento-cli-{v}-windows-x64\.zip",)),
    Target("cli-installers", PRODUCT, "any", (r"install\.sh", r"install\.ps1")),
    Target("backend", PRODUCT, "any", (r"bento_api-{v}-py3-none-any\.whl", r"bento_api-{v}\.tar\.gz")),
    Target("sbom", PRODUCT, "any", (r"bento-{v}-python\.cdx\.json", r"bento-{v}-npm-web\.cdx\.json", r"bento-{v}-npm-desktop\.cdx\.json")),
    Target(
        "android",
        ANDROID,
        "Linux x64 (JDK 17, Android SDK)",
        (
            r"bento-android-{v}-arm64-v8a\.apk",
            r"bento-android-{v}-universal\.apk",
            r"bento-update-android-arm64\.json",
            r"bento-update-android-universal\.json",
            r"SHA256SUMS-android-{v}\.txt",
        ),
    ),
    Target(
        "android-sbom",
        ANDROID,
        "Linux x64 (JDK 17, Android SDK)",
        (r"bento-{v}-android-gradle\.cdx\.json", r"bento-{v}-android-python\.cdx\.json"),
    ),
)

# Update manifests are signed with the Ed25519 update key; each needs its detached `.sig` in a release.
UPDATE_MANIFEST = re.compile(r"^bento-update-[a-z0-9]+-[a-z0-9]+\.json$")
DESKTOP_UPDATE_MANIFEST = re.compile(r"^bento-update-(?:darwin|linux|win32)-(?:x64|arm64)\.json$")


def tag_for(channel: str, version: str) -> str:
    return f"v{version}" if channel == PRODUCT else f"android-v{version}"


def targets(channel: str) -> list[Target]:
    return [target for target in TARGETS if target.channel == channel]


def target(target_id: str) -> Target:
    for candidate in TARGETS:
        if candidate.id == target_id:
            return candidate
    raise KeyError(target_id)


def classify(name: str, version: str) -> Target | None:
    """The target a file name belongs to (update-manifest signatures belong to their manifest's target)."""
    base = name.removesuffix(".sig") if UPDATE_MANIFEST.match(name.removesuffix(".sig")) else name
    for candidate in TARGETS:
        if any(regex.match(base) for regex in candidate.regexes(version)):
            return candidate
    return None


def missing(names: set[str], channel: str, version: str) -> dict[str, list[str]]:
    """Per target, the patterns no file satisfies (targets that are complete are omitted)."""
    result: dict[str, list[str]] = {}
    for candidate in targets(channel):
        absent = [regex.pattern for regex in candidate.regexes(version) if not any(regex.match(name) for name in names)]
        if absent:
            result[candidate.id] = absent
    return result


def unsigned_manifests(names: set[str]) -> list[str]:
    return sorted(name for name in names if UPDATE_MANIFEST.match(name) and f"{name}.sig" not in names)
