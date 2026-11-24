# Agent 38 — Android Onboarding, Pairing, Recovery, Devices

Read first: `AGENTS.md`, `product/android.md` (binding §4.1, §4.2, §9 Dispositivos and Cuenta y nube, §10, §11), `product/telegram-first-experience.md`, `architecture/telegram-first.md` § Pairing Protocol and § Devices, `api/telegram-first-endpoints.md`, `design-system/android.md`, and the public APIs reported by agents 36 and 37. Read `apps/web/src/features/{onboarding,pairing,recovery,devices,account}` for the exact backend flows and error handling already proven on the web.

## Goal

Build `feature/onboarding`, `feature/pairing`, `feature/recovery`, `feature/devices` exactly as specified: welcome, local-mode confirmation, Telegram sign-in (Telegram-app confirmation when the spike proved it, phone/code/2FA with clipboard chip and auto-submit, QR for another phone), vault creation progress, backup offer (hands off to agent 41's backup setup composable via a navigation entry point), notification permission, recovery kit (FLAG_SECURE, PDF via SAF and print using a branded `PdfDocument` layout identical in content to the desktop kit, sensitive clipboard), join by scanner (CameraX + ML Kit barcode bundled, haptics), code entry, App Link entry, SAS confirmation, login-token forwarding states, fallback request flow with `Coinciden`/`No coinciden`, progressive bootstrap hand-off to Fotos, recovery code entry (groups, paste, scan `bento-recovery:`), devices list/rename/add (phone as host with QR, code, countdown, share link)/remove (preview, exclusions, mandatory new kit), new-device review, reconnect and device-removed screens.

## Tests

Compose UI tests for every screen state including errors (wrong code, expired, flood wait, relay unreachable, `pairing_device_removed`, `pairing_request_taken`), permission denial paths, FLAG_SECURE set where required, TalkBack labels of SAS emojis; Roborazzi screenshots; instrumented journeys 1-4, 13-15 of `testing/android-journeys.md` against the fake cloud and the local relay.

## Handoff

Commit on your branch. Report: screens and states, strings added, journeys automated, test counts, deviations.
