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

`trust_host.py` runs the host side on 127.0.0.1: the remote fake cloud (`bento-sidecar fake-telegram-serve`),
the backend's relay double (mirrors `apps/relay`) and two headless desktops (API + worker). `run_journeys.sh` boots
the AVD headless, starts the harness on free host ports (or `BENTO_E2E_{RELAY,FAKE,DESKTOP,DESKTOP2}_PORT`), maps the
phone's fixed :8788 (relay), :8790 (fake cloud), :8791/:8792 (desktops) onto them with `adb reverse`, clears the app
and writes `files/dev-options.json` (`relay_url`, `fake_telegram_url`) before each journey, saves each journey's app
logcat, and pulls in-app screenshots to `build/trust-journeys/screens-<locale>/`. Any debug build works: the relay
comes from the dev options and App Links are accepted for `bentoSiteHost` (`bento.example` by default). The host's
sidecars are stopped on every exit, including failures and Ctrl-C.

```sh
cd apps/android
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest -PbentoBuildPython=$(uv python find 3.13)
flock "$HOME/.cache/bento-android-emulator.lock" feature/pairing/e2e/run_journeys.sh            # all, es-ES
APP_LOCALE=en-US flock "$HOME/.cache/bento-android-emulator.lock" feature/pairing/e2e/run_journeys.sh j90_englishCopy
```

Not automatable here (verified by unit/UI tests instead): scanning a QR with the emulator camera (the scanner is
covered with a fake camera slot), the Telegram app's `tg://login` confirmation (no Telegram app on the emulator),
and the camera-roll part of journey 1 (`Route.BackupSetup` and Fotos belong to agents 41 and 39).
