# Multi-device development with the fake Telegram cloud

`STORAGE_BACKEND=fake` replaces Telegram with a directory on disk that simulates one Telegram account: channels, messages, documents, pinned messages, chats and sign-in. Two Bento instances that share the same directory behave like two devices of the same user, so you can develop sync, pairing, recovery, inbox, sharing and import without a real account, network access or `FLOOD_WAIT`.

The fake is rejected when `ENVIRONMENT=production` and is never selectable in packaged release builds.

## What the fake account provides

- One simulated user, “Ana Demo”. Each Bento instance is a separate authorization (visible to the other instances like Telegram sessions).
- QR sign-in approves itself after about 2 seconds. Set `BENTO_FAKE_TELEGRAM_MANUAL_LOGIN=1` to approve by hand instead:

  ```sh
  curl -X POST -H 'X-Bento-Client: web' http://127.0.0.1:8000/api/dev/fake-telegram/approve-login
  ```

- Phone sign-in accepts the code `12345`. With `BENTO_FAKE_TELEGRAM_2FA=1` the account also asks for the password `bento-demo`.
- Saved Messages and two seeded chats with a few generated media items, for the import and share flows.

## Run two instances

Prerequisites: the backend and web dependencies (`uv sync --project apps/api --extra dev` and `npm --prefix apps/web ci`). Run every command from the repository root. Environment variables take precedence over the root `.env`.

Export these in every terminal below (they are shared by both instances):

```sh
export STORAGE_BACKEND=fake
export ENVIRONMENT=local
export BENTO_FAKE_TELEGRAM_DIR="$PWD/data/dev/fake-telegram"
```

**Device A** (API on port 8000, UI on 5173), one terminal per process:

```sh
export DATA_DIR="$PWD/data/dev/device-a" API_PORT=8000
uv run --project apps/api python -m bento.interfaces.desktop.launcher migrate
uv run --project apps/api python -m bento.interfaces.http.main
```

```sh
export DATA_DIR="$PWD/data/dev/device-a"
uv run --project apps/api python -m bento.interfaces.worker.main
```

```sh
VITE_API_BASE_URL=http://127.0.0.1:8000/api npm --prefix apps/web run dev -- --port 5173 --strictPort
```

**Device B** (API on port 8001, UI on 5174), the same with its own data directory:

```sh
export DATA_DIR="$PWD/data/dev/device-b" API_PORT=8001 WEB_PORT=5174
uv run --project apps/api python -m bento.interfaces.desktop.launcher migrate
uv run --project apps/api python -m bento.interfaces.http.main
```

```sh
export DATA_DIR="$PWD/data/dev/device-b"
uv run --project apps/api python -m bento.interfaces.worker.main
```

```sh
VITE_API_BASE_URL=http://127.0.0.1:8001/api npm --prefix apps/web run dev -- --port 5174 --strictPort
```

Each instance needs its own `DATA_DIR` (database, cache and key store) and its own API port; only `BENTO_FAKE_TELEGRAM_DIR` is shared. In headless mode each instance generates its device wrapping key in `<DATA_DIR>/secure/wrapping.key` unless you set `BENTO_DEVICE_WRAPPING_KEY`; never export the same wrapping key for both.

> **Browser origin.** Each API accepts cross-origin requests only from its own UI, `http://127.0.0.1:$WEB_PORT` and `http://localhost:$WEB_PORT` (default 5173). That is why device B’s API runs with `WEB_PORT=5174`.

### Pairing through a local relay

Without `BENTO_RELAY_URL`, pairing uses the Sync-channel fallback (**Pedir acceso a mis otros dispositivos**). To exercise the relay path, run it locally and give both instances its URL:

```sh
npm --prefix apps/relay run dev               # http://127.0.0.1:8787
export BENTO_RELAY_URL=ws://127.0.0.1:8787    # in every API and worker terminal
```

To test the web link, also run the site preview (`npm --prefix apps/site run preview`) and set `BENTO_PUBLIC_SITE_URL=http://127.0.0.1:8788`.

### Using the desktop shell as one device

Unpackaged desktop runs forward `STORAGE_BACKEND=fake` when started with `BENTO_DEV_STORAGE_BACKEND=fake`, so one of the two devices can be the Electron app (`npm --prefix apps/desktop start`). Make sure the same `BENTO_FAKE_TELEGRAM_DIR` reaches its sidecars.

### Scripted: both devices in one command

`scripts/smoke/two_devices.py` starts the same processes (real `migrate`, API and worker entrypoints) for devices `a` and `b` under `data/dev/smoke/`, with a shared fake cloud and an in-process relay double, and prints each device’s API URL and the matching Vite command (`--web` starts the Vite servers too):

```sh
uv run --project apps/api python scripts/smoke/two_devices.py                  # fresh devices: try onboarding and pairing
uv run --project apps/api python scripts/smoke/two_devices.py --setup paired   # a has a vault and samples, b is paired
uv run --project apps/api python scripts/smoke/two_devices.py --web --reset    # start over and run both UIs (5173, 5174)
```

Options: `--devices 3` adds device `c` (API 8002, UI 5175), `--no-relay` forces the Sync-channel fallback, `--relay-url ws://127.0.0.1:8787` uses `wrangler dev`, `--manual-login` keeps the second device’s own QR from approving itself. Ctrl+C stops everything; state survives until `--reset`. While it runs, another terminal can simulate Telegram trouble or a forwarded file:

```sh
uv run --project apps/api python scripts/smoke/two_devices.py fault flood_wait 90   # Activity explains waits longer than 60 s
uv run --project apps/api python scripts/smoke/two_devices.py fault network 30      # Telegram unreachable
uv run --project apps/api python scripts/smoke/two_devices.py fault clear
uv run --project apps/api python scripts/smoke/two_devices.py inbox ~/Pictures/foto.jpg
```

## A journey to try

1. On A: **Empezar** → the QR approves itself → Bento creates the vault and shows the recovery code.
2. Upload a few files on A.
3. On A: Ajustes › Dispositivos › **Añadir dispositivo**. On B: **Ya uso Bento en otro dispositivo** → type the code → compare the emojis → **Añadir** on A. B downloads the library.
4. Rename, move and delete on one device; watch the other converge.
5. Remove B from A: A rotates the keys and shows a new recovery code.
6. Wipe `data/dev/device-b`, start B again and recover it with **No tengo el otro dispositivo** and the new code.
7. Inspect what “Telegram” stored under `data/dev/fake-telegram`: only ciphertext, random part names and the plaintext vault header.

## Reset

Stop every process and delete `data/dev/` (it is inside the git-ignored `data/` directory).

## Automated tests

The fake cloud has its own contract and multi-process tests under `apps/api/tests/integration/fake_telegram`. The critical journeys 20–29 of [critical-journeys.md](../../orchestration/testing/critical-journeys.md) run end to end in `apps/api/tests/e2e`: real API and worker processes per device, one shared fake cloud and the relay double, driven over HTTP only. They take about two minutes, so the default backend run (`cd apps/api && uv run pytest`) skips them; run them with:

```sh
cd apps/api && uv run pytest -m e2e      # or: make e2e
```

Set `BENTO_E2E_TRACE=1` to print how long each wait took; a failing journey attaches the device logs to its report and skips the journeys that build on it.
