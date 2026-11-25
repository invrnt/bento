from __future__ import annotations

import datetime as dt
import unittest

from helpers import REPO

from bento_release import changelog

SAMPLE = """# Changelog

Preamble mentioning `## [Unreleased]` inline.

## [Unreleased]

### Fixed

- **CLI:** a fix.

## [0.1.0] - 2026-12-01

### Added

- **Desktop:** first release.

[unreleased]: https://github.com/invrnt/bento/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/invrnt/bento/releases/tag/v0.1.0
"""


class ChangelogTest(unittest.TestCase):
    def test_repository_changelog_is_valid(self) -> None:
        text = changelog.read(REPO)
        self.assertEqual(changelog.validate(text), [])
        self.assertEqual(changelog.sections(text)[0].name, "Unreleased")

    def test_notes_for_a_released_version(self) -> None:
        notes, from_unreleased = changelog.release_notes(SAMPLE, "0.1.0")
        self.assertFalse(from_unreleased)
        self.assertEqual(notes, "### Added\n\n- **Desktop:** first release.\n")

    def test_missing_section_falls_back_only_when_allowed(self) -> None:
        with self.assertRaises(changelog.ChangelogError):
            changelog.release_notes(SAMPLE, "0.2.0")
        notes, from_unreleased = changelog.release_notes(SAMPLE, "0.2.0", allow_unreleased=True)
        self.assertTrue(from_unreleased)
        self.assertIn("a fix", notes)

    def test_cut_moves_unreleased_and_updates_links(self) -> None:
        cut = changelog.cut(SAMPLE, "0.1.1", dt.date(2026, 12, 5))
        names = [(s.name, s.date) for s in changelog.sections(cut)]
        self.assertEqual(names, [("Unreleased", None), ("0.1.1", "2026-12-05"), ("0.1.0", "2026-12-01")])
        self.assertEqual(changelog.find(cut, "Unreleased").body, "")
        self.assertIn("- **CLI:** a fix.", changelog.find(cut, "0.1.1").body)
        self.assertIn("[unreleased]: https://github.com/invrnt/bento/compare/v0.1.1...HEAD", cut)
        self.assertIn("[0.1.1]: https://github.com/invrnt/bento/compare/v0.1.0...v0.1.1", cut)
        self.assertIn("[0.1.0]: https://github.com/invrnt/bento/releases/tag/v0.1.0", cut)
        self.assertEqual(cut.count("[unreleased]:"), 1)
        self.assertEqual(changelog.validate(cut), [])

    def test_first_cut_links_the_release_tag(self) -> None:
        first = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- **Desktop:** x.\n\n[unreleased]: https://github.com/invrnt/bento/commits/main\n"
        cut = changelog.cut(first, "0.1.0", dt.date(2026, 12, 1))
        self.assertIn("[0.1.0]: https://github.com/invrnt/bento/releases/tag/v0.1.0", cut)
        self.assertNotIn("commits/main", cut)

    def test_cut_refuses_empty_or_duplicate(self) -> None:
        cut = changelog.cut(SAMPLE, "0.1.1", dt.date(2026, 12, 5))
        with self.assertRaises(changelog.ChangelogError):
            changelog.cut(cut, "0.1.2", dt.date(2026, 12, 6))  # [Unreleased] is empty now
        with self.assertRaises(changelog.ChangelogError):
            changelog.cut(SAMPLE, "0.1.0", dt.date(2026, 12, 6))

    def test_validate_flags_undated_releases_and_unknown_categories(self) -> None:
        bad = SAMPLE.replace("## [0.1.0] - 2026-12-01", "## [0.1.0]").replace("### Fixed", "### Bugfixes")
        problems = changelog.validate(bad)
        self.assertTrue(any("no release date" in p for p in problems))
        self.assertTrue(any("Bugfixes" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
