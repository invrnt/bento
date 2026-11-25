# Archivos, Buscar and Compartir journeys on the emulator

Instrumented journeys 6, 8 and 9 of `orchestration/testing/android-journeys.md`
(`app/src/androidTest/.../FilesJourneysTest.kt`), driven through the real UI against the embedded engine and the remote
fake Telegram cloud. Each journey starts from a cleared app and joins the host desktop's cloud with its recovery kit.

| Journey | Test | What runs for real |
|---|---|---|
| 6 Share to Bento: 3 images + 1 PDF from another app → sheet → chosen folder; dismissed ≤ 200 ms | `j06_shareToBento` | `ShareActivity` from an `ACTION_SEND_MULTIPLE` intent (MediaStore content URIs), destination picker, fd-handle imports |
| 8 Files: create folder, upload a folder tree via SAF, move, rename, pin offline, airplane mode | `j08_files` | Archivos UI, the system folder picker (DocumentsUI, driven with UiAutomator), offline pins, airplane mode |
| 9 Search: OCR text of a desktop-indexed image found on the phone; filters; no-results | `j09_searchDesktopOcr` | desktop upload → thumbnail → OCR job → index → encrypted sync → phone search UI |

`files_host.py` runs the remote fake cloud and one headless desktop on free host ports (or `BENTO_E2E_FAKE_PORT`,
`BENTO_E2E_DESKTOP_PORT`), which `adb reverse` exposes to the phone as :8790 and :8791. Only that desktop's OCR engine is
the backend's mock provider with a fixed text (RapidOCR models are not installed on the hosts); everything after OCR is
real. `run_journeys.sh` boots the AVD headless, starts the host, maps the ports with `adb reverse`, clears the app,
writes `files/dev-options.json` before each journey and pulls in-app screenshots to `build/files-journeys/`.

```sh
cd apps/android
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest -PbentoBuildPython=$(uv python find 3.13)
flock "$HOME/.cache/bento-android-emulator.lock" feature/files/e2e/run_journeys.sh               # all, es-ES
APP_LOCALE=en-US flock "$HOME/.cache/bento-android-emulator.lock" feature/files/e2e/run_journeys.sh j90_englishFiles
```

Not automated here: "process killed mid-copy → resumes" of journey 6 (killing the app kills the instrumentation; the
interrupted-batch journal is covered by `UploadsTest.interruptedBatchesAreReportedAfterAProcessDeath`), and the
document scanner (needs a camera and Play services' scanner module).
