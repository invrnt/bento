# Android performance: Baseline Profiles, Macrobenchmarks, budget report

> **Status: WIP (Stage 22e, agent 42e).** The startup rows are measured. The Fotos, Archivos, Buscar, share and memory
> rows still need the full run on the 10k library: see "Pending" at the end. Every number here comes from the shared
> API 35 emulator (`bento_spike_api35`, 4 vCPU, 2 GB, **software GPU** `swiftshader_indirect`). Treat them as
> indicative only. The budgets in `orchestration/product/android.md` §13 are binding on the physical reference
> devices.

## Modules

| Path | What |
|---|---|
| `apps/android/benchmark/common` (`:benchmark-common`) | Drives the app from the test process: fake-cloud sign-in, a seeded library (`LibrarySeeder`: N photos with EXIF dates and a `Benchmark` folder with 300 `factura-NNNN.txt` files), and the UiAutomator journeys (`Journeys`) shared by the generator and the benchmarks. |
| `apps/android/baselineprofile` | `BaselineProfileGenerator`. `startup` (`includeInStartupProfile = true`): cold start to Fotos. `journeys`: Fotos fling, fast scroller, viewer open plus 3 swipes, Archivos tab, open folder, Buscar typing "factura". |
| `apps/android/benchmark` | `StartupBenchmarks` (cold: TTID, TTFD, engine ready, TTID breakdown; warm), `FotosBenchmarks` (fling, fast scroller, viewer open, viewer swipe, RSS), `FilesSearchShareBenchmarks` (`bento.files.open`, `bento.search.results`, `bento.share.dismiss`), `MemoryBenchmark` (PSS after a Fotos session). Every class runs with `CompilationMode.None()` and with `Partial(BaselineProfileMode.Require)`. |
| `app/src/main/generated/baselineProfiles/` | The generated `baseline-prof.txt` (42k rules) and `startup-prof.txt` (29k rules). The plugin runs with `mergeIntoMain`, `dexLayoutOptimization = true` and `automaticGenerationDuringBuild = false`. The startup classes end up in `classes.dex` (2.8 MB) of `benchmarkRelease`. |

Variants: the `androidx.baselineprofile` plugin adds `nonMinifiedRelease` (used to generate the profile) and `benchmarkRelease` (used to measure: R8, profileable, signed with the debug key). In `core/engine` these build types set `ENGINE_BENCHMARK_TOOLS = true`, which gives them the fake cloud. They publish the loopback endpoint under `/sdcard/Android/data/dev.bento.app/files/`, because a non-debuggable build has no `run-as`. Release builds never set this flag.

The app emits these trace slices (`core/designsystem` `InteractionTrace`): `bento.viewer.open`, `bento.files.open`, `bento.search.results` and `bento.share.dismiss`. Fotos calls `ReportDrawnWhen` once the first tile shows pixels. That is the TTFD for "cold start → cached Fotos grid with thumbnails".

## How to run

```sh
cd apps/android
export JAVA_HOME=$HOME/.local/share/mise/installs/java/temurin-17
G="-PbentoBuildPython=$HOME/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13 -Dorg.gradle.jvmargs=-Xmx2g --max-workers=3"
# python-wheels/dist must exist (git-ignored; build it with python-wheels/build_all.sh or copy it from a checkout that has it)

# Regenerate the profiles (seeding 2,000 photos is enough: the code paths do not depend on library size)
./gradlew $G :app:assembleNonMinifiedRelease :baselineprofile:assembleNonMinifiedRelease
SEED=2000 flock ~/.cache/bento-android-emulator.lock benchmark/run.sh profile   # writes app/src/main/generated/baselineProfiles

# Benchmarks (each session reinstalls cleanly and seeds; 10k photos take ~15 min on the emulator)
./gradlew $G :app:assembleBenchmarkRelease :benchmark:assembleBenchmarkRelease
SEED=10000 flock ~/.cache/bento-android-emulator.lock benchmark/run.sh bench [StartupBenchmarks FotosBenchmarks FilesSearchShareBenchmarks MemoryBenchmark]
python3 benchmark/summarize.py build/benchmark-results/device/*-benchmarkData.json      # median / p90 per metric
```

`run.sh` starts the AVD headless (or uses `DEVICE=<serial>`). It sets the animation scales to 1, because Compose flings end instantly at 0, and restores them on exit. It saves the instrumentation output, the logcat (`BentoBenchmark`, `BentoJank`), the JSON and the Perfetto traces under `build/benchmark-results`. `COMPILATION=none|profile` runs only one compilation mode.

## Budget report (emulator, medians; p90 in brackets)

| §13 budget | No profile | Baseline Profile | Method | Caveat |
|---|---|---|---|---|
| Cold start → first frame ≤ 500 ms p50 | 1171 ms [1259] | 1080 ms [1114] | `StartupTimingMetric` TTID, 10 cold starts, 2k library | ~615 ms of it is GPU shader compilation on the software GPU (see TTID below). Measure on devices. |
| Cold start → cached Fotos grid with thumbnails ≤ 900 ms p50 / 1.5 s p90 | 1689 ms [1856] | 1442 ms [1518] | TTFD (`ReportDrawnWhen` on the first tile with pixels) | It was 4.9–5.3 s before the two fixes below. |
| Engine ready ≤ 2.5 s p50 (floor ≤ 4 s p90) | 3287 ms [3408] | 2991 ms [3099] | `bento.engine.ready` async slice | Python warm-up is ~90 % of it. The emulator CPU is shared with other agents. |
| Warm start | 171 ms [808] | 293 ms [790] | TTID, warm | Noisy: one session, shared host. |
| Fotos scroll ≤ 1 % janky (10k, fling + fast scroller) | pending | pending | `FrameTimingMetric` + `BentoJank` | Software GPU: agent 39 measured ~97 % of frames over the deadline. The generator run on 2k logged `BentoJank` 0 % janky. |
| Viewer open ≤ 100 ms | pending | pending | `bento.viewer.open` | Agent 39 measured 60 ms (debug build). |
| Share sheet → dismissed ≤ 200 ms | pending | pending | `bento.share.dismiss` | — |
| Memory (Fotos) ≤ 350 MB PSS | pending | pending | `MemoryBenchmark` (`dumpsys meminfo` TOTAL PSS) | 10k library on the emulator, not 100k. |
| Archivos open folder / Buscar first results (not in §13) | pending | pending | `bento.files.open`, `bento.search.results` | — |
| Tile thumbnail ≤ 50 ms, original ≤ 1 s on Wi-Fi, idle battery ≤ 1 %/day, APK ≤ 60 MB | not measured | — | — | Physical devices and real Telegram only (see below). |

## TTID investigation (0.79 → 1.10 s)

A Perfetto trace of a cold start with the profile (`benchmark-results/device/StartupBenchmarks_coldStart_*.perfetto-trace`) shows this breakdown:

- Main thread before the first frame: `bindApplication` 145 ms (75 ms of it opening the 66 MB APK's dex/oat), `bento.app.onCreate` 7 ms, `activityStart` 45 ms, `activityResume` 15 ms. Our own code here is small.
- First frame `traversal` ≈ 830 ms. The main thread **sleeps** most of it, waiting on RenderThread (712 ms CPU). RenderThread spends **~550–615 ms in `shader_compile`** (8–12 Skia programs, every one a `cache_miss`, via `glCreateProgram` on the translated GPU). The rest is `eglGetDisplay` (48 ms) and `eglSwapBuffers` (116 ms).
- **Conclusion:** the 0.79 → 1.10 s rise is mostly GPU programs. The Bento theme draws rounded rects, circles (avatar), atlas text and fills, and each draw type is one more program at ~65 ms on this emulator. Macrobenchmark drops the shader cache before every cold start. Real devices compile these programs much faster on a real GPU and cache them after the first launch. This is not something to fix in our code, so **measure TTID on the reference devices**.
- **Fixed (ours):** the first text measure built the Geist variable typefaces on the main thread. `preloadBentoFonts` now resolves them on `Dispatchers.Default` from `Application.onCreate`. First `TextStringSimpleNode::measure`: 63 → 28 ms (profile), 40 → 21 ms (none). TTID medians: 1134 → 1074 ms (profile), 1177 → 1051 ms (none), within run noise.

## Fixes found by the benchmarks

| Fix | Before → after (emulator, median) |
|---|---|
| `core/data` `TimelinePositionalSource`: `TreeMap.putIfAbsent` replaced the head cursor (null counts as absent), so `fotos.json` (the UI cache) was **never written**. Every cold start showed "Cargando…" until the engine answered. | TTFD 4945 → 1442 ms (profile), 5284 → 1689 ms (none), together with the next fix. Test: `TimelinePositionalTest`. |
| `core/api` `BentoImageFetcher`: thumbnails with an etag (immutable) are now served from Coil's disk cache before the fetcher awaits the engine. | Same TTFD as above. Test: `BentoImageFetcherTest`. |
| `core/designsystem` + `app`: Geist typeface preload. | First text measure −35 ms (profile). |

## Must be measured on physical devices before release (owner)

Reference devices: Pixel 7a and Galaxy A35. Floor device: 4 GB RAM, Android 10. On each device:

```sh
cd apps/android
./gradlew $G -PbentoAbis=arm64-v8a :app:assembleBenchmarkRelease :benchmark:assembleBenchmarkRelease
DEVICE=<serial> SEED=10000 benchmark/run.sh bench          # all classes, both compilation modes
python3 benchmark/summarize.py build/benchmark-results/device/*-benchmarkData.json
```

1. Cold start TTID ≤ 500 ms and TTFD ≤ 900 ms / 1.5 s p90: `StartupBenchmarks` (profile mode is the shipped configuration).
2. Engine ready ≤ 2.5 s p50 (≤ 4 s p90 on the floor device): `StartupBenchmarks` `bento.engine.readyFirstMs`.
3. Fotos ≤ 1 % janky frames: `FotosBenchmarks.timelineFling` and `fastScroller` (`frameOverrunMs`, `frameDurationCpuMs`), plus `adb logcat -s BentoJank`.
4. Viewer open ≤ 100 ms: `FotosBenchmarks.viewerOpen` `bento.viewer.openFirstMs`.
5. Share sheet ≤ 200 ms: `FilesSearchShareBenchmarks.shareSheetDismiss`.
6. Memory ≤ 350 MB PSS on a **100k** library, and no OOM on the floor device: `SEED=100000 DEVICE=… benchmark/run.sh bench MemoryBenchmark`. Seeding takes ~2.5 h. During the run, check `adb logcat -b events | grep am_kill`.
7. Tile thumbnail ≤ 50 ms bind → pixels: there is no instrumentation yet. Add a Coil `EventListener` trace or measure it manually with Perfetto.
8. Original ≤ 1 s on Wi-Fi: needs the real Telegram backend, not the fake cloud.
9. Idle battery ≤ 1 %/day with backup on: `adb shell dumpsys batterystats --reset`, then 24 h unplugged and idle, then `adb shell dumpsys batterystats --charged dev.bento.app` (or Battery Historian).
10. APK ≤ 60 MB arm64: `./gradlew -PbentoAbis=arm64-v8a :app:assembleRelease`, then `apkanalyzer apk download-size <apk>`.

## Pending (next steps)

1. Rebuild `benchmarkRelease` with the regenerated profile (commit `3e448fa`): `./gradlew $G :app:assembleBenchmarkRelease :benchmark:assembleBenchmarkRelease`.
2. Run `SEED=10000 flock … benchmark/run.sh bench` for all four classes and fill in the pending rows above. Repeat the startup rows on the 10k library.
3. Run the gate `./gradlew $G check assembleDebug :app:assembleDebugAndroidTest`. ktlint, detekt and lint have **not** been run on the new modules or the touched files yet.
4. Decide with agent 39 whether `feature/photos/benchmark` should reuse `:benchmark-common`. Its `BentoDevice` and `LibrarySeeder` are now duplicated there.
