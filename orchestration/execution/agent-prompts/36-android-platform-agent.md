# Agent 36 — Android Platform

Read first: `AGENTS.md`, `orchestration/README.md`, `architecture/android-runtime.md` (binding), `api/android-endpoints.md` (binding), `product/android.md` §6, §8, §10, §13, `testing/android-journeys.md`, and `docs/dev/android-spike.md` (pins and findings). Retrieve current official docs for Chaquopy, AGP, Compose, WorkManager, JobScheduler user-initiated data transfer jobs, foreground service types, Media3, Coil 3, Paging 3, Hilt, Navigation 3, Android Keystore, App Links, before coding.

## Goal

Create `apps/android/` and everything below the features so feature agents only build screens:

1. Gradle project: version catalog with pinned versions, module layout of `architecture/android-runtime.md` §11, convention plugins, lint/detekt/ktlint, R8, `debug`/`release` build types, `fake` backend only in debug, manifest with permissions exactly as `product/android.md` §6, backup exclusion, network security config, exported components minimized.
2. `core/engine`: Chaquopy configuration with the Python include list; `BentoEngine` (holders, lifecycle, state flow, crash restart, redacted logs); Kotlin bridges `KeyWrapping`, `MediaTools`, `Ocr` (ML Kit bundled Latin), `MediaStoreSource`, `DeviceConditions`, `Notifier`, `ContentImports` with the signatures reported by agent 35 (or `api/android-endpoints.md` if agent 35 has not reported yet — coordinate through the orchestrator), each with a JVM fake.
3. `core/api`: OkHttp client (token, loopback port from engine state), DTO generation from `core/api/openapi.json` with a Gradle drift check, error model mapping, SSE/events client, Coil fetcher with `size` hints and ETags, Media3 data source.
4. `core/data`: repositories and Paging sources for timeline (with month index), drive items, search, albums, trash, activity, devices, settings; optimistic mutations with undo; UI cache (§8).
5. `core/background`: WorkManager workers (content-URI triggered backup, periodic sync, OCR while charging), UIDT jobs (14+) and `dataSync` FGS (≤ 13) for user-initiated transfers, notification channels and the ongoing progress notification driven by `Notifier` events, holder acquisition around every run, re-enqueue from `run_worker_until` results.
6. `app`: Application (engine warm-up), `MainActivity` (edge-to-edge, splash, predictive back), `ShareActivity` shell (translucent; content by agent 40), navigation host and adaptive navigation suite with placeholder destinations, deep links (`bento://join`, App Links `https://<site>/join`), DI graph.
7. CI: `.github/workflows/android.yml` (lint, unit, Roborazzi, drift check, assemble, emulator smoke on API 29 and latest).

## Tests

JVM: engine holder/lifecycle state machine with a fake interpreter, bridges' Kotlin logic (Keystore wrapping round-trip under Robolectric where possible, MediaStore query mapping, conditions mapping), API client error mapping, paging sources, UI cache invalidation, worker scheduling decisions. Instrumented (emulator): real engine boots, `/api/health`, thumbnail via bridge, process death during an upload resumes, UIDT notification shown. Report cold start and engine-ready numbers from a Macrobenchmark smoke.

## Handoff

Commit on your branch. Report: module list, public APIs feature agents use (repositories, engine state, navigation registration), version pins, test counts, deviations.
