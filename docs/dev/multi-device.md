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

**Device B** (API on port 8001), the same with its own data directory:

```sh
export DATA_DIR="$PWD/data/dev/device-b" API_PORT=8001
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

> **Browser origin for the second UI.** In headless mode the API currently allows cross-origin requests only from `http://127.0.0.1:5173` and `http://localhost:5173`, so device B’s UI on port 5174 is blocked by CORS until the API derives its allowed origin from `WEB_PORT`. Until then, keep both APIs and workers running (sync between them keeps working) and switch the single UI on port 5173 between them by restarting Vite with the other `VITE_API_BASE_URL`.

### Pairing through a local relay

Without `BENTO_RELAY_URL`, pairing uses the Sync-channel fallback (**Pedir acceso a mis otros dispositivos**). To exercise the relay path, run it locally and give both instances its URL:

```sh
npm --prefix apps/relay run dev               # http://127.0.0.1:8787
export BENTO_RELAY_URL=ws://127.0.0.1:8787    # in every API and worker terminal
```

To test the web link, also run the site preview (`npm --prefix apps/site run preview`) and set `BENTO_PUBLIC_SITE_URL=http://127.0.0.1:8788`.

### Using the desktop shell as one device

Unpackaged desktop runs forward `STORAGE_BACKEND=fake` when started with `BENTO_DEV_STORAGE_BACKEND=fake`, so one of the two devices can be the Electron app (`npm --prefix apps/desktop start`). Make sure the same `BENTO_FAKE_TELEGRAM_DIR` reaches its sidecars.

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

The fake cloud has its own contract and multi-process tests under `apps/api/tests/integration/fake_telegram`, and the critical journeys in [critical-journeys.md](../../orchestration/testing/critical-journeys.md) run against it. Run the whole backend suite with `cd apps/api && uv run pytest`.
