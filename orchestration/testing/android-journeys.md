# Android Journeys and Release Gates

## Test layers

| Layer | Tooling | Runs |
|---|---|---|
| Backend android adapters/engine | pytest with fake bridges (`tests/unit/android`, `tests/api/android`) | every backend CI run, no Chaquopy |
| Kotlin unit | JUnit + Turbine + coroutines-test, fakes from `core/testing` | JVM, every PR |
| Compose UI | Compose UI test (Robolectric) per feature: states, semantics, actions | JVM, every PR |
| Screenshots | Roborazzi: light/dark, 200 % font, compact/expanded | JVM, every PR; diffs reviewed in handoff |
| Instrumented | AndroidX Test on emulator API 29 + latest, real embedded engine with `STORAGE_BACKEND=fake` | PR (smoke) and nightly (full) |
| Multi-device e2e | emulator app + host backend processes sharing the remote fake cloud (`api/android-endpoints.md` §9) + `wrangler dev` relay | nightly and before release |
| Performance | Macrobenchmark + Baseline Profile generator | nightly on emulator; physical matrix before release |
| Accessibility | Compose a11y checks (ATF) in UI tests + manual TalkBack/Switch Access pass | PR checks + release |

## Critical journeys (each automated where marked ⚙, all manually verified on the matrix)

1. ⚙ First run, new vault: Bienvenida → Telegram (fake QR auto-approve / phone code) → nube creada → backup on with full media access → kit saved by typing last group → Fotos shows camera roll within 2 s, uploads start on Wi-Fi only.
2. ⚙ Join from desktop by code: desktop host (host process) shows code → phone enters it → SAS shown on both → host approves → login token forwarded → phone signed in without number → library bootstraps progressively; a file uploaded on desktop appears on the phone ≤ 10 s while foreground.
3. ⚙ Join by App Link: `https://<site>/join#v=1&c=…` intent opens the join screen with the code filled.
4. ⚙ Recovery without other device: sign in → recovery code (paste and scan) → bootstrap.
5. ⚙ Partial media access: only selected photos back up; card explains; granting all later backs up the rest without duplicates.
6. ⚙ Share to Bento: 3 images + 1 PDF from another app → sheet → saved in chosen folder; sheet dismissed ≤ 200 ms; process killed mid-copy → resumes.
7. ⚙ Viewer: open from grid (shared element), swipe through 50 items, zoom, info sheet, favorite, delete with undo, video streams a remote file with seeking.
8. ⚙ Files: create folder, upload folder tree via SAF, move, rename, pin offline, airplane mode → pinned file opens, unpinned shows the offline message.
9. ⚙ Search: OCR text from a desktop-indexed image found on the phone; filters; no-results state.
10. ⚙ Background: app swiped away, 30 new photos taken → backed up within the next background run on Wi-Fi; metered network → waits with "esperando Wi-Fi".
11. ⚙ Initial backup of 5,000 items with UIDT notification, reboot mid-way, resumes, completion summary.
12. ⚙ Free up space: preview lists only verified items; system delete request; timeline unchanged.
13. ⚙ Phone as host: Ajustes › Dispositivos › Añadir → second emulator/desktop joins.
14. ⚙ Device removal from desktop: phone shows `device_removed`, library read-only, `Volver a unirme` works with a new identity.
15. ⚙ Session revoked in Telegram: reconnect screen keeps the library visible; signing in again resumes.
16. App lock: biometric gate, recents hidden, background sync continues while locked.
17. TalkBack: complete journeys 1, 2, 7, 8 using TalkBack only; Switch Access for 7.
18. 200 % font and landscape on journeys 1, 7, 8; tablet/foldable list-detail in Archivos and Ajustes.

## Device matrix (release)

Pixel 8 or newer (latest Android), Pixel 7a (reference), Samsung Galaxy A35 (One UI, reference), Xiaomi/Redmi mid-range (HyperOS, background restrictions), a 4 GB RAM Android 10 device (floor), a tablet or foldable, a Chromebook (optional, keyboard/mouse).

## Release gates

- All automated layers green; nightly multi-device e2e green 3 nights in a row.
- `product/android.md` §13 budgets met on the reference devices and the floor device (report attached).
- Zero crashes/ANRs across the matrix runs; Accessibility Scanner and lint without unaddressed accessibility or security warnings.
- Security review of the Android-specific surface (loopback token, Keystore wrapping, FileProvider, intents/deep links, `FLAG_SECURE`, backup exclusion, exported components) with every high/medium finding fixed.
- Copy review: every string in es and en, plurals checked, no "OK"/"Aceptar", Telegram compliance lines present.
