# Android Program (Stages 19-22)

Goal: Bento for Android as a full vault device with a flawless, professional experience. Binding docs: `product/android.md`, `architecture/android-runtime.md`, `design-system/android.md`, `api/android-endpoints.md`, `testing/android-journeys.md`. Protocol: `architecture/telegram-first.md` (unchanged).

## Workflow

- Integration branch: `feature/android` (branched from `feature/cli`, which provides the API token and `/assets/lookup` from Stage 18). Each agent works in its own git worktree and touches only its owned paths.
- Setup: `uv sync --project apps/api --extra dev`; Android: JDK 17 (AGP-supported; the default JDK 27 is too new), Android SDK (command-line tools), emulator images API 29 and latest; Node 24 for token/icon generators.
- Merge order per stage: backend → platform → design system → features (alphabetical) → release. The orchestrator resolves one-line registration conflicts (navigation entries, DI modules, `include_router`).
- Every handoff includes Roborazzi screenshots of the agent's screens (light/dark/200 %), test counts, and deviations from the docs.

## Stage 19 — Feasibility gate (sequential)

| Agent | Prompt | Owns |
|---|---|---|
| android-spike | `agent-prompts/34-android-spike-agent.md` | `spikes/android-engine/**` (throwaway, deleted at Stage 20 merge), `docs/dev/android-spike.md` |

Exit: the go/no-go report (`architecture/android-runtime.md` §12) reviewed by the owner. No-go → Plan B review before anything else.

## Stage 20 — Foundations (parallel)

| Agent | Prompt | Owns |
|---|---|---|
| android-backend | `agent-prompts/35-android-backend-agent.md` | `apps/api/src/bento/interfaces/android/**`, `adapters/android/**`, `ports/device.py`, additive changes in `ports/backup.py`, `application/storage_pipeline.py`, `application/backup.py`, job scheduler eligibility (`application/jobs.py`), `adapters/backup/**` (media_store kind), cache pins in `adapters/storage/**`, thumbnails `size` + timeline paging/index in `interfaces/http/routes_photos.py`/assets routes and their application services, `routes_android.py` (+ one `include_router` line), `interfaces/http/export_openapi.py`, `adapters/fake_telegram/remote*.py`, `interfaces/desktop/launcher.py` (`fake-telegram-serve` subcommand only), `infrastructure/services.py` (android wiring only), `infrastructure/settings*` (new settings only), one Alembic migration, `apps/api/pyproject.toml` (`android` extra), `apps/api/uv.lock`, tests under `tests/unit/android`, `tests/api/android`, `tests/integration/android` |
| android-platform | `agent-prompts/36-android-platform-agent.md` | `apps/android/` root build files, `app/`, `core/engine/`, `core/api/` (incl. `openapi.json` snapshot), `core/data/`, `core/background/`, `core/testing/`, `.github/workflows/android.yml` |
| android-design-system | `agent-prompts/37-android-design-system-agent.md` | `apps/android/core/designsystem/`, `apps/android/core/strings/` (skeleton + shared strings), `apps/android/scripts/generate_tokens.mjs`, `apps/android/scripts/generate_icons.mjs`, `apps/android/scripts/icons.json`, launcher/notification icon resources in `app/src/main/res/mipmap*`/`drawable` (icons only) |

Contracts between them: `api/android-endpoints.md` (backend ↔ platform), bridge interfaces in `architecture/android-runtime.md` §5 (platform implements Kotlin bridges, backend implements Python adapters against the same method names, both with fakes), primitives list in `design-system/android.md` §8 (design system ↔ features).

Exit: backend suite green (+ new android tests); APK boots the embedded engine on the emulator, `/api/health` and a thumbnail job pass in an instrumented test; design-system Roborazzi suite green; a "kitchen sink" debug screen shows every primitive in both themes.

## Stage 21 — Features (parallel)

Each feature agent owns its `feature/<name>/` modules plus its strings in `core/strings` under a file named after the feature (`strings_<feature>.xml`, es + en), and registers navigation entries in one line each in `app/` (orchestrator resolves conflicts).

| Agent | Prompt | Owns |
|---|---|---|
| android-onboarding-trust | `agent-prompts/38-android-onboarding-trust-agent.md` | `feature/onboarding`, `feature/pairing`, `feature/recovery`, `feature/devices` |
| android-photos | `agent-prompts/39-android-photos-agent.md` | `feature/photos`, `feature/viewer`, `feature/collections` |
| android-files-search-share | `agent-prompts/40-android-files-search-share-agent.md` | `feature/files`, `feature/search`, `feature/share` |
| android-backup-activity-settings | `agent-prompts/41-android-backup-settings-agent.md` | `feature/activity`, `feature/settings` (incl. phone backup and storage screens), QS tile UI and launcher shortcuts definitions in `core/background` (shared with platform; this stage owns them) |

Exit: journeys 1-15 of `testing/android-journeys.md` automated and green on the emulator; screenshot suites green; manual pass of each agent's screens against `product/android.md`.

## Stage 22 — Release hardening and distribution

| Agent | Prompt | Owns |
|---|---|---|
| android-release | `agent-prompts/42-android-release-agent.md` | `apps/android/baselineprofile/`, `apps/android/benchmark/`, release signing/R8 config in `app/build.gradle.kts` (release block only), `.github/workflows/android-release.yml`, `apps/site/**` (assetlinks, join page Android CTA, Android download page), `docs/user/{es,en}/android.md`, `docs/dev/android.md`, Play listing assets under `apps/android/store/`, `README.md` (Android section), `orchestration/README.md` status line |

Exit: every release gate in `testing/android-journeys.md`; a signed release APK built by CI from a tag, attached to the GitHub release with its signed manifest entry; in-app update verified from one version to the next on a device.

## Owner actions (cannot be delegated)

release signing keystore custody (generated once, backed up offline; the same key is reused if Play is added later); production `site_url` domain for App Links; Telegram production `api_id` for the Android build (may reuse Bento's); physical device matrix; final legal/privacy review of the store listing.

## Status

See the bottom of this file (updated by the orchestrator at the end of each stage).
