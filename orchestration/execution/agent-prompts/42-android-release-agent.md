# Agent 42 — Android Release Hardening and Distribution

Read first: `AGENTS.md`, `testing/android-journeys.md` (binding), `product/android.md` §2, §13, `architecture/android-runtime.md` §9-§11, `docs/dev/launch-checklist.md`, and every Stage 21 handoff.

## Goal

1. Baseline Profiles (startup, Fotos scroll, viewer open, Archivos) and Macrobenchmarks for every budget in `product/android.md` §13; fix or file regressions with owners; produce the budget report for the reference and floor devices.
2. Release build: R8 full mode rules (Chaquopy, kotlinx.serialization, Media3), signing config from CI secrets (keystore never committed), version codes from tags, `.github/workflows/android-release.yml` building signed APKs (arm64 + universal) on tags and attaching them plus the signed update-manifest entry to the GitHub release; in-app updater (manifest check, SHA-256 + signer verification, `PackageInstaller`) in `core/background`/`feature/settings` integration if not already built.
3. Security pass of the Android surface (loopback token, Keystore wrapping, FileProvider grants, exported components and intent filters, deep link validation, FLAG_SECURE coverage, backup exclusion, logs redaction, release without fake backend/dev endpoints); fix within owned paths or file precise findings.
4. Accessibility pass: TalkBack and Switch Access on the journeys of `testing/android-journeys.md` §17-18, Accessibility Scanner clean.
5. Site: `/.well-known/assetlinks.json`, join page "Instala Bento" with the APK download and sideload steps when Bento is not installed (code kept in the fragment), Android download page; user docs `docs/user/{es,en}/android.md`; developer docs `docs/dev/android.md` (setup, emulator e2e with the remote fake cloud, release); README Android section.
6. Download page copy and screenshots (from Roborazzi device frames) for the site; Play listing drafts are deferred.

## Handoff

Commit on your branch. Report: budget report, security and a11y findings with status, release workflow run link, owner actions remaining.
