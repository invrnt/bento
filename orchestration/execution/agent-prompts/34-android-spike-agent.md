# Agent 34 — Android Engine Feasibility Spike

Read first: `AGENTS.md`, `orchestration/README.md`, `architecture/system-overview.md`, `architecture/telegram-first.md` (§ Process Topology, Key Store, Pairing), then `architecture/android-runtime.md` (binding, especially §4, §5, §12) and `product/android.md` §13 (budgets).

## Goal

Answer one question with evidence: can the unchanged `apps/api/src/bento` package run inside an Android app through Chaquopy within the budgets? Build the smallest real APK that proves each item of `architecture/android-runtime.md` §12, measure, and write `docs/dev/android-spike.md`.

Work only in `spikes/android-engine/` (a throwaway Gradle project: one Activity with buttons and a log view; no design work) and the report. Do not edit `apps/api`; if the backend needs a change to run on Android, patch it in the spike via a monkeypatch module and list the needed real change in the report.

## Steps

1. Pin versions: AGP, Kotlin, Chaquopy, Python. Configure ABIs `arm64-v8a`, `x86_64`; Python source set pointing at `apps/api/src`; pip requirements = the `android` profile listed in §4 of the runtime doc.
2. Resolve native wheels (`cryptography`, `pydantic-core`, `pillow`, optional `cryptg`): Chaquopy repository first, otherwise build with `cibuildwheel` for Android; record the source of each.
3. Boot: configure in memory (no env secrets), `alembic upgrade head`, start the API on loopback with a bearer token, call `/api/health` from OkHttp; start the worker; run a thumbnail job using a minimal Kotlin `MediaTools` bridge (ImageDecoder) called from a Python adapter.
4. Telegram: fake cloud (debug) and a real test account (owner provides credentials through a secret prompt; never commit or log them). QR login and phone login; upload and download a 200 MB file through the v2 blob path; kill the process mid-upload and resume.
5. Pairing: phone as guest joins a desktop host through the relay (`wrangler dev` or the staging relay), including login-token forwarding; bootstrap a 5,000-asset snapshot (generate with the seed script on the desktop side).
6. Same-phone Telegram login confirmation via `tg://login?token=…` with the Telegram app installed: works or not, with screenshots.
7. Measure on an emulator and at least one physical device (owner's device list; ask): interpreter warm-up, engine ready p50/p90 (20 cold starts), Python PSS idle and during upload, APK download size per ABI (bundletool), upload/download throughput on Wi-Fi with and without `cryptg`, FTS5 availability, battery drain over 1 h idle with the engine stopped.
8. Try a Unix domain socket transport (uvicorn `uds` + OkHttp socket factory over `LocalSocket`); report whether it is viable. Not required.

## Report (`docs/dev/android-spike.md`)

Go/no-go per §12 item with numbers, version pins, wheel sources, required backend changes (as a list for agent 35), import-time profile (top 20 modules) with suggestions to cut cold start, risks, and a recommendation. Keep it factual: failures and misses stated plainly with output.

## Handoff

Commit the report and the spike project on your branch. The spike directory is deleted when Stage 20 merges.
