# Trust journeys on the emulator

Instrumented journeys 1-4 and 13-15 of `orchestration/testing/android-journeys.md`
(`app/src/androidTest/.../TrustJourneysTest.kt`), driven through the real UI against the embedded engine and the
fake Telegram cloud.

| Journey | Test | Devices |
|---|---|---|
| 1 First run, new vault (sign-in, cloud, backup hand-off, kit by last group) | `j01_firstRunNewVault` | phone (own fake cloud) |
| 2 Join from a desktop by code (SAS on both, host approves, login token forwarded, desktop change syncs) | `j02_joinFromDesktopByCode` | phone + `desktop` |
| 3 Join by App Link (code prefilled, joining still takes a tap) | `j03_joinByAppLink` | phone |
| 4 Recovery without the other device (sign in, paste the kit code, bootstrap) | `j04_recoveryWithoutOtherDevice` | phone + `desktop` (cloud owner) |
| 13 Phone as host (Dispositivos › Añadir, a desktop joins with the shown code) | `j13_phoneAsHost` | phone + `desktop` + `desktop2` |
| 14 Removed from the desktop, joins again with a new identity | `j14_removedFromDesktop` | phone + `desktop` |
| 15 Session closed: reconnect screen over the library, sign in resumes | `j15_sessionRevoked` | phone |
| English copy | `j90_englishCopy` (`APP_LOCALE=en-US`) | phone |

`trust_host.py` runs the host side on 127.0.0.1: the remote fake cloud (`bento-sidecar fake-telegram-serve`, :8790),
the backend's relay double (mirrors `apps/relay`, :8788) and two headless desktops (API + worker, :8791/:8792).
`run_journeys.sh` boots the AVD headless, starts the harness, maps the ports with `adb reverse`, clears the app and
writes `files/dev-options.json` before each journey, and pulls in-app screenshots to
`build/trust-journeys/screens-<locale>/`.

```sh
cd apps/android
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest -PbentoRelayUrl=ws://127.0.0.1:8788 \
  -PbentoSiteUrl=https://bento.example -PbentoBuildPython=$(uv python find 3.13)
flock "$HOME/.cache/bento-android-emulator.lock" feature/pairing/e2e/run_journeys.sh            # all, es-ES
APP_LOCALE=en-US flock "$HOME/.cache/bento-android-emulator.lock" feature/pairing/e2e/run_journeys.sh j90_englishCopy
```

Not automatable here (verified by unit/UI tests instead): scanning a QR with the emulator camera (the scanner is
covered with a fake camera slot), the Telegram app's `tg://login` confirmation (no Telegram app on the emulator),
and the camera-roll part of journey 1 (`Route.BackupSetup` and Fotos belong to agents 41 and 39).
