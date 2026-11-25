# Fotos, Visor, Colecciones (agent 39)

| Module | What |
|---|---|
| `feature/photos` | Fotos timeline and the shared media pieces: `MediaGrid` (densities, sticky months, fast scroller, range selection), `MediaActions` (undo, exports, disclosures), sheets, `ViewerSessions`. `testFixtures`: `MediaTestHarness`, fake Coil loader, screenshot variants. |
| `feature/viewer` | Visor: pager, shared element, progressive quality (Telephoto), info, video (Media3, PiP, tabletop). |
| `feature/collections` | Colecciones hub, albums, Favoritos, Videos, Documentos, Del teléfono, Telegram import, Papelera. |
| `feature/photos/benchmark` (`:feature:photos-benchmark`) | Instrumented journeys (7 and the Fotos parts of 1, 2, 5) using the shared `:benchmark-common` driver. The Fotos Macrobenchmarks (fling, fast scroller, viewer) moved to `apps/android/benchmark` (`FotosBenchmarks`, docs/dev/android-performance.md). |

## Timeline data

`TimelineRepository.sharedPositional` pages the whole library with placeholders (positions from the month index), so
the grid knows its full height and the fast scroller jumps by index; each month's `first_cursor` makes any position
loadable in at most `offset / 200` requests. `PositionMap` maps grid indices ↔ photo positions exactly, and the grid
keeps the top photo in place when a jump replaces the loaded block.

## Commands

```sh
./gradlew :feature:photos:recordRoborazziDebug :feature:viewer:recordRoborazziDebug :feature:collections:recordRoborazziDebug
./gradlew :feature:photos:testDebugUnitTest :feature:viewer:testDebugUnitTest :feature:collections:testDebugUnitTest
./gradlew :app:assembleDebug :feature:photos-benchmark:assembleDebug   # then, on an emulator with both installed:
adb shell am instrument -w -e class dev.bento.feature.photos.benchmark.PhotosJourneysTest \
  dev.bento.feature.photos.benchmark/androidx.test.runner.AndroidJUnitRunner
adb logcat -d -s BentoJank   # in-app JankStats per screen (Fotos, Visor)
```

Journeys seed what they need through the loopback API (`LibrarySeeder` in `apps/android/benchmark/common`).
