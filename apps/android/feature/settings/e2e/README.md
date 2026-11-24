# Backup, background, free-up-space and app-lock journeys on the emulator

Instrumented journeys of `orchestration/testing/android-journeys.md` owned by agent 41
(`app/src/androidTest/.../BackupJourneysTest.kt`), driven through the real UI against the embedded engine and a
fresh remote fake Telegram cloud per journey (`bento-sidecar fake-telegram-serve` on :8790 behind `adb reverse`).
Every journey starts from a cleared app, creates a new cloud through onboarding and inserts its own camera-roll photos
(unique JPEGs in `DCIM/Camera`, the default "Camera" bucket).

| Journey | Test | What runs for real |
|---|---|---|
| 1 camera-roll part: backup on with full media access; uploads on Wi-Fi only | `j01_firstRunBackupOn` | onboarding `Respaldar fotos`, MediaStore source, Wi-Fi upload, `svc wifi disable` → "esperando Wi-Fi" in Ajustes › Respaldo |
| 10 app closed, 30 new photos → next background run on Wi-Fi; metered waits | `j10_backgroundBackup` | WorkManager content-URI trigger → `work:backup` engine run, then the metered deferral |
| 11 initial backup with the UIDT notification, stopped mid-way, resumes, completion summary | `j11_initialBackup` | user-initiated data transfer job + notification, `Respaldar ahora` |
| 12 free up space: verified items only, system delete request, timeline unchanged | `j12_freeUpSpace` | preview, `MediaStore.createDeleteRequest` dialog (UiAutomator), confirm |
| 16 app lock: device-credential gate, locked on return, sync continues while locked | `j16_appLock` | platform BiometricPrompt with the PIN set by `locksettings` |
| English copy | `j91_englishSettings` (`APP_LOCALE=en-US`) | Ajustes, Respaldo, avatar |

```sh
cd apps/android
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest -PbentoBuildPython=$(uv python find 3.13)
flock "$HOME/.cache/bento-android-emulator.lock" feature/settings/e2e/run_journeys.sh                 # all, es-ES
APP_LOCALE=en-US flock "$HOME/.cache/bento-android-emulator.lock" feature/settings/e2e/run_journeys.sh j91_englishSettings
```

Deviations (not reproducible inside instrumentation, covered as closely as feasible):

- Journey 11 uses 120 photos instead of 5,000 (emulator time), and "reboot mid-way" is the system stopping the job
  (`TransferScheduler.stop`) and the transfer resuming; a real reboot kills the instrumentation.
- Journey 10's "swiped away" closes the activity (the engine's `ui` holder is released); the test process stays.
- Journey 16 cannot read `setRecentsScreenshotEnabled` back (no getter); recents hiding is covered by
  `SettingsLogicTest.recentsHidingFollowsTheLock` and the call site.
- The permission denial paths (denied, partial, revoked later) run in `BackupViewModelTest`/`SettingsUiTest`: the
  emulator's permission dialogs are system UI and grants persist across `pm clear` only through the test rule.
- Journeys 10 and 16 put one photo in the roll before turning backup on: with an empty roll there is no "Camera"
  bucket yet, so nothing is enabled and photos taken later are not backed up (a follow-up listed in agent 41's
  handoff: remember "backup on" and enable the suggested buckets when they first appear).
- Journey 11 inserts its 120 photos on the backup step (after sign-in): 120 MediaStore inserts during sign-in made the
  emulator miss the phone-number field.

`CLASS=TrustJourneysTest` runs another journey class with the same single fake cloud (used to re-check agent 38's
`j01_firstRunNewVault` and `j15_sessionRevoked` after the backup step replaced the placeholder).
