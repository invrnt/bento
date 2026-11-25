"""CHANGELOG.md in the Keep a Changelog 1.1.0 format: section lookup, release notes and cutting a release.

A release section is `## [X.Y.Z] - YYYY-MM-DD`; unreleased work lives under `## [Unreleased]`. Link
references at the bottom (`[x.y.z]: https://…`) are kept in sync when a release is cut.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_URL = "https://github.com/invrnt/bento"
HEADING = re.compile(r"^## \[(?P<name>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?[ \t]*$", re.MULTILINE)
LINK_REFERENCE = re.compile(r"^\[(?P<name>[^\]]+)\]: \S+[ \t]*$", re.MULTILINE)
CATEGORIES = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")


class ChangelogError(Exception):
    pass


@dataclass(frozen=True)
class Section:
    name: str
    date: str | None
    body: str


def sections(text: str) -> list[Section]:
    headings = list(HEADING.finditer(text))
    references = LINK_REFERENCE.search(text, headings[-1].end()) if headings else None
    result = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else (references.start() if references else len(text))
        result.append(Section(heading["name"], heading["date"], text[heading.end():end].strip("\n")))
    return result


def find(text: str, name: str) -> Section | None:
    return next((section for section in sections(text) if section.name.lower() == name.lower()), None)


def _has_entries(body: str) -> bool:
    return any(line.lstrip().startswith(("- ", "* ")) for line in body.splitlines())


def validate(text: str) -> list[str]:
    problems: list[str] = []
    found = sections(text)
    if not found or found[0].name != "Unreleased":
        problems.append("the first section must be ## [Unreleased]")
    names = [section.name for section in found]
    if len(set(names)) != len(names):
        problems.append("duplicate section headings")
    for section in found:
        if section.name != "Unreleased" and section.date is None:
            problems.append(f"## [{section.name}] has no release date (`## [{section.name}] - YYYY-MM-DD`)")
        for line in section.body.splitlines():
            if line.startswith("### ") and line[4:].strip() not in CATEGORIES:
                problems.append(f"## [{section.name}]: unknown category '{line[4:].strip()}' (use {', '.join(CATEGORIES)})")
    return problems


def release_notes(text: str, version: str, *, allow_unreleased: bool = False) -> tuple[str, bool]:
    """Returns (markdown body of the version's section, whether it came from [Unreleased])."""
    section = find(text, version)
    from_unreleased = False
    if section is None and allow_unreleased:
        section = find(text, "Unreleased")
        from_unreleased = True
    if section is None:
        raise ChangelogError(f"CHANGELOG.md has no ## [{version}] section (cut it with `bento-release changelog cut`)")
    if not _has_entries(section.body):
        raise ChangelogError(f"CHANGELOG.md section [{section.name}] has no entries")
    return section.body.strip() + "\n", from_unreleased


def cut(text: str, version: str, date: _dt.date) -> str:
    """Moves the [Unreleased] entries into a new `## [version] - date` section and updates link references."""
    if find(text, version) is not None:
        raise ChangelogError(f"CHANGELOG.md already has a [{version}] section")
    unreleased = find(text, "Unreleased")
    if unreleased is None:
        raise ChangelogError("CHANGELOG.md has no [Unreleased] section")
    if not _has_entries(unreleased.body):
        raise ChangelogError("[Unreleased] has no entries to release")
    headings = list(HEADING.finditer(text))
    index = next(i for i, match in enumerate(headings) if match["name"] == "Unreleased")
    heading = headings[index]
    first_reference = LINK_REFERENCE.search(text, headings[-1].end())
    boundary = headings[index + 1].start() if index + 1 < len(headings) else (first_reference.start() if first_reference else len(text))
    previous = headings[index + 1]["name"] if index + 1 < len(headings) else None
    rest = text[boundary:].lstrip("\n")
    released = f"## [{version}] - {date.isoformat()}\n\n{unreleased.body.strip(chr(10))}\n"
    new = text[: heading.end()] + "\n\n" + released + ("\n" + rest if rest else "")

    kept: list[str] = []
    body = new
    tail = LINK_REFERENCE.search(new, list(HEADING.finditer(new))[-1].end())
    if tail:
        body = new[: tail.start()]
        kept = [
            match.group(0)
            for match in LINK_REFERENCE.finditer(new, tail.start())
            if match["name"].lower() not in {"unreleased", version}
        ]
    compare = f"{REPOSITORY_URL}/compare/v{previous}...v{version}" if previous else f"{REPOSITORY_URL}/releases/tag/v{version}"
    links = [f"[unreleased]: {REPOSITORY_URL}/compare/v{version}...HEAD", f"[{version}]: {compare}", *kept]
    return body.rstrip("\n") + "\n\n" + "\n".join(links) + "\n"


def read(root: Path) -> str:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        raise ChangelogError("CHANGELOG.md is missing at the repository root")
    return path.read_text(encoding="utf-8")
