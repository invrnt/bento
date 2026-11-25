# Agent 37 — Android Design System

Read first: `AGENTS.md`, `design-system/brand.md` (source of truth), `design-system/android.md` (binding), `design-system/motion-interaction.md`, `product/android.md` §1, §12, §13a, `apps/web/src/styles/tokens.css`, `apps/web/src/components/` (behavioral reference for primitives).

## Goal

Build `core/designsystem` and `core/strings` so every feature screen is assembled from Bento primitives:

1. `scripts/generate_tokens.mjs`: tokens.css → `BentoTokens.kt` (light/dark colors converted from OKLCH to sRGB, radii incl. the mobile control exception, spacing, shadows, durations, easing); CI drift check.
2. `scripts/generate_icons.mjs` + `icons.json`: pinned `lucide-static` (same version as `apps/web`) → `BentoIcons.kt` ImageVectors.
3. `BentoTheme`: full Material 3 `ColorScheme`/`Typography`/`Shapes` from tokens per the mapping table, dynamic color off, `media` scheme for viewers, Geist fonts bundled.
4. Every primitive in `design-system/android.md` §8 with semantics, touch targets, reduced-motion behavior, predictive back for sheets, haptics per §7, and `@Preview`s for each state in light/dark/200 %/compact/expanded.
5. `BrandMark`, `BentoLoader` (AnimatedImageVector, also exported for the splash), adaptive launcher icon with monochrome layer, notification icon.
6. `core/strings`: resource structure (`values/` es default, `values-en/`), shared strings (actions, errors, units, plurals, plaintext-disclosure lines, Telegram compliance lines), a JVM test that es and en have identical keys and placeholder signatures, lint against hardcoded strings in Compose.
7. Lint rules: `BentoNoRawColor`, no `MaterialTheme.colorScheme` default usage outside the theme, no hardcoded strings.
8. A debug-only "Kitchen sink" screen showing every primitive.

## Tests

Roborazzi screenshots for every primitive state; Compose UI tests for `CodeField` (grouping, paste of codes and links, Crockford normalization), `SasEmojiRow` semantics, `StatusAvatar` states, `Thumbnail` placeholder/fade, `FloatingActionBar`, `Snackbar` undo timing; contrast test for every text/background token pair (≥ 4.5:1) in both themes; generator tests.

## Handoff

Commit on your branch. Report: primitive API list with parameters, screenshots, test counts, any brand.md ambiguity found.
