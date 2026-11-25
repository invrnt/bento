# Android copy and accessibility review (Stage 22 release gate)

Scope: every string resource in `apps/android/core/strings/src/main/res/values{,-en}/` and the Compose code and Roborazzi goldens of `app`, `core/designsystem`, `core/background` and every feature **except** `feature/activity` and `feature/settings` (agent 41 is still writing them). Base: `0b611cf`. Static review only. Gradle was not run, so nothing here was checked on a device or emulator.

Deliverables:

- This report. Each finding has a severity (**blocker** / **major** / **minor**), `file:line`, the problem and the exact fix.
- `orchestration/execution/android-copy-fixes.patch`: the pure string fixes (C-1 … C-14), plus the 6 test assertions they change. Apply it with `git apply orchestration/execution/android-copy-fixes.patch` after merging Stage 22. It applies cleanly to `0b611cf` (`git apply --check`). Run `:core:strings:test` and the unit tests of `files`, `collections`, `photos` and `share` after applying.

Paths below are relative to `apps/android/`. `res/` means `core/strings/src/main/res/`.

## Gate status

| Gate line (`testing/android-journeys.md`) | Status |
|---|---|
| Every string in es and en | ✅ 906/904 keys; the 2 extra are `translatable="false"` (`app_name`, `ds_brand_name`). No key exists in only one locale. Placeholder signatures match (also enforced by `StringResourceParityTest`). |
| Plurals checked | ⚠️ Every count goes through `<plurals>`, and es has one/many/other. Six es `many` forms lack the "de" ("1.000.000 de elementos") → C-1. Counts are passed unformatted (no ICU grouping) → C-9 / A-11. |
| No "OK"/"Aceptar" | ✅ None. "Cancelar" is used only where it cancels a running flow (pairing, host code), which is acceptable. |
| Telegram compliance lines present | ✅ `common_telegram_api_notice` appears on Bienvenida (`OnboardingScreens.kt:178`) and Conecta tu Telegram (`TelegramSignIn.kt:227`). Ajustes › Acerca de belongs to agent 41: **it must also render this string** (product §9). The product name never contains "Telegram". |
| TalkBack / Switch Access on journeys 1, 2, 7, 8 | ⚠️ Mostly in place (custom actions on tiles and rows, live regions, headings). Open issues: A-1, A-2, A-3, A-5, A-6. |
| 200 % font and landscape | ⚠️ 200 %: three clipping defects in the goldens (A-1, A-2, A-4). **There are no landscape goldens at all** (A-7). |
| Accessibility Scanner clean | Not run (no device). A-8 and A-12 are what the Scanner is likely to flag. |

## Fix status (Stage 22g, copy/a11y fix agent)

Branch `t3/android-copy-accessibility-fixes`. "Fixed" means changed in code and covered by the named test or golden. Findings in `feature/activity` and `feature/settings` belong to agent 41.

| ID | Sev. | Status | Where / verification |
|---|---|---|---|
| C-1 | minor | Fixed | patch; new `StringResourceParityTest.spanishManyFormsSayDe` |
| C-2 | minor | Fixed | patch (nbsp units) + its 6 test assertions |
| C-3 | minor | Fixed | patch; `copyFollowsTheVoiceRules` now rejects `\"` in `values-en` |
| C-4 | minor | Fixed | `files_action_failed`, `pairing_host_action_failed`, `photos_action_failed` deleted; call sites use `common_error_generic` |
| C-5 | minor | Fixed | the 19 dead keys deleted; `viewer_seek_*`, `viewer_controls_show`, `search_filter_remove` now used (A-2, A-3, A-9); PDF keys see A-10; `common_*` reserved keys left for agent 41 |
| C-6 | minor | Fixed | new `common_metadata_pair` (replaces `collections_phone_row` / `collections_trash_row`) via `metadataPair()` in `LibraryScreens.kt`; new `common_label_value` for the onboarding step label |
| C-7 | major | Fixed | patch (`en favoritos`, `en la selección`); `MediaGridUiTest` |
| C-8, C-8c | minor | Fixed | patch |
| C-8b | minor | **Open, product decision** | "Imágenes › Bento" vs "Pictures › Bento" needs the product owner |
| C-9 | major | Fixed | patch; the count is also grouped now (`pluralCountResource`) |
| C-10, C-11, C-13 | minor | Fixed | patch |
| C-12 | major | Fixed | one formatter, `core/designsystem` `format/BentoFormat.kt` (`count`, `plural`, `bytes`, `formatCount`, `pluralCountResource`), used by `BentoNotifications` and every in-app count listed; `NotificationCopyTest` ("12.400 de 18.000 archivos", "Listo: 18.000 fotos respaldadas"). Note: es follows CLDR minimum grouping, so 4-digit numbers stay ungrouped ("1240"); product §5's "1.240" example would need a product call |
| C-14 | minor | Agent 41 | `common_state_offline` wording, account sheet |
| A-1 | major | Fixed | `SelectionTopBar`: one line, ellipsis, select-all as `Check` icon button; `MediaGridUiTest`, golden `photos-selection/*` |
| A-2 | major | Fixed | "Mostrar/Ocultar controles" custom action on photo and video pages (also on the poster before the player exists); `ViewerContentTest` (both tests on custom actions) |
| A-3 | major | Fixed | −10 s / play / +10 s `TransportButtons`; scrubber focusable with focus ring, ←/→ = ±5 s, keeps progress range + set-progress; `VideoSeekTest` (3 tests), golden `viewer-video-controls/*` |
| A-4 | major | Fixed | `FloatingActionBar(compactTitle = …)`: shows the count when the title does not fit (measured, so also at 1×, where it was "2 sel…"), full title stays the content description; `PrimitiveBehaviorTest.floatingActionBarShowsOnlyTheCountWhenTheTitleDoesNotFit`, golden `files/selection/*` |
| A-5 | major | Fixed | `FieldFrame`: always-present assertive live region carrying the error; `PrimitiveBehaviorTest.fieldErrorIsAnAssertiveLiveRegionSoAutoSubmittedCodesAnnounceIt`. TalkBack spot-check on device: see handoff |
| A-6 | major | Fixed | resend line is a `FlowRow`; golden `signin-code/font-200` |
| A-7 | major | Fixed | `BentoScreenshots.landscape` + `captureLandscape` + `LANDSCAPE_QUALIFIERS` (891 × 411 dp, `land`); goldens `onboarding/{welcome,signin-code}`, `recovery/kit-firstrun`, `photos/{photos-grid,photos-selection}`, `viewer/{viewer-photo,viewer-video-controls}`, `files/{list,selection}` `/landscape.png`. `sheet-item-menu` not added (sheets render in their own window outside the harness). The new goldens caught a real defect: `SetupScaffold` pinned its actions over ~40 % of a 411 dp-high window, hiding the code field and the recovery code; in a compact-height window (< 480 dp) the actions now scroll after the content (portrait unchanged) |
| A-8 | minor | Fixed | `BentoChip(selected, role)`; search chips use `Role.DropdownList` |
| A-9 | minor | Fixed | "Tipo: Fotos" description + "Quitar el filtro «Tipo»" custom action; `SearchUiTest.activeFilterChipNamesItsFilterIsADropdownAndCanBeRemoved`. The missing **Origen** filter is a contract gap, not done |
| A-10 | minor | Fixed | PDF search already announces "n de m" in a polite live region; unused `files_pdf_matches`, `files_pdf_no_text`, `files_pdf_loading` deleted |
| A-11 | minor | Fixed | grid `Ctrl +`/`Ctrl =` and `Ctrl −` change density |
| A-12 | minor | **Not done** | keyboard zoom needs the zoom state hoisted out of `PhotoPage` to the focused pager box; left for a follow-up |
| A-13 | minor | Fixed (except photo tiles) | focus ring on `BentoTextAction`, `ListRow` (so file rows), `SwitchRow`, `StatusAvatar`, `FileTile`. Photo tiles skipped on purpose: `bentoFocusRing` is `composed` + a state collector per tile, too costly for the photo grid's frame budget |
| A-14 | minor | Already fixed | recent rows already have a trailing remove icon button |
| A-15 | minor | Fixed | disabled Confirmar carries `recovery_confirm_hint` as state description |
| A-16 | minor | Fixed | confirmed: Material's tooltip anchor added an unlabeled long-click node. `BentoTooltip` now uses `enableUserInput = false` with a non-consuming pointer observer (long-press, mouse hover); `PrimitiveBehaviorTest.iconButtonTooltipAnchorIsNotASecondFocusStop` + existing long-press test |
| A-17 | minor | Fixed | `MediaFormat.bytes` and `Sizes.format` removed; `BentoFormat.bytes` (SI steps, as Android shows sizes) everywhere, so Files no longer shows 1024-based sizes that disagree with Photos ("812 MB", was "774 MB") |
| Reduced motion | — | Fixed | viewer arrow-key paging cuts instead of sliding with reduced motion |
| Dark selection circle | — | Fixed | unselected `SelectionCheck` on a 40 % scrim |
| Ajustes › Acerca de notice | — | Agent 41 | must render `common_telegram_api_notice`; apply A-5/A-13 via shared primitives |

## Counts

| Severity | Copy | Accessibility | Total |
|---|---|---|---|
| Blocker | 0 | 0 | 0 |
| Major | 3 | 7 | 10 |
| Minor | 13 | 10 | 23 |

---

## 1. Copy

### Cross-cutting (all features)

**C-1 · minor · plurals `many` forms (es)** — in Spanish, CLDR `many` covers 1 000 000, 2 000 000, … and needs "de" before the noun. Most plurals already have it; these six do not:

- `res/values/strings_collections.xml:103` `collections_count_items` many → `%1$s de elementos`
- `res/values/strings_collections.xml:88` `collections_trash_empty_confirm_body` many → `Se eliminarán para siempre %1$s de elementos (%2$s). No se puede deshacer.`
- `res/values/strings_collections.xml` `collections_trash_days_left` many → `Se eliminará en %1$s de días`
- `res/values/strings_photos.xml:67` `photos_trashed_many` many → `Se movieron %1$s de elementos a la papelera`
- `res/values/strings_photos.xml:72` `photos_card_partial_title` many → `Bento solo ve %1$s de fotos`
- `res/values/strings_photos.xml:77` `photos_album_count` many → `%1$s de elementos`

*(in patch)* Suggested follow-up: add a check to `StringResourceParityTest` that every es `many` item whose `other` item has a noun after the number contains `" de "`.

**C-2 · minor · units: no non-breaking space** — `res/values/strings_common.xml:51-55` (`common_unit_*`) and `res/values/strings_viewer.xml:10` (`viewer_info_dimensions`), in both locales. `12 MB` can wrap between the number and the unit (visible at 200 % in the trash golden: "· 2,4 / MB" risk). Replace the space with ` `: `%1$s MB`, `%3$s MP`. *(in patch, with the 6 test assertions that compare those strings: `CollectionsTests.kt:202-205`, `FilesLogicTest.kt:82-85`, `FilesUiTest.kt:59,181`, `ShareUiTest.kt:34`)*

**C-3 · minor · en quotation marks** — 22 en strings in `strings_devices.xml`, `strings_pairing.xml`, `strings_onboarding.xml` and `strings_recovery.xml` use escaped straight quotes (`\"%1$s\"`, e.g. `res/values-en/strings_pairing.xml:26`, `strings_onboarding.xml:93`, `strings_recovery.xml:34`). Files, search, photos and share use “ ”. Replace them all with `“…”`. *(in patch)* Follow-up: add `assertTrue(!text.contains("\\\""))` for `values-en` in `copyFollowsTheVoiceRules`.

**C-4 · minor · duplicate generic errors** — `files_action_failed` (`res/values/strings_files.xml:85`) and `pairing_host_action_failed` (`strings_pairing.xml:127`) duplicate `common_error_generic` word for word. `photos_action_failed` (`strings_photos.xml:48`) is a third wording ("No se pudo completar. Inténtalo otra vez."). Their en texts also differ ("That couldn’t be done." / "The action couldn’t be completed." / "That didn’t work."). AGENTS.md: no duplicated constants. Fix: delete the three keys and use `common_error_generic` at their call sites (code change, not in the patch).

**C-5 · minor · unused strings (41)** — none of these keys is referenced from any Kotlin or XML source. Some are probably reserved for agent 41 (`common_state_*`, `common_action_pause_backup`, `common_action_resume`, `common_action_copy`, `common_telegram_connect`, `common_error_storage_full`, `common_count_photos`, `common_count_devices`). Others point to missing UI, which A-3, A-9 and A-10 track: `viewer_seek_back`, `viewer_seek_forward`, `viewer_controls_show`, `search_filter_remove`, `files_pdf_matches`, `files_pdf_no_text`, `files_pdf_loading`, `viewer_error_open`, `viewer_loading_original`. Delete what is truly dead before release: `collections_albums_all`, `collections_telegram_started`, `collections_trash_row`, `ds_selected`, `ds_not_selected`, `ds_thumbnail`, `ds_video`, `ds_favorite`, `ds_progress_percent`, `files_badge_processing`, `files_sort`, `files_menu_more`, `files_move_all`, `files_detail_placeholder`, `photos_tile_loading`, `photos_density_month`, `search_date_pick`, `viewer_label`, `viewer_info_exposure`. Not in the patch, so as not to collide with agent 41.

**C-6 · minor · separators assembled in code** — `feature/collections/.../LibraryScreens.kt:161` and `:546` build rows with `.joinToString(" · ")`. `collections_phone_row` / `collections_trash_row` already exist for exactly this purpose. Use `stringResource(StringsR.string.collections_trash_row, left, size)`. The same applies to `OnboardingScreens.kt:293` (`"$label. $status"`): add `<string name="onboarding_creating_step_a11y">%1$s: %2$s</string>` and its en twin `%1$s: %2$s`.

### Photos (`strings_photos.xml`)

**C-7 · major · TalkBack tile labels disagree in gender for videos** — `res/values/strings_photos.xml:8,12`. `TileLabels.describe` (`feature/photos/.../MediaTile.kt:209-225`) appends `photos_tile_favorite` ("favorita") and `photos_tile_selected` ("seleccionada") to both "Foto" and "Video", so a video reads "Video, 0:42, 14 de marzo de 2024, favorita, seleccionada". Fix: `photos_tile_favorite` → `en favoritos`, `photos_tile_selected` → `en la selección` (en: `in favorites`; `selected` stays). *(in patch, with `MediaGridUiTest.kt:134`)*

**C-8 · minor** — `photos_sent_telegram` (`:46`) `Enviado a %1$s` → `Enviado a «%1$s»` (en `Sent to “%1$s”`). `photos_move_open_folder` (`:59`) `Abrir %1$s` → `Abrir «%1$s»` (en `Open “%1$s”`). Both now match `files_telegram_sent` and `files_move_open`. *(in patch)*

**C-8b · minor · not in patch** — `photos_saved_to_phone` (`:45`) "Guardado en Imágenes › Bento". Files apps show the MediaStore folder as `Pictures/Bento`, not "Imágenes". Use `Guardado en el teléfono, en Pictures › Bento` (en `Saved to your phone, in Pictures › Bento`), or confirm with the product owner that "Imágenes" matches what the target galleries display.

**C-8c · minor · en** — `photos_trashed_one` / `photos_trashed_many` say "moved to trash", while files say "Moved … to the trash". Unify on `Moved to the trash` / `Moved %1$s item(s) to the trash`. *(in patch)*

### Files (`strings_files.xml`)

**C-9 · major · upload failure count reads as a bare number** — `res/values/strings_files.xml:143` `files_upload_failed`: "3 no se pudieron añadir" / "3 couldn’t be added" (`FilesComponents.kt:450` passes the failed count). Replace with:

```xml
<item quantity="one">No se pudo añadir %1$s archivo</item>
<item quantity="many">No se pudieron añadir %1$s de archivos</item>
<item quantity="other">No se pudieron añadir %1$s archivos</item>
<!-- en -->
<item quantity="one">%1$s file couldn’t be added</item>
<item quantity="other">%1$s files couldn’t be added</item>
```

*(in patch)*

**C-10 · minor · en** — `files_telegram_title` / `photos_telegram_sheet_title` say "Send with Telegram", but `common_action_send_telegram` says "Send via Telegram…". Use `Send via Telegram`. *(in patch)*

### Design system / shared (`strings_designsystem.xml`)

**C-11 · minor** — `res/values/strings_designsystem.xml:44` `ds_kind_text` "Archivo" / "File" labels text and markdown files in Detalles › Tipo, which says nothing. Use `Archivo de texto` / `Text file`. *(in patch)*

### Notifications (`strings_notifications.xml`, `core/background`)

**C-12 · major · numbers not formatted in the backup notification** — `res/values/strings_notifications.xml:18,23` use `%1$d`/`%d`, and `core/background/.../Notifications.kt:86-89,118` pass raw `Int`s. The result is "1240 de 18000 archivos" and "Listo: 18000 fotos respaldadas" instead of the "1.240 de 18.000" / "18.000 fotos" required by product §5 and §8. The patch switches the placeholders to `%1$s`/`%2$s`, which renders the same with today's `Int` arguments. Code change still needed:

```kotlin
val nf = android.icu.text.NumberFormat.getInstance(context.resources.configuration.locales[0])
context.resources.getQuantityString(StringsR.plurals.bento_transfer_progress, progress.total, nf.format(progress.done), nf.format(progress.total))
context.resources.getQuantityString(StringsR.plurals.bento_transfer_finished_backup, count, nf.format(count))
```

The same problem exists in-app wherever `pluralStringResource(id, n, n)` feeds a `%1$s` with a raw `Int`: `FilesComponents.kt:449-451`, `PhotosScreen.kt:358`, `LibraryScreens.kt:402`, `ShareSheet.kt:154`, `MediaChrome.kt:60`, `FilesScreen.kt:540`. Pass `MediaFormat.number(n, locale)`, as `LibraryScreens.kt:217-219` already does. Minor at in-app sizes, but it is the same fix.

### Recovery / onboarding / collections (en tone)

**C-13 · minor · en wording** *(in patch)*:

- `recovery_rotate_confirm` "Create code" → `Generate code`, and "created" → "generated" in `recovery_rotate_failed`, `recovery_verify_invalid` and `recovery_sheet_footer`. es says "Generar" everywhere, and so do the other en recovery strings.
- `onboarding_error_flood_body` "We’ll try again by ourselves." → `We’ll try again automatically.`
- `onboarding_notifications_title` "Should we tell you about the backup?" → `Get notified about your backup?`
- `onboarding_qr_body` "…where your account already is." → `…where you’re already signed in.`
- `onboarding_qr_step3` "It refreshes by itself." → `It refreshes automatically.`
- `collections_trash_summary` "Empties itself after 30 days" → `Emptied automatically after 30 days`
- `collections_telegram_summary` "brought from your chats" → `imported from your chats`

**C-14 · minor · not in patch (wording choice for product)** — `common_state_offline` "Sin conexión. Se reanudará solo." differs from product §7 "Sin conexión — se reanudará solo". It is unused today; agent 41 should take the product wording when wiring the account sheet.

**Checked and fine:** tuteo throughout; no "vault"/"bóveda"/"MTProto"/"bearer"/"token" in user-facing copy (`pairing_vault_*` are key names only); "teléfono" for this phone and "computador" in pairing copy, as §13a requires; "tu nube", "kit de recuperación" and "sin conexión" used consistently; « » in es; the typographic ellipsis everywhere (enforced by test); every destructive confirmation states its consequence ("No se puede deshacer."). No hard-coded user-facing literals in `src/main` (the only literals are in `core/designsystem/src/debug` specimens and benchmarks). The plaintext disclosures (`common_plaintext_*`) exist for share, Telegram, open-with and save-to-phone.

---

## 2. Accessibility

### Photos (journey 7 entry, Switch Access)

**A-1 · major · selection title breaks mid-word at 200 %** — `feature/photos/.../MediaChrome.kt:59-69`. Golden `feature/photos/screenshots/photos-selection/font-200.png`: "4 / selecci / onados" next to "Seleccionar todo". Fix: show select-all as an icon button so the count keeps the space:

```kotlin
if (onSelectAll != null) {
    BentoIconButton(BentoIcons.CheckCheck /* add to icons.json if missing */, stringResource(StringsR.string.common_action_select_all), onSelectAll)
}
```

Also give the title `maxLines = 1, softWrap = false, overflow = TextOverflow.Ellipsis`. A count must never hyphenate.

**A-11 · minor · reduced-motion and keyboard paths for density** — pinch has a non-gesture alternative: `MediaGrid.kt:144-145` adds custom actions "Ver más fotos por fila" and "Ver fotos más grandes" ✅. There is no keyboard or mouse equivalent, although product §4.6 requires keyboard support on tablets and ChromeOS. Add `Ctrl +` / `Ctrl −` `onPreviewKeyEvent` on the grid, calling the same `state.changeDensity`. Range drag-select has an alternative too: taps in selection mode, the day "select all" circle and the custom actions ✅.

### Viewer (journey 7, TalkBack and Switch Access)

**A-2 · major · controls cannot be restored without touch on video, and possibly on photos** — `feature/viewer/.../VideoPage.kt:206`. `pointerInput { detectTapGestures(onTap) }` toggles the chrome but exposes **no semantics action**. Once `chromeVisible` is false (a sighted tap, zoom on a previous photo, then paging to a video), TalkBack and Switch Access cannot bring back the play button, scrubber, top bar or bottom actions. `viewer_controls_show` exists but is unused. Fix, in both `VideoPage` and around `PhotoPage`'s `ZoomableAsyncImage` (`PhotoPage.kt:155-163`):

```kotlin
val showLabel = stringResource(StringsR.string.viewer_controls_show)
Modifier.semantics { onClick(label = showLabel) { onTap(); true } }
```

Verify on device whether Telephoto's `onClick` already exposes a click action for photos; video certainly does not.

**A-3 · major · video seek is drag or tap only** — `VideoPage.kt:295-330`. The scrubber has `setProgress` (TalkBack volume keys) but is not `focusable()` and has no `onKeyEvent`, so Switch Access and keyboards cannot seek. The strings `viewer_seek_back` and `viewer_seek_forward` exist and are unused. Fix: add two `BentoIconButton`s (`BentoIcons.RotateCcw` / `RotateCw`, ±10 s; add them to `icons.json` if missing) beside `CenterPlayButton`, and make the scrubber `focusable()` with `Key.DirectionLeft/Right` → ±5 s.

**A-12 · minor · zoom is gesture-only** — pinch, double-tap and one-finger zoom have no non-gesture path. That is acceptable for Switch Access (zoom is not required by journey 7's Switch Access pass), but add keyboard `Ctrl +` / `Ctrl −` and `=`/`-` for ChromeOS. Dismissal and info have alternatives: back button and `Escape` ✅; overflow › Detalles ✅.

### Files (journey 8)

**A-4 · major · selection count truncates to "2 …" at 200 %** — `core/designsystem/.../Media.kt:287-295` (`FloatingActionBarContent`), used by `FilesScreen.kt:538-540`. Golden `feature/files/screenshots/selection/font-200.png`. Four 48 dp icons, close and overflow leave the title about 30 dp. Fix in the primitive: when `LocalDensity.current.fontScale >= 1.5f` (or when `BoxWithConstraints` gives the title < 96 dp), render only the number (`count.toString()`), and keep the full plural as `Modifier.semantics { contentDescription = title }`. Callers need to pass `count` alongside `title`. Photos avoids this because its title lives in the top bar (fix A-1 there).

**A-13 · minor · visible focus on custom clickables** — `bentoFocusRing` is applied only in `Buttons.kt`, `Selection.kt`, `Navigation.kt` (1) and `Foundation.kt`. `BentoTextAction` (`Snackbar.kt:142-153`), `ListRow`/`SwitchRow` (`Lists.kt:60-70,170-175`), `StatusAvatar` (`Navigation.kt:158-161`), file rows and grid tiles (`FilesComponents.kt:222,248`) and photo tiles (`MediaTile.kt:123`) rely on the ripple's 10 % focus layer. That is barely visible on photos and not visible in the dark scheme. Add `.bentoFocusRing(interaction, shape)` after each `clickable`/`combinedClickable`/`toggleable`; tiles need `RectangleShape`.

Checked and fine: rows merge semantics and expose Open / Select / Share / Favorite / Delete custom actions (`FilesComponents.kt:167-176`); badges reach TalkBack through `stateDescription`; the per-row overflow button is 48 dp with "Opciones de «nombre»"; long-press on the back affordance has an `onLongClickLabel` (`:311`), and the breadcrumb chips are the non-gesture path; the list has 160 dp of bottom padding, so the FAB never covers the last row.

### Onboarding (journey 1)

**A-5 · major · inline field errors are not announced** — `core/designsystem/.../TextFields.kt:91-106,203`. The error goes into the field node's `error()` semantics, and the visible text is `hideFromAccessibility()`. The Telegram code auto-submits on the last digit (`TelegramSignIn.kt:385`), as do the pairing code, recovery groups and kit confirmation, so focus never moves and TalkBack stays silent when "El código no es correcto" appears. Fix in `FieldFrame`: keep the visible error hidden, and add an announcing node when `error` changes from null to non-null:

```kotlin
error != null -> Row(Modifier.semantics { liveRegion = LiveRegionMode.Assertive; contentDescription = error }) { /* icon + text, text keeps hideFromAccessibility */ }
```

Verify with TalkBack in journey 1 (wrong code) and journey 2 (wrong pairing code). Also add a Compose test asserting `liveRegion` on the error node.

**A-6 · major · "Reenviar en …" splits mid-word and is clipped at 200 %** — `feature/onboarding/.../TelegramSignIn.kt:362-378`. Golden `signin-code/font-200.png`: "Reenvi / ar en …". Two ghost buttons share a `Row(SpaceBetween)` with no weights. Fix:

```kotlin
FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalArrangement = Arrangement.spacedBy(4.dp)) { /* same two buttons */ }
```

A single word wider than its slot always breaks mid-word, so the fix is layout (`FlowRow`, or stacking the buttons vertically when `fontScale >= 1.5f`), not text style. Audit every other `Row` holding two text buttons the same way. The welcome and sign-in goldens wrap cleanly.

### Search (journey 9)

**A-9 · minor · active filter chips lose their name** — `feature/search/.../SearchScreen.kt:284-302`. An active chip shows only its value ("Fotos", "En «Trabajo»"), so TalkBack reads "Fotos, seleccionado" with no filter name. The chip is a toggle (`BentoFilterChip`), but tapping it opens a sheet. Fix: `Modifier.semantics { contentDescription = "$filterName: $value"; role = Role.Button }` using a new `<string name="search_filter_a11y">%1$s: %2$s</string>` (en identical), and use the existing `search_filter_remove` for a per-chip clear action (`customActions`). Product §4.7 also lists an **Origen** filter (Este teléfono / Otros dispositivos / Telegram), which is missing (contract gap, not a11y).

**A-14 · minor · swipe-to-delete recents** — `SearchScreen.kt:467-476`. There is a custom action for TalkBack and Switch Access ✅, but no visible alternative for keyboard and mouse beyond "Borrar historial". Add a trailing 40/48 dp `BentoIconButton(BentoIcons.X, removeLabel, …)` to each recent row.

### Pairing / recovery / devices / share / collections

Checked and fine at 200 % and in dark mode (goldens `join-confirm-computer`, `host-code`, `kit-firstrun`, `devices/list`, `share/media`, `collections-hub`, `collections-trash`). The SAS emojis carry names (`ds_sas_label`); the host countdown is not a live region, so it is not chatty; `FLAG_SECURE` is out of scope here.

**A-15 · minor · recovery kit at 200 %** — `kit-firstrun/font-200.png`. The pinned bottom (Confirmar + Más tarde) plus the action buttons leave about 40 % of the height for content, and the "last group" field is below the fold while Confirmar is shown disabled. Add `Modifier.semantics { stateDescription = recovery_confirm_hint }` on the disabled Confirmar, or scroll the field into view when Confirmar is focused.

### Design system (cross-feature)

**A-8 · minor · `BentoFilterChip` used as a menu trigger** — `Selection.kt` exposes checkbox/selected semantics. Callers that open a sheet (search) need `Role.DropdownList`. Add a `BentoChip(selected = …)` variant, or a `role` parameter.

**A-16 · minor · tooltips on `BentoIconButton`** — each icon button wraps `BentoTooltip(contentDescription)`. Confirm that the tooltip anchor does not add a second focusable node; a TalkBack pass on the photo selection bar is enough. Otherwise use `Modifier.semantics { hideFromAccessibility() }` on the tooltip content.

**A-17 · minor · duplicated byte formatter** — `feature/photos/.../MediaFormat.kt:87` and `feature/files/.../FileFormat.kt:100` (`Sizes.format`) are two implementations of the same unit ladder over `common_unit_*` (AGENTS.md: no duplicated helpers). Move one into `core/designsystem` or `core/data` (it is a formatter).

### Coverage

**A-7 · major · no landscape goldens** — the screenshot variants are `light`, `dark`, `font-200`, `compact` and `expanded` only. The release gate requires 200 % **and landscape** on journeys 1, 7 and 8. Add a `landscape` variant (`qualifiers = "w891dp-h411dp-land"`) to the Roborazzi harness for at least: onboarding welcome, signin-code, recovery kit-firstrun, photos-grid, photos-selection, viewer-photo, viewer-video-controls, files list, files selection, files sheet-item-menu. The kit and sign-in screens pin their buttons to the bottom and are the most likely to break at 411 dp height.

**A-10 · minor · PDF search UI incomplete?** — `files_pdf_matches`, `files_pdf_no_text` and `files_pdf_loading` are unused, so match count and "no text" states are never announced. If PDF search is shipped, show the match count in a `liveRegion = Polite` text. Otherwise remove the strings.

**Reduced motion** ✅ — `BentoMotion.reduced` collapses transforms to 120 ms fades, the shared element uses `tween(0)` (`SharedMedia.kt:37-38`), and the grid density crossfade honours it (`MediaGrid.kt:150`). The viewer's keyboard paging uses `animateScrollToPage`, a slide; wrap it with `if (reduced) scrollToPage`.

**Dark mode contrast** — no failures visible in the dark goldens sampled (`photos-grid`, `files/list`, `onboarding/welcome` expanded). The tile overlay chips sit on a 40 % black scrim and stay legible on light thumbnails. The unselected selection circle on light-grey thumbnails is low contrast (light golden `photos-selection`); give the circle the same 40 % scrim fill.

---

## Top 10

1. **A-2** Viewer: no accessible way to bring hidden controls back (video certain, photo to verify). Blocks the Switch Access pass of journey 7.
2. **A-5** Field errors (wrong Telegram, pairing or recovery code) are not announced to TalkBack in journeys 1 and 2.
3. **A-3** Video seek only by drag or tap; the ±10 s buttons are missing although their strings exist.
4. **A-1** Photos selection title "selecci/onados" at 200 %.
5. **A-4** Files selection count truncated to "2 …" at 200 % (`FloatingActionBar` primitive).
6. **A-6** "Reenviar en …" clipped mid-word at 200 % on the code screen (journey 1).
7. **A-7** No landscape goldens; the gate requires landscape on journeys 1, 7 and 8.
8. **C-12** Backup notification shows "18000" instead of "18.000" (and in-app counts are ungrouped too).
9. **C-7** Video tiles read "favorita, seleccionada" (gender mismatch) in TalkBack.
10. **C-9** Upload failure card reads "3 no se pudieron añadir" with no noun.

Also for agent 41: render `common_telegram_api_notice` in Ajustes › Acerca de, reuse `common_state_*` rather than adding new keys, and apply A-5 and A-13 (via the shared primitives) to the settings switches and fields.
