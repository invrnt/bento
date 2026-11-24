# Agent 41 — Android Phone Backup, Activity, Settings

Read first: `AGENTS.md`, `product/android.md` (binding §5-§9, §10, §11), `product/settings-recovery-security.md`, `api/android-endpoints.md` §2-§3, §6-§7, `architecture/android-runtime.md` §6, `design-system/android.md`, and the public APIs from agents 36 and 37.

## Goal

Build `feature/activity` and `feature/settings`:

- Phone backup setup composable (used by onboarding and settings): bucket list with counts and thumbnails, policy toggles, permission flows for full/partial media access and media location with every denial path, `Respaldar ahora`, status header, free-up-space flow with system delete request and confirmation reporting.
- Account and activity sheet: status line, transfers, attention items with one action each, pause/resume; `StatusAvatar` wiring for all ring states.
- Quick Settings tile and launcher shortcuts; notification content and actions for every `Notifier` event (channels are platform's; text, coalescing, and actions are yours).
- Settings: every section of §9 including app lock (BiometricPrompt with device credential fallback, timeouts, recents hiding), storage on this phone (cache limit, offline items, clear cache), Telegram section, Avanzado (diagnostic export via SAF, relay URL, reset this phone with typed confirmation), Acerca de (privacy summary, Telegram notice, OSS licenses).
- OEM stall detection card and vendor help links.

## Tests

Compose UI tests for permission states (granted, partial, denied, revoked later), policy toggles reflected in backend settings, free-up-space preview/confirm, app lock timing, notification builders per event; Roborazzi screenshots; instrumented journeys 10-12, 16.

## Handoff

Commit on your branch. Report: screens and states, test counts, deviations.
