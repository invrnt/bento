# Agent 40 — Android Files, Search, Share Target

Read first: `AGENTS.md`, `product/android.md` (binding §4.5-§4.7, §4.9, §11), `product/drive.md`, `product/search.md`, `api/search-contract.md`, `api/android-endpoints.md` §4, §6, `design-system/android.md`, and the public APIs from agents 36 and 37.

## Goal

Build `feature/files`, `feature/search`, `feature/share`:

- Files: list/grid, sort sheet remembered per folder, breadcrumbs, `+ Nuevo` sheet (SAF files, photo picker, SAF folder tree import, document scanner when available, new folder), openers (PDF reader with page rail and text search, text viewer, audio mini player, `Abrir con…` through FileProvider with disclosure), item menu, selection with floating action bar, move sheet with search and inline new folder, offline pins, upload progress card, list-detail on expanded widths, keyboard/mouse support including drag and drop.
- Search: full-screen search with recent searches, suggestion chips, grouped results with match reasons and highlights, filter chips and sheets, scoped search, no-result states.
- Share target: `ShareActivity` sheet (translucent, ≤ 200 ms dismiss), destination picker, album option, text/URL notes, Direct Share shortcuts for recent folders, `ACTION_VIEW` import, failure reporting into Activity.

## Tests

Compose UI tests for every state; share intents with single/multiple/mixed MIME and revoked URIs; path traversal and weird display names reach the backend sanitized; Roborazzi screenshots; instrumented journeys 6, 8, 9.

## Handoff

Commit on your branch. Report: screens and states, test counts, deviations.
