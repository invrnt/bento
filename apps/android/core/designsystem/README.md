# core/designsystem

Bento's Compose design system. Source of truth: `orchestration/design-system/brand.md`, mapped by
`orchestration/design-system/android.md`. Feature code builds screens only from these primitives, reads colors from
`BentoTheme.colors` and text from `core/strings`.

## Generated sources (do not edit)

| File | Generator | Source |
|---|---|---|
| `generated/BentoTokens.kt`, `res/values{,-night}/bento_colors.xml` | `scripts/generate_tokens.mjs` | `apps/web/src/styles/tokens.css` (OKLCH → sRGB, CSS Color 4 gamut mapping) |
| `generated/BentoIcons.kt` | `scripts/generate_icons.mjs` | `scripts/icons.json` + `lucide-static` (pinned to the `lucide-react` version of `apps/web`) |

```sh
cd apps/android/scripts
npm ci              # installs lucide-static
npm run generate    # rewrite generated files
npm run check       # drift check, exit 1 on diff (also Gradle :core:designsystem:verifyBentoGenerated, wired into `check`)
npm test            # generator tests (node:test)
```

Add an icon: append `{ "name": "PascalName", "lucide": "file-name", "use": "…" }` to `icons.json` (`"nav": true`
also emits a stroke-1.75 `BentoNavIcons` variant; `"filled": true` emits `<Name>Filled`), then `npm run generate`.

## Theme

- `BentoTheme(darkTheme, reducedMotion = null /* system */)`: every Material 3 color, type and shape slot comes from
  tokens (role table in android.md §1). Dynamic color is never used. `surfaceTint` is transparent, so there is no tonal tint.
- `BentoMediaTheme { }`: always-dark `media` scheme for the viewer and player.
- `BentoTheme.colors / typography / shadows / motion / isDark / isMedia`.
- `BentoShapes`: `xs sm md control(12 dp mobile) lg xl hero sheet full`.
- `BentoMotion`: `color()` 120 ms, `state()` 180 ms, `layer()` 260 ms, `follow()` spring 0.9/600, `slideUpIn`, `popIn`…
  With reduced motion, each of these becomes a 120 ms fade. Reduced motion is read live from `ANIMATOR_DURATION_SCALE`.
- `bentoHaptics().perform(BentoHaptic.LongPress | SegmentTick | Confirm | Reject)` honors the system setting and
  falls back on API 29/30. Override with `LocalBentoHaptics` in tests.
- `Modifier.bentoShadow(BentoElevation.Xs…Xl, shape)` applies ink-tinted token shadows (floating layers only).
- Fonts: Geist Variable and Geist Mono Variable (OFL, `GEIST-OFL.txt`), instanced at 400/500/600.

## Primitives (package `dev.bento.designsystem.component`)

Brand: `BrandMark(size, contentDescription?)`, `BrandLogo(markSize, label)`, `BentoLoader(size, contentDescription)`,
`bentoLoaderAnimatedVector()` (`R.drawable.avd_bento_loader`, the splash animation). Launcher: `@mipmap/ic_launcher`
(adaptive with a monochrome layer); notifications use `@drawable/ic_stat_bento`.

The full list with parameters is in the handoff and in the KDoc. Summary:
`BentoTopBar`, `StatusAvatar`, `BentoNavigationSuite`, `BentoButton`, `BentoIconButton`, `BentoFab`, `BentoTextField`,
`CodeField` (+ `CrockfordCode`), `SegmentedButtons`, `BentoChip`, `BentoFilterChip`, `BentoSwitch`, `BentoSheet`
(+ `rememberBentoSheetState`), `BentoDialog`, `Callout`, `AttentionCard`, `Badge`, `StatusDot`, `ProgressBar`,
`ProgressRing`, `EmptyState`, `LoadingState`, `ErrorState`, `Thumbnail`, `SelectionCheck`, `VideoBadge`,
`BentoFavorite`, `BentoFavoriteButton`, `FloatingActionBar`, `BentoSnackbarHost` (+ `BentoSnackbarHostState.showUndo`),
`SasEmojiRow`, `QrView` (+ `QrMatrix`), `KindIcon` (+ `FileKind`), `ListRow`, `SectionHeader`, `SettingsRow`,
`SwitchRow`, `BentoIcon`, `BentoTooltip`, `BentoTextAction`.

Rules that every primitive enforces:
- 48 dp touch targets, including for 40 dp visuals.
- Content descriptions and long-press/hover tooltips on icon-only controls.
- Explicit live regions.
- No text in `ink-subtle`, which is below 4.5:1 (see below).

## Lint (`core/designsystem/lint`, published with this module)

- `BentoNoRawColor`: `Color(0x…)`, `Color.Red`, `parseColor` outside `designsystem.theme` / `designsystem.generated`.
- `BentoMaterialColorScheme`: `MaterialTheme.colorScheme` outside `dev.bento.designsystem`.
- `BentoHardcodedText`: string literals passed to text parameters of composables (`text`, `label`, `title`,
  `contentDescription`…). Previews, specimens and the kitchen sink are exempt.

## Kitchen sink, previews, screenshots

- Debug only: `src/debug/.../specimen/Specimens.kt` defines one specimen per primitive state group. It is shared by
  `@BentoPreviews` (light, dark, 200 %, compact 320 dp, expanded 840 dp), `KitchenSinkActivity`, and the Roborazzi suite.
  The activity has theme, reduced-motion and live sheet/dialog/snackbar/selection demos. It is merged into any debug app:
  `adb shell am start -n <applicationId>/dev.bento.designsystem.kitchensink.KitchenSinkActivity`.
- Goldens: `screenshots/<specimen>/<light|dark|font-200|compact|expanded>.png`.
  - Record: `./gradlew :core:designsystem:recordRoborazziDebug`.
  - Verify: `./gradlew :core:designsystem:verifyRoborazziDebug`.
- JVM tests run on Robolectric SDK 35: Robolectric's SDK 36 sandbox needs Java 21, and the project JDK is 17.

## Decisions and open brand questions

- Placeholders use `ink-muted`; `ink-subtle` is for icons and strokes only. The reason is that `ink-subtle` measures
  3.65–4.30:1 in light (4.21:1 on dark `raised`), and brand §13 requires 4.5:1 for text.
- Pressed fills use `accent-hover` / `danger-hover` only in light mode. In dark mode, white text on them is 4.1:1 and 3.8:1.
- `kind-folder` on `kind-folder-soft` (light) is 2.2:1, below the 3:1 UI rule. This is a known item in `ContrastTest`.
- The launcher icon follows the brand.md §3 geometry, flat and in token colors. `bento-icon.svg` has gradients and
  different compartment radii, which §3 forbids.
- `QrView` is always dark-on-light, because inverted codes fail some scanners.
- Under reduced motion, `BentoLoader` is still: brand §9 says reduced motion disables all motion.
