## What and why

<!-- What this changes and the problem it solves. Link the issue: "Closes #123". -->

## How it was tested

<!-- Paste the summary printed by scripts/local-ci.sh (GitHub Actions does not run here):
     scripts/local-ci.sh --auto main     or     scripts/local-ci.sh --light
     Add manual checks (platforms, devices, screenshots for UI changes). -->

## Checklist

- [ ] Every commit is signed off (`git commit -s`, Developer Certificate of Origin; see CONTRIBUTING.md).
- [ ] Tests cover the change and the local CI gate passes for the components it touches.
- [ ] `CHANGELOG.md` has a line under `## [Unreleased]` (or this change is not user-visible).
- [ ] User-facing strings go through i18n, in Spanish and English; user and developer docs are updated.
- [ ] Nothing new leaves the device unencrypted, and no secret, code, session or key is logged.
- [ ] No version bump (`VERSION` and manifests change only in release pull requests).
