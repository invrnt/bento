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

## Stage 20 status (2026-11-24, orchestrator)

**Landed on `feature/android`:** backend (agent 35), design system (agent 37), platform (agent 36), then integration:

- Root build: the platform's files (compileSdk 37 minor 2, targetSdk 36, minSdk 29, Compose BOM 2026.11.01, build-logic conventions, ktlint/detekt). `core/designsystem` and `core/strings` use the `bento.android.library`/`compose` conventions; the catalog gains the lint API (32.5.2), compose animation, and `android-lint`. `check` now runs ktlint, detekt, Android lint, JVM tests, Roborazzi verify, generator drift (`verifyBentoGenerated`), OpenAPI drift and `checkPythonRequirements`. Design-system goldens verified unchanged on the new BOM (no re-record).
- Engine: Kotlin calls `bento.interfaces.android.engine` directly (shim, migrations package and `extractPackages` deleted). `warm_up()` and the redacted log routing (`interfaces/android/redaction.py`) now live in the backend. Migrations ship as APK assets and are copied once per install to `noBackupFilesDir/migrations/<install stamp>` (`MigrationAssets`), passed as `migrations_dir`. Debug options map to `fake_telegram_dir` and the allowed `settings` overrides (`EngineConfigWire`). Bridges match the adapters: `storage_total_bytes`, `media_changed {"bucket_ids": [...]}`.
- `requirements-android.txt` generated from `uv export --extra android` (`python-wheels/generate_requirements.py`; overrides: cffi 1.17.1, greenlet 3.1.1, markupsafe 3.0.4). The OpenAPI snapshot comes from `bento.interfaces.http.export_openapi`; `monthIndex()` uses `GET /photos/timeline/index`.
- UI: `BentoTheme`, `Theme.Bento` window themes, `BentoNavigationSuite` with the Lucide nav icons, launcher/notification icons, and shell/notification strings in `core/strings`. In debug builds the kitchen sink is reachable from a launcher shortcut.

**Verification:** backend 1270 passed; Android JVM 167 (+5 build-logic); instrumented on API 35 emulator `app` 4/4, `smoke` 1/1 + Macrobenchmark smoke. Cold start with the real module: engine ready median 2.76 s (warm-up 2.51 s, `start_api` 0.18 s); TTID median 1.10 s.

**Deviations:**
- The root `.gitignore` rule `data/` hid `apps/android/core/data` from git on the platform branch. It is now `/data/` and the module was restored from the agent worktree.
- The backend has a single `data_dir` = `noBackupFilesDir/bento`. Blobs and thumbs live there too, not in `filesDir/bento` as §10 says. Both are excluded from backup, so this is not a safety issue.
- `hkdf` is no longer installed (spake2 0.9 uses cryptography's HKDF). The wheel is still built.

**Open items:**
- TTID rose from 0.79 s (temporary theme) to 1.10 s with BentoTheme, fonts and the splash AVD. Profile this in Stage 22 with the Baseline Profile.
- Split blobs and thumbs into `filesDir` if §10 stays binding (needs a backend setting).
- The debug shortcut meta-data on `MainActivity` must be merged with agent 41's launcher shortcuts.
- The kitchen-sink BrandLogo specimen wraps "Bento" at 411 dp.
- Python 3.14 and cryptography ≥ 46 on Android remain follow-ups from the spike.

## Stage 22e status (agent 42e, performance) — WIP handoff (2026-11-24)

Branch `t3/android-performance-profiles` (not rebased on the moved `feature/android`; orchestrator merges). Details and numbers: `docs/dev/android-performance.md`.

**Done (committed):** `:baselineprofile` generator + committed `baseline-prof.txt`/`startup-prof.txt` (dex layout on); `:benchmark` Macrobenchmarks for every emulator-measurable §13 budget (None vs Partial(Require)); `:benchmark-common` driver; `benchmark/run.sh` + `summarize.py`; benchmark variants with fake cloud (`ENGINE_BENCHMARK_TOOLS`, core/engine); `InteractionTrace` slices + Fotos `ReportDrawnWhen`. Fixes: UI cache never written (`TimelinePositionalSource` putIfAbsent), thumbnails from disk cache before engine (`BentoImageFetcher`), Geist font preload. Measured (emulator, 2k library): TTID 1080 ms (profile) / 1171 ms (none), TTFD 4.9 s → 1.44 s, engine ready ~3.0–3.3 s; TTID dominated by ~600 ms GPU shader compile (software GPU, cache dropped per cold start).

**Verified:** generator journeys pass on emulator; StartupBenchmarks pass in both modes; `core:api` BentoImageFetcherTest and `core:data` tests pass; benchmarkRelease/nonMinifiedRelease/debug assemble.

**Not verified / pending:** full 10k benchmark run (Fotos, viewer, Archivos, Buscar, share, memory) — FotosBenchmarks/FilesSearchShareBenchmarks/MemoryBenchmark never ran end to end; gate `./gradlew check assembleDebug :app:assembleDebugAndroidTest` not run (ktlint/detekt/lint on new modules unknown); profile regenerated after fixes but benchmarkRelease not yet rebuilt/measured with it; physical-device list in the doc.

**Changes outside owned paths:** `core/engine` (build types, endpoint dir), `core/api` (fetcher), `core/data` (positional fix), `core/designsystem` (InteractionTrace, font preload), `feature/{photos,files,search,share}` (trace hooks, ReportDrawn), `app` (ShareActivity onPause, BentoApplication preload, plugin lines + `baselineProfile {}` block), root `build.gradle.kts`, catalog, settings.

**Next steps:** see "Pending" in `docs/dev/android-performance.md`.
