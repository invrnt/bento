# Agent 39 — Android Photos, Viewer, Collections

Read first: `AGENTS.md`, `product/android.md` (binding §3, §4.3, §4.4, §4.6, §4.8, §12, §13), `product/photos.md`, `design-system/android.md`, `api/android-endpoints.md` §5-§6, and the public APIs from agents 36 and 37. Retrieve current docs for Compose lazy grids, shared element transitions, Telephoto, Media3 ExoPlayer/PiP.

## Goal

Build `feature/photos`, `feature/viewer`, `feature/collections` to the bar of the best gallery apps on Android:

- Timeline grid with pinch density steps anchored on the focal item, sticky month/day headers, fast scroller with date bubble and year ticks backed by the month index, overlays (duration, favorite, upload state), long-press + drag range selection with edge auto-scroll, floating action bar, top cards, empty states, cached-first rendering.
- Viewer: shared element open/close, progressive quality, paging, zoom (double-tap, pinch, one-finger), swipe-down dismiss with predictive back, info sheet with EXIF/location/storage line, actions and overflow from §4.4, plaintext disclosure sheet, video with Range streaming, scrubbing, PiP, tabletop posture.
- Collections: albums (create via library picker, detail, rename, cover, delete), favorites, videos, documents view (shared list component from agent 40 if available, otherwise a thin list), "Del teléfono", imported from Telegram (with the import flow: chat picker → media grid → import), trash (restore, delete forever, empty).

## Tests

Compose UI tests for selection gestures (including accessibility custom actions as the non-gesture path), header stickiness, overlay semantics, viewer state machine, undo; Roborazzi screenshots; Macrobenchmark scroll and viewer-open journeys with JankStats (budgets §13); instrumented journey 7 and the photos part of 1, 2, 5.

## Handoff

Commit on your branch. Report: measured jank/frame times, screens and states, test counts, deviations.
