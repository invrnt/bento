# Android performance: Baseline Profiles, Macrobenchmarks, budget report

> **Status: Stage 22e (agent 42e).** Measured on the 10,000-photo library, with the regenerated profile (2026-11-24).
> Archivos and share would not run on the emulator (see the table and "Pending"). Every number comes from the shared
> API 35 emulator (`bento_spike_api35`, 4 vCPU, 2 GB, **software GPU** `swiftshader_indirect`), so treat them as
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
python3 benchmark/summarize.py build/benchmark-results/*-benchmarkData.json      # median / p90 per metric (one JSON per class)
```

`run.sh` starts the AVD headless (or uses `DEVICE=<serial>`). It sets the animation scales to 1, because Compose flings end instantly at 0, and restores them on exit. It saves the instrumentation output, the logcat (`BentoBenchmark`, `BentoJank`) and, per class, the JSON, the Perfetto traces and the failure screenshots (`device-<Class>/`) under `build/benchmark-results`. Each instrumentation run clears the device output dir, so the script copies it after every class.

Non-startup benchmarks use `startupMode = null` and call `killProcess()` in `setupBlock`. With `StartupMode.COLD`, Macrobenchmark kills the app *between* setup and the measured block, so the measured block would run on the home screen. `COMPILATION=none|profile` runs only one compilation mode.

## Budget report (emulator, 10k library, medians; P90/P99 where sampled)

| §13 budget | No profile | Baseline Profile | Method | Caveat |
|---|---|---|---|---|
| Cold start → first frame ≤ 500 ms p50 | 1234 ms | 1191 ms | `StartupTimingMetric` TTID, 10 cold starts | ~620–680 ms of it is GPU shader compilation on the software GPU (see TTID below). On the 2k library: 1171 / 1080 ms. Measure on devices. |
| Cold start → cached Fotos grid with thumbnails ≤ 900 ms p50 / 1.5 s p90 | 1760 ms | 1577 ms | TTFD (`ReportDrawnWhen` on the first tile with pixels) | It was 4.9–5.3 s before the two fixes below. 2k library: 1689 / 1442 ms. |
| Engine ready ≤ 2.5 s p50 (floor ≤ 4 s p90) | 3275 ms | 3166 ms | `bento.engine.ready` async slice | Python warm-up is ~2.9–3.0 s of it. The emulator CPU is shared with other agents. |
| Warm start | 237 ms | 273 ms | TTID, warm | Noisy: P90 up to 0.8–0.9 s on the shared host. |
| Fotos fling ≤ 1 % janky | overrun P50 23 / P90 35 / P99 47 ms; CPU P50 34 ms (1021 frames) | overrun P50 23 / P90 34 / P99 45 ms; CPU P50 33 ms (1063 frames) | `FrameTimingMetric`, 5 × (8 flings down, 4 up) | Overrun is positive on most frames (software GPU), so the janky share cannot be judged here. Agent 39 saw ~97 % over deadline on the same AVD. |
| Fotos fast scroller | overrun P50 7 / P90 23 / P99 49 ms | overrun P50 15 / P90 23 / P99 45 ms | `FrameTimingMetric`, drag through the library and back | In the "none" run the thumb was usually not found (median 38 frames, versus 946 with the profile), so the drag mostly did not happen: compare with care. |
| Viewer open ≤ 100 ms | 732 ms | 457 ms | `bento.viewer.open` (tap → first frame with the shared thumbnail) | **Over budget.** Each iteration is the first viewer open in a freshly started process (`killProcess()` in setup), so it includes first composition and class loading of the viewer. Agent 39 measured 60 ms with repeated opens in one process (debug build). The warm case needs a separate benchmark, and the cold case needs a device check (see Pending). |
| Viewer swipe | overrun P50 7 / P90 24 / P99 84 ms | overrun P50 17 / P90 24 / P99 78 ms | `FrameTimingMetric`, 5 swipes | — |
| Share sheet → dismissed ≤ 200 ms | did not run | did not run | `bento.share.dismiss` | "Guardar en Bento" never appeared after `startActivity(ACTION_SEND)` from the test APK. Not diagnosed (the screenshot was lost before the run.sh fix). Journey j06 (`app` androidTest) still measures this in-process. |
| Memory (Fotos) ≤ 350 MB PSS | 270 MB median, 293 MB max | 338 MB median, 341 MB max | `MemoryBenchmark`: `dumpsys meminfo` TOTAL PSS after fling + fast scroller + viewer, 3 iterations | 10k library on the emulator, not 100k. The "profile" run is close to the budget. RSS anon 253 / 283 MB. Re-check on devices. |
| Buscar first results (not in §13) | 523 ms | 484 ms | `bento.search.results` (first key → first frame with results) | Includes the engine's search query. |
| Archivos open folder (not in §13) | did not run | did not run | `bento.files.open` | The `Benchmark` folder was not on screen after the Archivos tab. The generator journey passed on 2k, so the cause is unknown (screenshot lost). |
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
python3 benchmark/summarize.py build/benchmark-results/*-benchmarkData.json
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

1. Diagnose `archivosOpenFolder` and `shareSheetDismiss` on the emulator. `run.sh` now keeps the failure screenshot and UI dump per class under `build/benchmark-results/device-FilesSearchShareBenchmarks/`.
2. Add a warm viewer-open benchmark (several opens in one process) next to the fresh-process one. Then decide whether 457 ms for the first open after a cold start is a real regression (Telephoto/Media3 class loading, first composition).
3. Run on the reference and floor devices (list above). The emulator cannot judge jank (software GPU) or TTID (shader compilation).
