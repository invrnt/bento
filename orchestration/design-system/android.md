# Bento on Android — Design System Adaptation

`design-system/brand.md` is the source of truth. This document says how it maps to Compose. When they disagree, `brand.md` wins or is updated first.

## 1. Single source of tokens

- Colors, radii, spacing, shadows, and motion durations are **generated** from `apps/web/src/styles/tokens.css` into `core/designsystem/src/main/kotlin/.../generated/BentoTokens.kt` by `apps/android/scripts/generate_tokens.mjs` (Node, no new dependency beyond what `apps/web` uses). OKLCH values are converted to sRGB at generation time; both light and dark values are emitted. A CI check regenerates and fails on diff.
- No hex literal, `Color(0x…)`, or Material baseline color appears in feature code (lint rule `BentoNoRawColor`).
- Material 3 is used for **behavior** (accessibility, sheets, predictive back, ripples, text fields, date pickers); its `ColorScheme`, `Typography`, and `Shapes` are fully filled from Bento tokens so no Material default color leaks. **Dynamic color (Material You) is off**: Bento's washi/índigo palette is the identity.

### Color role mapping

| Material role | Bento token |
|---|---|
| `background` | `tray` |
| `surface` / `surfaceContainerLowest` | `surface` / `raised` |
| `surfaceContainer` / `surfaceContainerHigh` | `subtle` / `raised` |
| `surfaceDim` | `sunken` |
| `primary` / `onPrimary` | `accent` / white |
| `primaryContainer` / `onPrimaryContainer` | `accent-soft` / `accent-ink` |
| `outline` / `outlineVariant` | `line-strong` / `line` |
| `onSurface` / `onSurfaceVariant` | `ink` / `ink-muted` |
| `error` / `errorContainer` / `onErrorContainer` | `danger` / `danger-soft` / `danger-ink` |
| `tertiary` | unused (shu is never a role; it is used only through `BentoFavorite`, `BrandMark`) |

The viewer and video player always use the `media` (dark) scheme regardless of theme.

## 2. Typography

- Geist Variable and Geist Mono Variable bundled as font resources (OFL), weights 400/500/600 only.
- Brand pixel sizes map 1:1 to `sp` with a **mobile step-up** for readability at arm's length: body 15 sp / 22 (brand `text-md`), dense metadata 13 sp / 18, labels 14 sp / 20, section titles 17 sp / 24, month headers 20 sp / 28, page titles 24 sp / 32, hero numbers 32 sp / 38. No text below 12 sp.
- Tabular numerals (`fontFeatureSettings = "tnum"`) for sizes, counters, progress, codes.
- Text follows the system font scale (nonlinear on 14+); layouts are tested at 100 %, 130 %, 200 %.

## 3. Shape and space

- Radii from tokens with the nested rule (outer = inner + gap): buttons/fields `md` 10 dp → on phones fields and buttons use 12 dp so 48 dp controls look proportionate (documented exception, applied through the token generator as `radius.control.mobile`); cards `lg` 14 dp; sheets and dialogs `xl` 18 dp top corners; hero surfaces 24 dp. Photo tiles are square-cornered at every density; a selected tile insets 8 dp and takes a 12 dp radius (the "settling into a compartment" moment).
- Spacing 4 dp base; screen gutters 16 dp (compact), 24 dp (medium+). Controls: 48 dp minimum touch, 40 dp visual for dense icon buttons with expanded touch area.
- *Ma*: the shell keeps `tray` visible between the top bar, the content compartment, and the navigation bar on medium/expanded widths; on compact phones the content fills edge-to-edge and the tray shows only behind system bars and between cards.

## 4. Elevation

Tonal surfaces first (`raised` vs `surface`); shadows only for floating layers (FAB, floating action bar, upload card, sheets) using the ink-tinted shadow colors from tokens via `Modifier.dropShadow` with spot/ambient colors set. No Material tonal elevation tint.

## 5. Icons

- Lucide remains the single icon library: `apps/android/scripts/generate_icons.mjs` converts the pinned `lucide-static` SVGs (same version as `lucide-react` in `apps/web`) into `ImageVector`s in `core/designsystem/.../generated/BentoIcons.kt`, only for the icons listed in `icons.json`. Stroke 1.75 in navigation, 2 elsewhere; sizes 20/24 dp (mobile step-up of brand §8).
- Canonical icons per `brand.md` §8; mobile additions: `Smartphone` (este teléfono), `CloudUpload`, `CloudOff`, `ScanLine` (escanear), `QrCode`, `Share2`, `Lock`.
- Launcher icon: adaptive icon from `apps/desktop/resources/icons/bento-icon.svg` (background `tray`, foreground box + ume) with a **monochrome** layer for themed icons; notification small icon = monochrome box without ume.

## 6. Motion

| Brand | Compose |
|---|---|
| 120 ms color/hover | `tween(120, easing = BentoEaseOut)` |
| 180 ms state | `tween(180, BentoEaseOut)` |
| 260 ms layer entrance | `tween(260, BentoEaseOut)`; sheets and the viewer dismiss use spring physics (`dampingRatio 0.9, stiffness 600`) because they follow the finger |
| `--ease-out` | `CubicBezierEasing(0.16f, 1f, 0.3f, 1f)` |

- Transitions: shared axis (Z) between top-level destinations is **not** used (bottom nav swaps instantly with a 120 ms fade); shared-axis X for drill-in (folders, settings), container transform for search pill → search screen, shared element for tile → viewer.
- Predictive back animations are implemented for every custom transition.
- Never animate virtualized item size; grid density changes animate by crossfading two lazy grids anchored on the focal item.
- Reduced motion → fades only, 120 ms.
- `BentoLoader` as an `AnimatedImageVector`; also the splash icon animation.

## 7. Haptics

`HapticFeedbackConstants`: `LONG_PRESS` on entering selection, `SEGMENT_TICK` on grid density steps and fast-scroller year ticks, `CONFIRM` on successful pairing/QR detection, `REJECT` on invalid code. No haptics on scroll or routine taps. Respect the system haptics setting.

## 8. Primitives (`core/designsystem`)

Domain-free, mirroring `brand.md` §11 where it makes sense on touch:

`BentoTheme`, `BrandMark`, `BrandLogo`, `BentoLoader`, `BentoTopBar` (search pill + avatar slot), `StatusAvatar` (ring states), `BentoNavigationSuite` (bar/rail), `BentoButton` (`primary`/`secondary`/`ghost`/`danger`, sizes 40/48/56 dp, `loading`), `BentoIconButton`, `BentoFab`, `BentoTextField` (label always, hint, error, `secure`), `CodeField` (grouped Crockford input with auto-dash and paste), `SegmentedButtons`, `BentoChip`/`FilterChip`, `BentoSheet` (modal bottom sheet with drag handle and predictive back), `BentoDialog` (only for destructive confirmations), `Callout`/`AttentionCard`, `Badge`, `StatusDot`, `ProgressBar`/`ProgressRing`, `EmptyState`, `ErrorState`, `Thumbnail` (placeholder, fade-in, overlays slot), `FloatingActionBar`, `Snackbar` with `Deshacer`, `SasEmojiRow`, `QrView`, `KindIcon` (kind palette), `ListRow`, `SectionHeader`, `SettingsRow`/`SwitchRow`.

Rules: one primary button per zone; destructive actions use `danger` and a sheet or dialog that states the consequence; shu only via `BentoFavorite` and `BrandMark`; every icon-only control has a content description and a tooltip on long-press/hover.

## 9. Screenshot and preview coverage

Every primitive and every feature screen state (loading-from-cache, live, empty, error, offline, selection) has `@Preview`s in light, dark, 200 % font, and compact/expanded widths, rendered by Roborazzi in CI. These screenshots are the visual review artifact for each agent's handoff.
